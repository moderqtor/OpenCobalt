from __future__ import annotations

from pathlib import Path

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


def make_relay(tmp_path: Path, github: FakeGitHub, *, execute_agent: bool = True):
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
