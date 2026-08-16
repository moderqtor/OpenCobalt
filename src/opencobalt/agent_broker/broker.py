"""Durable agent broker with receipt-backed Codex turns."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.store import ExecutionStore
from opencobalt.personal_ai.staging import StagingController

from .codex_adapter import CodexSdkBrokerAdapter
from .models import AgentBrokerSession, AgentBrokerTurn
from .store import AgentBrokerStore


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class BrokerExecution:
    """Normalized result of one ExecutionEngine-backed broker action."""

    status: str
    executed: bool
    receipt_id: str | None = None
    provider_session_id: str | None = None
    response: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ExecutionEngineCodexRunner:
    """Run Codex SDK worker actions only through ExecutionEngine."""

    def __init__(self, engine: ExecutionEngine) -> None:
        self.engine = engine

    @staticmethod
    def _worker_payload(stdout_path: str | None, preview: str) -> dict[str, Any]:
        text = preview
        if stdout_path:
            try:
                text = Path(stdout_path).read_text(encoding="utf-8")
            except OSError:
                pass
        for line in reversed([item.strip() for item in text.splitlines() if item.strip()]):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and "ok" in payload:
                return payload
        return {}

    def run_turn(
        self,
        *,
        prompt: str,
        workspace_path: str,
        provider_session_id: str | None,
        model: str | None,
        execute: bool,
        approved: bool,
        timeout_seconds: int,
    ) -> BrokerExecution:
        adapter = CodexSdkBrokerAdapter(
            action="turn",
            provider_session_id=provider_session_id,
            model=model,
        )
        outcome = self.engine.run_task(
            prompt,
            runtime=adapter.runtime_id,
            execute=execute,
            approved=approved,
            timeout_seconds=timeout_seconds,
            cwd=workspace_path,
            adapter=adapter,
        )
        receipt_id = outcome.receipt.receipt_id
        if outcome.result is None:
            return BrokerExecution(status="planned", executed=False, receipt_id=receipt_id)
        payload = self._worker_payload(outcome.result.stdout_path, outcome.result.stdout_preview)
        if outcome.result.status != "succeeded" or payload.get("ok") is not True:
            error = str(
                payload.get("error")
                or outcome.result.error
                or outcome.result.stderr_preview
                or "Codex broker turn failed"
            )[:1000]
            return BrokerExecution(
                status="failed",
                executed=True,
                receipt_id=receipt_id,
                provider_session_id=provider_session_id,
                error=error,
                metadata={"worker": payload},
            )
        return BrokerExecution(
            status="complete",
            executed=True,
            receipt_id=receipt_id,
            provider_session_id=str(payload.get("thread_id") or provider_session_id or "") or None,
            response=str(payload.get("final_response") or ""),
            metadata={
                "usage": payload.get("usage"),
                "item_count": payload.get("item_count"),
                "cwd": payload.get("cwd"),
            },
        )

    def archive(
        self,
        *,
        provider_session_id: str,
        workspace_path: str,
        execute: bool,
        approved: bool,
        timeout_seconds: int,
    ) -> BrokerExecution:
        adapter = CodexSdkBrokerAdapter(
            action="archive",
            provider_session_id=provider_session_id,
        )
        outcome = self.engine.run_task(
            f"Archive Codex broker thread {provider_session_id}",
            runtime=adapter.runtime_id,
            execute=execute,
            approved=approved,
            timeout_seconds=timeout_seconds,
            cwd=workspace_path,
            adapter=adapter,
        )
        receipt_id = outcome.receipt.receipt_id
        if outcome.result is None:
            return BrokerExecution(status="planned", executed=False, receipt_id=receipt_id)
        payload = self._worker_payload(outcome.result.stdout_path, outcome.result.stdout_preview)
        if outcome.result.status != "succeeded" or payload.get("ok") is not True:
            return BrokerExecution(
                status="failed",
                executed=True,
                receipt_id=receipt_id,
                provider_session_id=provider_session_id,
                error=str(payload.get("error") or outcome.result.error or "Codex archive failed")[:1000],
                metadata={"worker": payload},
            )
        return BrokerExecution(
            status="complete",
            executed=True,
            receipt_id=receipt_id,
            provider_session_id=provider_session_id,
            metadata={"archive": payload.get("archive")},
        )


class AgentBroker:
    """OpenCobalt-owned lifecycle for resumable external coding agents."""

    def __init__(
        self,
        *,
        db_path: str | Path = Path(".opencobalt") / "ledger.db",
        store: AgentBrokerStore | None = None,
        runner: Any | None = None,
        workspace_factory: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.store = store or AgentBrokerStore(self.db_path)
        if runner is None:
            engine = ExecutionEngine(store=ExecutionStore(self.db_path))
            runner = ExecutionEngineCodexRunner(engine)
        self.runner = runner
        if workspace_factory is None:
            controller = StagingController(
                staging_root=self.db_path.parent / "agent-broker-workspaces"
            )

            def create_workspace(repository: str) -> dict[str, Any]:
                return controller.create_workspace(repository, provider_id="codex-sdk")

            workspace_factory = create_workspace
        self.workspace_factory = workspace_factory

    def start(
        self,
        *,
        repository: str,
        objective: str,
        model: str | None = None,
        execute: bool = False,
        approved: bool = False,
        timeout_seconds: int = 1800,
    ) -> tuple[AgentBrokerSession, BrokerExecution]:
        workspace = self.workspace_factory(repository)
        baseline = workspace.get("baseline") or {}
        session = AgentBrokerSession(
            objective=objective,
            repository_path=str(workspace["authoritative_path"]),
            workspace_id=str(workspace["workspace_id"]),
            workspace_path=str(workspace["staging_path"]),
            source_branch=workspace.get("branch") or baseline.get("branch"),
            starting_head=workspace.get("head") or baseline.get("head"),
            model=model,
            metadata={
                "workspace_kind": workspace.get("kind"),
                "authority": "staged_workspace_only",
            },
        )
        self.store.save_session(session)
        execution = self.runner.run_turn(
            prompt=objective,
            workspace_path=session.workspace_path,
            provider_session_id=None,
            model=model,
            execute=execute,
            approved=approved,
            timeout_seconds=timeout_seconds,
        )
        return self._record_turn(session, objective, execution)

    def continue_session(
        self,
        session_id: str,
        prompt: str,
        *,
        execute: bool = False,
        approved: bool = False,
        timeout_seconds: int = 1800,
    ) -> tuple[AgentBrokerSession, BrokerExecution]:
        session = self.require_session(session_id)
        if session.status == "stopped":
            raise ValueError(f"broker session is stopped: {session_id}")
        execution = self.runner.run_turn(
            prompt=prompt,
            workspace_path=session.workspace_path,
            provider_session_id=session.provider_session_id,
            model=session.model,
            execute=execute,
            approved=approved,
            timeout_seconds=timeout_seconds,
        )
        return self._record_turn(session, prompt, execution)

    def stop(
        self,
        session_id: str,
        *,
        archive_provider: bool = False,
        execute: bool = False,
        approved: bool = False,
        timeout_seconds: int = 120,
    ) -> tuple[AgentBrokerSession, BrokerExecution | None]:
        session = self.require_session(session_id)
        archive_result = None
        if archive_provider and session.provider_session_id:
            archive_result = self.runner.archive(
                provider_session_id=session.provider_session_id,
                workspace_path=session.workspace_path,
                execute=execute,
                approved=approved,
                timeout_seconds=timeout_seconds,
            )
            if archive_result.status == "failed":
                return session, archive_result
        session = session.model_copy(update={"status": "stopped", "updated_at": _now()})
        self.store.save_session(session)
        return session, archive_result

    def require_session(self, session_id: str) -> AgentBrokerSession:
        session = self.store.get_session(session_id)
        if session is None:
            raise KeyError(f"unknown broker session: {session_id}")
        return session

    def list_sessions(self, *, limit: int = 50) -> list[AgentBrokerSession]:
        return self.store.list_sessions(limit=limit)

    def turns(self, session_id: str) -> list[AgentBrokerTurn]:
        self.require_session(session_id)
        return self.store.list_turns(session_id)

    def _record_turn(
        self,
        session: AgentBrokerSession,
        prompt: str,
        execution: BrokerExecution,
    ) -> tuple[AgentBrokerSession, BrokerExecution]:
        sequence = session.turn_count + 1
        turn_status = (
            "complete" if execution.status == "complete" else
            "failed" if execution.status == "failed" else
            "planned"
        )
        turn = AgentBrokerTurn(
            session_id=session.session_id,
            sequence=sequence,
            prompt=prompt,
            response=execution.response,
            provider_session_id=execution.provider_session_id,
            receipt_id=execution.receipt_id,
            status=turn_status,
            metadata={**execution.metadata, **({"error": execution.error} if execution.error else {})},
        )
        self.store.save_turn(turn)
        next_status = (
            "active" if execution.status == "complete" else
            "failed" if execution.status == "failed" else
            "planned"
        )
        session = session.model_copy(update={
            "provider_session_id": execution.provider_session_id or session.provider_session_id,
            "status": next_status,
            "turn_count": sequence,
            "last_prompt": prompt,
            "last_response": execution.response or execution.error,
            "last_receipt_id": execution.receipt_id,
            "updated_at": _now(),
        })
        self.store.save_session(session)
        return session, execution
