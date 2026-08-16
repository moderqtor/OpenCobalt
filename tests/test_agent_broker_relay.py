from __future__ import annotations

from pathlib import Path

import pytest

from opencobalt.agent_broker.broker import BrokerExecution
from opencobalt.agent_broker.models import AgentBrokerSession
from opencobalt.agent_broker.relay import (
    COMMAND_MARKER,
    RESULT_MARKER,
    GitHubAgentRelay,
    command_comment,
    parse_command_comment,
)
from opencobalt.agent_broker.store import AgentBrokerStore


class FakeBroker:
    def __init__(self, store: AgentBrokerStore, root: Path) -> None:
        self.store = store
        self.root = root
        self.starts: list[dict] = []
        self.continues: list[tuple[str, str, bool]] = []
        self.sessions: dict[str, AgentBrokerSession] = {}

    def start(self, *, repository: str, objective: str, model=None, execute=False, **_kwargs):
        self.starts.append(
            {"repository": repository, "objective": objective, "model": model, "execute": execute}
        )
        session = AgentBrokerSession(
            session_id="agent-relay-test",
            provider_session_id="thr-relay" if execute else None,
            objective=objective,
            repository_path=repository,
            workspace_id="ws-relay",
            workspace_path=str(self.root / "staging"),
            source_branch="agent-broker-v0",
            starting_head="abc123",
            status="active" if execute else "planned",
            turn_count=1,
            last_receipt_id="receipt-relay",
        )
        self.sessions[session.session_id] = session
        self.store.save_session(session)
        return session, BrokerExecution(
            status="complete" if execute else "planned",
            executed=execute,
            receipt_id="receipt-relay",
            provider_session_id=session.provider_session_id,
            response="implemented the bounded change" if execute else "",
        )

    def continue_session(self, session_id: str, prompt: str, *, execute=False, **_kwargs):
        self.continues.append((session_id, prompt, execute))
        session = self.sessions[session_id]
        session = session.model_copy(
            update={
                "turn_count": session.turn_count + 1,
                "last_receipt_id": "receipt-continue",
            }
        )
        self.sessions[session_id] = session
        self.store.save_session(session)
        return session, BrokerExecution(
            status="complete" if execute else "planned",
            executed=execute,
            receipt_id="receipt-continue",
            provider_session_id=session.provider_session_id,
            response="follow-up complete" if execute else "",
        )

    def require_session(self, session_id: str):
        return self.sessions[session_id]

    def list_sessions(self, *, limit=10):
        return list(self.sessions.values())[:limit]

    def stop(self, session_id: str):
        session = self.sessions[session_id].model_copy(update={"status": "stopped"})
        self.sessions[session_id] = session
        self.store.save_session(session)
        return session, None


class FakeGitHub:
    def __init__(self, comments: list[dict], *, fail_posts: int = 0) -> None:
        self.comments = comments
        self.fail_posts = fail_posts
        self.posts: list[str] = []
        self.auth_checked = False

    def check_auth(self) -> None:
        self.auth_checked = True

    def list_comments(self):
        return list(self.comments)

    def post_comment(self, body: str) -> int:
        if self.fail_posts:
            self.fail_posts -= 1
            raise RuntimeError("temporary GitHub failure")
        self.posts.append(body)
        return 9000 + len(self.posts)


def comment(comment_id: int, body: str, author: str = "moderqtor") -> dict:
    return {"id": comment_id, "body": body, "user": {"login": author}}


def make_relay(
    tmp_path: Path,
    github: FakeGitHub,
    *,
    execute_agent: bool = True,
    initialize: bool = True,
    replay_existing: bool = True,
):
    store = AgentBrokerStore(tmp_path / "ledger.db")
    broker = FakeBroker(store, tmp_path)
    relay = GitHubAgentRelay(
        repository="moderqtor/OpenCobalt",
        issue_number=42,
        allowed_author="moderqtor",
        local_repository=str(tmp_path / "repo"),
        broker=broker,
        store=store,
        github=github,
        execute_agent=execute_agent,
        allow_comment_writes=True,
    )
    if initialize:
        relay.initialize_channel(replay_existing=replay_existing)
    return relay, broker, store


def test_command_protocol_round_trip() -> None:
    body = command_comment(
        action="continue",
        session_id="agent-123",
        prompt="run the focused tests",
        command_id="cmd-123",
    )

    assert body.startswith(COMMAND_MARKER)
    parsed = parse_command_comment(body)
    assert parsed is not None
    assert parsed.command_id == "cmd-123"
    assert parsed.action == "continue"
    assert parsed.session_id == "agent-123"
    assert parsed.prompt == "run the focused tests"
    assert parse_command_comment("ordinary PR discussion") is None


def test_relay_executes_allowlisted_start_once_and_posts_result(tmp_path: Path) -> None:
    body = command_comment(
        action="start",
        prompt="inspect the broker and improve one bounded defect",
        command_id="cmd-start",
    )
    github = FakeGitHub([comment(101, body)])
    relay, broker, store = make_relay(tmp_path, github)

    first = relay.run_once()
    second = relay.run_once()

    assert first == {"processed": 1, "ignored": 0, "posted": 1}
    assert second == {"processed": 0, "ignored": 0, "posted": 0}
    assert len(broker.starts) == 1
    assert broker.starts[0]["execute"] is True
    assert len(github.posts) == 1
    assert github.posts[0].startswith(RESULT_MARKER)
    assert "receipt-relay" in github.posts[0]
    event = store.get_relay_event("moderqtor/OpenCobalt", 42, 101)
    assert event is not None
    assert event.status == "complete"
    assert event.session_id == "agent-relay-test"
    assert event.result_comment_id == 9001


def test_fresh_channel_starts_after_existing_comments_by_default(tmp_path: Path) -> None:
    old = command_comment(action="start", prompt="historical", command_id="cmd-old")
    github = FakeGitHub([comment(201, old)])
    relay, broker, store = make_relay(tmp_path, github, initialize=False)

    channel = relay.initialize_channel()
    first = relay.run_once()
    github.comments.append(
        comment(
            202,
            command_comment(action="start", prompt="new", command_id="cmd-new"),
        )
    )
    second = relay.run_once()

    assert channel.last_seen_comment_id == 201
    assert first == {"processed": 0, "ignored": 0, "posted": 0}
    assert second == {"processed": 1, "ignored": 0, "posted": 1}
    assert [item["objective"] for item in broker.starts] == ["new"]
    stored = store.get_relay_channel("moderqtor/OpenCobalt", 42)
    assert stored is not None and stored.last_seen_comment_id == 202


def test_restart_processes_commands_posted_while_relay_was_down(tmp_path: Path) -> None:
    github = FakeGitHub([comment(301, "ordinary setup discussion")])
    relay, broker, store = make_relay(tmp_path, github, initialize=False)
    relay.initialize_channel()
    github.comments.append(
        comment(
            302,
            command_comment(action="start", prompt="while down", command_id="cmd-down"),
        )
    )

    restarted = GitHubAgentRelay(
        repository="moderqtor/OpenCobalt",
        issue_number=42,
        allowed_author="moderqtor",
        local_repository=str(tmp_path / "repo"),
        broker=broker,
        store=store,
        github=github,
        execute_agent=True,
        allow_comment_writes=True,
    )
    existing = restarted.initialize_channel()
    result = restarted.run_once()

    assert existing.last_seen_comment_id == 301
    assert result == {"processed": 1, "ignored": 0, "posted": 1}
    assert broker.starts[0]["objective"] == "while down"


def test_existing_channel_rejects_author_rebinding(tmp_path: Path) -> None:
    github = FakeGitHub([])
    relay, broker, store = make_relay(tmp_path, github, initialize=False)
    relay.initialize_channel()
    changed = GitHubAgentRelay(
        repository="moderqtor/OpenCobalt",
        issue_number=42,
        allowed_author="someone-else",
        local_repository=str(tmp_path / "repo"),
        broker=broker,
        store=store,
        github=github,
        execute_agent=True,
        allow_comment_writes=True,
    )

    with pytest.raises(ValueError, match="different allowed GitHub author"):
        changed.initialize_channel()


def test_relay_ignores_command_from_other_author(tmp_path: Path) -> None:
    body = command_comment(action="start", prompt="do not run", command_id="cmd-other")
    github = FakeGitHub([comment(102, body, author="someone-else")])
    relay, broker, store = make_relay(tmp_path, github)

    result = relay.run_once()

    assert result == {"processed": 0, "ignored": 1, "posted": 0}
    assert broker.starts == []
    assert github.posts == []
    event = store.get_relay_event("moderqtor/OpenCobalt", 42, 102)
    assert event is not None and event.status == "ignored"


def test_unauthorized_malformed_command_is_inert(tmp_path: Path) -> None:
    malformed = f"{COMMAND_MARKER}\n```json\nnot-json\n```"
    github = FakeGitHub([comment(106, malformed, author="someone-else")])
    relay, broker, store = make_relay(tmp_path, github)

    result = relay.run_once()

    assert result == {"processed": 0, "ignored": 1, "posted": 0}
    assert broker.starts == []
    assert github.posts == []
    event = store.get_relay_event("moderqtor/OpenCobalt", 42, 106)
    assert event is not None and event.status == "ignored"


def test_pending_result_is_retried_without_reexecuting_agent(tmp_path: Path) -> None:
    body = command_comment(action="start", prompt="one turn", command_id="cmd-retry")
    github = FakeGitHub([comment(103, body)], fail_posts=1)
    relay, broker, store = make_relay(tmp_path, github)

    first = relay.run_once()
    event = store.get_relay_event("moderqtor/OpenCobalt", 42, 103)
    second = relay.run_once()

    assert first["processed"] == 1 and first["posted"] == 0
    assert event is not None and event.status == "result_pending"
    assert len(broker.starts) == 1
    assert second == {"processed": 0, "ignored": 0, "posted": 1}
    assert len(broker.starts) == 1
    assert len(github.posts) == 1


def test_duplicate_command_id_is_not_reexecuted(tmp_path: Path) -> None:
    first = command_comment(action="start", prompt="one", command_id="cmd-same")
    second = command_comment(action="start", prompt="two", command_id="cmd-same")
    github = FakeGitHub([comment(107, first), comment(108, second)])
    relay, broker, store = make_relay(tmp_path, github)

    result = relay.run_once()

    assert result == {"processed": 1, "ignored": 1, "posted": 1}
    assert len(broker.starts) == 1
    assert broker.starts[0]["objective"] == "one"
    duplicate = store.get_relay_event("moderqtor/OpenCobalt", 42, 108)
    assert duplicate is not None and duplicate.status == "ignored"
    assert duplicate.action == "duplicate"


def test_continue_and_status_use_existing_session(tmp_path: Path) -> None:
    github = FakeGitHub([])
    relay, broker, _store = make_relay(tmp_path, github)
    started, _execution = broker.start(
        repository=str(tmp_path / "repo"),
        objective="first",
        execute=True,
    )
    github.comments.extend(
        [
            comment(
                104,
                command_comment(
                    action="continue",
                    session_id=started.session_id,
                    prompt="second",
                    command_id="cmd-continue",
                ),
            ),
            comment(
                105,
                command_comment(
                    action="status",
                    session_id=started.session_id,
                    command_id="cmd-status",
                ),
            ),
        ]
    )

    result = relay.run_once()

    assert result == {"processed": 2, "ignored": 0, "posted": 2}
    assert broker.continues == [(started.session_id, "second", True)]
    assert any("receipt-continue" in body for body in github.posts)


def test_github_comment_client_validation() -> None:
    from opencobalt.agent_broker.relay import GitHubCommentClient

    # Invalid repo format
    with pytest.raises(ValueError, match="repository must be owner/name"):
        GitHubCommentClient("invalid_repo_name", 1, allow_comment_writes=False)

    # Invalid issue number
    with pytest.raises(ValueError, match="issue_number must be positive"):
        GitHubCommentClient("owner/repo", 0, allow_comment_writes=False)

    # Permission check on write when not allowed
    client_readonly = GitHubCommentClient("owner/repo", 1, allow_comment_writes=False)
    with pytest.raises(PermissionError, match="not explicitly enabled"):
        client_readonly.post_comment("hello")


def test_relay_authorized_invalid_command_posts_error_comment(tmp_path: Path) -> None:
    # Authorized author posts invalid command (missing required prompt)
    malformed_body = f"{COMMAND_MARKER}\n```json\n{{\"command_id\": \"cmd-bad\", \"action\": \"start\"}}\n```"
    github = FakeGitHub([comment(201, malformed_body)])
    relay, _broker, store = make_relay(tmp_path, github)

    result = relay.run_once()
    assert result == {"processed": 1, "ignored": 0, "posted": 1}
    assert len(github.posts) == 1
    assert "start requires a prompt" in github.posts[0]
    event = store.get_relay_event("moderqtor/OpenCobalt", 42, 201)
    assert event is not None
    assert event.action == "invalid"
    assert event.status == "failed"


def test_relay_dispatches_stop_and_status_list(tmp_path: Path) -> None:
    github = FakeGitHub([])
    relay, broker, _store = make_relay(tmp_path, github)
    started, _ = broker.start(repository=str(tmp_path / "repo"), objective="to stop", execute=True)

    github.comments.extend(
        [
            comment(301, command_comment(action="stop", session_id=started.session_id, command_id="cmd-stop")),
            comment(302, command_comment(action="status", command_id="cmd-list-all")),
        ]
    )
    result = relay.run_once()
    assert result == {"processed": 2, "ignored": 0, "posted": 2}
    assert started.session_id in github.posts[0]
    assert "stopped" in github.posts[0]
    assert "sessions" in github.posts[1]


def test_relay_public_response_redaction_and_truncation() -> None:
    from opencobalt.agent_broker.relay import _public_text

    # Redact credentials and home path
    home = str(Path.home())
    text_with_secret = f"Path is {home}/workspace, token is sk-ant-api03-123456789012345678901234567890123456"
    sanitized = _public_text(text_with_secret)
    assert home not in sanitized
    assert "<home>" in sanitized

    # Truncate >8000 chars
    long_text = "A" * 10_000
    truncated = _public_text(long_text)
    assert len(truncated) < 9_000
    assert "[truncated; full response is in the local broker ledger]" in truncated


def test_relay_command_validation_constraints() -> None:
    from opencobalt.agent_broker.relay import RelayCommand

    # Flag injection in command_id
    with pytest.raises(ValueError, match="bounded non-flag"):
        RelayCommand(command_id="--danger", action="start", prompt="test")

    # Whitespace in session_id
    with pytest.raises(ValueError, match="bounded non-flag"):
        RelayCommand(command_id="cmd-1", action="continue", session_id="ses 123", prompt="test")

    # Continue without session_id
    with pytest.raises(ValueError, match="continue requires a session_id"):
        RelayCommand(command_id="cmd-1", action="continue", prompt="test")

