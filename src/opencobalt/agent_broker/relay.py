"""GitHub issue/PR comment relay for durable local broker sessions.

The relay is deliberately opt-in and foreground. GitHub is a coordination bus,
not an authority source: only structured commands from one configured author on
one configured issue/PR are accepted. Agent execution remains local and
receipt-backed through :class:`AgentBroker`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from opencobalt.execution.runner import redact_text

from .broker import AgentBroker, BrokerExecution
from .models import AgentBrokerSession, AgentRelayEvent
from .store import AgentBrokerStore

COMMAND_MARKER = "<!-- opencobalt-agent-command:v1 -->"
RESULT_MARKER = "<!-- opencobalt-agent-result:v1 -->"
_MAX_PUBLIC_RESPONSE = 8_000
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class RelayCommand(BaseModel):
    """Bounded command accepted from the configured GitHub relay channel."""

    command_id: str = Field(min_length=1, max_length=200)
    action: Literal["start", "continue", "status", "stop"]
    session_id: str | None = Field(default=None, max_length=200)
    prompt: str | None = Field(default=None, max_length=100_000)

    @field_validator("command_id", "session_id")
    @classmethod
    def _bounded_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith("-") or any(character.isspace() for character in value):
            raise ValueError("relay identifiers must be bounded non-flag values")
        return value

    @model_validator(mode="after")
    def _action_requirements(self) -> RelayCommand:
        if self.action in {"start", "continue"} and not (self.prompt or "").strip():
            raise ValueError(f"{self.action} requires a prompt")
        if self.action in {"continue", "stop"} and not self.session_id:
            raise ValueError(f"{self.action} requires a session_id")
        return self


def command_comment(
    *,
    action: Literal["start", "continue", "status", "stop"],
    prompt: str | None = None,
    session_id: str | None = None,
    command_id: str | None = None,
) -> str:
    """Render the stable command envelope a remote controller should post."""
    payload = RelayCommand(
        command_id=command_id or f"cmd-{uuid.uuid4()}",
        action=action,
        prompt=prompt,
        session_id=session_id,
    ).model_dump(mode="json", exclude_none=True)
    return f"{COMMAND_MARKER}\n```json\n{json.dumps(payload, sort_keys=True)}\n```"


def parse_command_comment(body: str) -> RelayCommand | None:
    """Parse only explicit v1 command comments; ordinary prose is inert."""
    if COMMAND_MARKER not in body:
        return None
    segment = body.split(COMMAND_MARKER, 1)[1]
    match = _JSON_BLOCK_RE.search(segment)
    if match is None:
        raise ValueError("relay command marker requires one JSON code block")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError("relay command JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("relay command must be a JSON object")
    return RelayCommand.model_validate(payload)


class GitHubCommentClient:
    """Narrow GitHub comment client using externally managed `gh` auth."""

    def __init__(
        self,
        repository: str,
        issue_number: int,
        *,
        allow_comment_writes: bool,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        if not _REPOSITORY_RE.fullmatch(repository):
            raise ValueError("repository must be owner/name")
        if int(issue_number) <= 0:
            raise ValueError("issue_number must be positive")
        self.repository = repository
        self.issue_number = int(issue_number)
        self.allow_comment_writes = bool(allow_comment_writes)
        self._run = run
        self._gh = shutil.which("gh")
        if self._gh is None:
            raise RuntimeError("GitHub CLI `gh` is required for the broker relay")

    @property
    def endpoint(self) -> str:
        return f"repos/{self.repository}/issues/{self.issue_number}/comments"

    def check_auth(self) -> None:
        result = self._run(
            [self._gh, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "GitHub CLI authentication unavailable").strip()
            raise RuntimeError(detail[:500])

    def list_comments(self) -> list[dict[str, Any]]:
        result = self._run(
            [
                self._gh,
                "api",
                "--paginate",
                "--slurp",
                f"{self.endpoint}?per_page=100",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "GitHub comment read failed").strip()
            raise RuntimeError(detail[:500])
        try:
            data = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError("GitHub CLI returned invalid comment JSON") from exc
        if not isinstance(data, list):
            raise RuntimeError("GitHub CLI returned an unexpected comment response")
        if data and all(isinstance(item, list) for item in data):
            comments = [comment for page in data for comment in page if isinstance(comment, dict)]
        else:
            comments = [comment for comment in data if isinstance(comment, dict)]
        return sorted(comments, key=lambda item: int(item.get("id") or 0))

    def post_comment(self, body: str) -> int:
        if not self.allow_comment_writes:
            raise PermissionError("GitHub comment writes were not explicitly enabled")
        result = self._run(
            [self._gh, "api", "--method", "POST", self.endpoint, "--input", "-"],
            input=json.dumps({"body": body}),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "GitHub comment write failed").strip()
            raise RuntimeError(detail[:500])
        try:
            payload = json.loads(result.stdout or "{}")
            comment_id = int(payload["id"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("GitHub comment write did not return a comment id") from exc
        return comment_id


def _public_text(value: str) -> str:
    text = redact_text(value or "").replace(str(Path.home()), "<home>").strip()
    if len(text) <= _MAX_PUBLIC_RESPONSE:
        return text
    return f"{text[:_MAX_PUBLIC_RESPONSE]}\n\n[truncated; full response is in the local broker ledger]"


def _session_view(session: AgentBrokerSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "provider_session_id": session.provider_session_id,
        "status": session.status,
        "turn_count": session.turn_count,
        "source_branch": session.source_branch,
        "starting_head": session.starting_head,
        "last_receipt_id": session.last_receipt_id,
    }


def _execution_view(execution: BrokerExecution | None) -> dict[str, Any]:
    if execution is None:
        return {}
    return {
        "status": execution.status,
        "executed": execution.executed,
        "receipt_id": execution.receipt_id,
        "provider_session_id": execution.provider_session_id,
        "response": execution.response,
        "error": execution.error,
    }


def render_result_comment(command: RelayCommand, result: dict[str, Any]) -> str:
    """Render a bounded public result while full state remains local."""
    public = dict(result)
    if "response" in public:
        public["response"] = _public_text(str(public.get("response") or ""))
    if "error" in public:
        public["error"] = _public_text(str(public.get("error") or ""))
    payload = {
        "protocol": "opencobalt-agent-relay/v1",
        "command_id": command.command_id,
        **public,
    }
    return f"{RESULT_MARKER}\n```json\n{json.dumps(payload, indent=2, sort_keys=True, default=str)}\n```"


class GitHubAgentRelay:
    """Poll one GitHub issue/PR and dispatch allowlisted structured commands."""

    def __init__(
        self,
        *,
        repository: str,
        issue_number: int,
        allowed_author: str,
        local_repository: str,
        broker: AgentBroker | None = None,
        store: AgentBrokerStore | None = None,
        github: GitHubCommentClient | Any | None = None,
        execute_agent: bool = False,
        allow_comment_writes: bool = False,
        model: str | None = None,
    ) -> None:
        if not allowed_author or any(character.isspace() for character in allowed_author):
            raise ValueError("allowed_author must be one GitHub login")
        self.repository = repository
        self.issue_number = int(issue_number)
        self.allowed_author = allowed_author.casefold()
        self.local_repository = str(Path(local_repository).expanduser().resolve())
        self.broker = broker or AgentBroker()
        self.store = store or self.broker.store
        self.github = github or GitHubCommentClient(
            repository,
            issue_number,
            allow_comment_writes=allow_comment_writes,
        )
        self.execute_agent = bool(execute_agent)
        self.model = model

    def run_once(self) -> dict[str, int]:
        """Flush pending results, then process each unseen command exactly once."""
        posted = self._flush_pending_results()
        processed = 0
        ignored = 0
        for comment in self.github.list_comments():
            comment_id = int(comment.get("id") or 0)
            if comment_id <= 0:
                continue
            if self.store.get_relay_event(self.repository, self.issue_number, comment_id):
                continue
            body = str(comment.get("body") or "")
            if COMMAND_MARKER not in body:
                continue
            author = str((comment.get("user") or {}).get("login") or "")
            if author.casefold() != self.allowed_author:
                event = AgentRelayEvent(
                    repository=self.repository,
                    issue_number=self.issue_number,
                    source_comment_id=comment_id,
                    command_id=f"ignored-{comment_id}",
                    author=author or "unknown",
                    action="ignored",
                    status="ignored",
                )
                self.store.save_relay_event(event)
                ignored += 1
                continue
            try:
                command = parse_command_comment(body)
                if command is None:
                    continue
            except Exception as exc:
                command = RelayCommand(command_id=f"invalid-{comment_id}", action="status")
                event = AgentRelayEvent(
                    repository=self.repository,
                    issue_number=self.issue_number,
                    source_comment_id=comment_id,
                    command_id=command.command_id,
                    author=author,
                    action="invalid",
                    status="result_pending",
                    result_json={"ok": False, "error": str(exc)},
                    result_body=render_result_comment(
                        command, {"ok": False, "status": "invalid", "error": str(exc)}
                    ),
                )
                self.store.save_relay_event(event)
                posted += self._post_event_result(event)
                processed += 1
                continue

            duplicate = self.store.get_relay_event_by_command(
                self.repository, self.issue_number, command.command_id
            )
            if duplicate is not None:
                event = AgentRelayEvent(
                    repository=self.repository,
                    issue_number=self.issue_number,
                    source_comment_id=comment_id,
                    command_id=f"duplicate-{comment_id}",
                    author=author,
                    action="duplicate",
                    session_id=duplicate.session_id,
                    status="ignored",
                    command_json={
                        "duplicate_command_id": command.command_id,
                        "original_source_comment_id": duplicate.source_comment_id,
                    },
                )
                self.store.save_relay_event(event)
                ignored += 1
                continue

            event = AgentRelayEvent(
                repository=self.repository,
                issue_number=self.issue_number,
                source_comment_id=comment_id,
                command_id=command.command_id,
                author=author,
                action=command.action,
                session_id=command.session_id,
                command_json=command.model_dump(mode="json", exclude_none=True),
                status="processing",
            )
            self.store.save_relay_event(event)

            result = self._dispatch(command)
            session_id = str(result.get("session_id") or command.session_id or "") or None
            receipt_id = str(result.get("receipt_id") or "") or None
            event = event.model_copy(
                update={
                    "session_id": session_id,
                    "receipt_id": receipt_id,
                    "status": "result_pending",
                    "result_json": result,
                    "result_body": render_result_comment(command, result),
                    "updated_at": _now(),
                }
            )
            self.store.save_relay_event(event)
            posted += self._post_event_result(event)
            processed += 1
        return {"processed": processed, "ignored": ignored, "posted": posted}

    def run_forever(self, *, interval_seconds: float = 5.0) -> None:
        """Foreground poll loop. Ctrl+C remains the deliberate stop control."""
        interval = max(1.0, min(float(interval_seconds), 300.0))
        self.github.check_auth()
        while True:
            self.run_once()
            time.sleep(interval)

    def _dispatch(self, command: RelayCommand) -> dict[str, Any]:
        try:
            if command.action == "start":
                session, execution = self.broker.start(
                    repository=self.local_repository,
                    objective=(command.prompt or "").strip(),
                    model=self.model,
                    execute=self.execute_agent,
                )
                return self._result(session, execution)
            if command.action == "continue":
                session, execution = self.broker.continue_session(
                    command.session_id or "",
                    (command.prompt or "").strip(),
                    execute=self.execute_agent,
                )
                return self._result(session, execution)
            if command.action == "stop":
                session, execution = self.broker.stop(command.session_id or "")
                return self._result(session, execution)
            if command.session_id:
                session = self.broker.require_session(command.session_id)
                return {"ok": True, **_session_view(session)}
            sessions = self.broker.list_sessions(limit=10)
            return {
                "ok": True,
                "status": "status",
                "sessions": [_session_view(session) for session in sessions],
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "failed",
                "session_id": command.session_id,
                "error": str(exc)[:2000],
            }

    @staticmethod
    def _result(
        session: AgentBrokerSession,
        execution: BrokerExecution | None,
    ) -> dict[str, Any]:
        execution_view = _execution_view(execution)
        return {
            "ok": execution is None or execution.status != "failed",
            **_session_view(session),
            "receipt_id": execution_view.get("receipt_id") or session.last_receipt_id,
            "execution_status": execution_view.get("status"),
            "executed": execution_view.get("executed"),
            "response": execution_view.get("response") or "",
            "error": execution_view.get("error"),
        }

    def _flush_pending_results(self) -> int:
        posted = 0
        for event in self.store.list_pending_relay_results(
            self.repository, self.issue_number
        ):
            posted += self._post_event_result(event)
        return posted

    def _post_event_result(self, event: AgentRelayEvent) -> int:
        try:
            result_comment_id = self.github.post_comment(event.result_body)
        except Exception:
            return 0
        succeeded = bool(event.result_json.get("ok"))
        updated = event.model_copy(
            update={
                "result_comment_id": result_comment_id,
                "status": "complete" if succeeded else "failed",
                "updated_at": _now(),
            }
        )
        self.store.save_relay_event(updated)
        return 1
