"""Durable agent broker with receipt-backed coding agent turns."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.store import ExecutionStore
from opencobalt.personal_ai.staging import StagingController

from .antigravity_adapter import AntigravityBrokerAdapter
from .codex_adapter import CodexSdkBrokerAdapter
from .models import AgentBrokerSession, AgentBrokerTurn, canonical_broker_runtime
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


def _not_executed_error(outcome: Any) -> str:
    policy = getattr(outcome, "policy", None)
    if policy is not None and not bool(getattr(policy, "allowed", False)):
        reason = str(getattr(policy, "reason", "execution blocked by policy"))
        return f"execution blocked by OpenCobalt policy: {reason}"[:1000]
    receipt = getattr(outcome, "receipt", None)
    limitations = list(getattr(receipt, "limitations", []) or [])
    if limitations:
        return f"runtime did not execute: {limitations[-1]}"[:1000]
    return "runtime did not execute; inspect the linked WorkReceipt"


@runtime_checkable
class BrokerRunner(Protocol):
    """Protocol for provider-specific broker turn runners routing through ExecutionEngine."""

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
        ...

    def archive(
        self,
        *,
        provider_session_id: str,
        workspace_path: str,
        execute: bool,
        approved: bool,
        timeout_seconds: int,
    ) -> BrokerExecution:
        ...


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
            if execute:
                return BrokerExecution(
                    status="failed",
                    executed=False,
                    receipt_id=receipt_id,
                    provider_session_id=provider_session_id,
                    error=_not_executed_error(outcome),
                )
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
            if execute:
                return BrokerExecution(
                    status="failed",
                    executed=False,
                    receipt_id=receipt_id,
                    provider_session_id=provider_session_id,
                    error=_not_executed_error(outcome),
                )
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


class ExecutionEngineAntigravityRunner:
    """Run Google Antigravity CLI actions only through ExecutionEngine."""

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
            if isinstance(payload, dict) and ("conversation_id" in payload or "status" in payload or "response" in payload):
                return payload
        try:
            payload = json.loads(text.strip())
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
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
        adapter = AntigravityBrokerAdapter(
            provider_session_id=provider_session_id,
            model=model,
            sandbox=True,
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
            if execute:
                return BrokerExecution(
                    status="failed",
                    executed=False,
                    receipt_id=receipt_id,
                    provider_session_id=provider_session_id,
                    error=_not_executed_error(outcome),
                )
            return BrokerExecution(status="planned", executed=False, receipt_id=receipt_id)
        payload = self._worker_payload(outcome.result.stdout_path, outcome.result.stdout_preview)
        payload_status = payload.get("status")
        is_success = outcome.result.status == "succeeded" and (
            payload_status == "SUCCESS" or (not payload_status and bool(payload))
        )
        if not is_success:
            error = str(
                payload.get("error")
                or outcome.result.error
                or outcome.result.stderr_preview
                or outcome.result.stdout_preview
                or "Antigravity broker turn failed"
            )[:1000]
            return BrokerExecution(
                status="failed",
                executed=True,
                receipt_id=receipt_id,
                provider_session_id=provider_session_id,
                error=error,
                metadata={"worker": payload},
            )
        conv_id = str(payload.get("conversation_id") or provider_session_id or "") or None
        response_text = str(payload.get("response") or outcome.result.stdout_preview or "")
        return BrokerExecution(
            status="complete",
            executed=True,
            receipt_id=receipt_id,
            provider_session_id=conv_id,
            response=response_text,
            metadata={
                "usage": payload.get("usage"),
                "duration_seconds": payload.get("duration_seconds"),
                "num_turns": payload.get("num_turns"),
                "cwd": workspace_path,
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
        return BrokerExecution(
            status="unsupported",
            executed=False,
            receipt_id=None,
            provider_session_id=provider_session_id,
            metadata={
                "archive_supported": False,
                "reason": "Google Antigravity CLI does not support provider-side conversation archiving",
            },
        )


class BrokerRunnerRegistry:
    """Registry of BrokerRunner implementations by canonical runtime ID."""

    def __init__(self, engine: ExecutionEngine) -> None:
        self.engine = engine
        self._runners: dict[str, BrokerRunner] = {
            "codex-sdk": ExecutionEngineCodexRunner(engine),
            "google-antigravity": ExecutionEngineAntigravityRunner(engine),
        }

    def get_runner(self, runtime: str) -> BrokerRunner:
        canonical = canonical_broker_runtime(runtime)
        runner = self._runners.get(canonical)
        if runner is None:
            known = ", ".join(sorted(self._runners.keys()))
            raise KeyError(f"unsupported broker runtime '{runtime}' (supported: {known})")
        return runner


class AgentBroker:
    """OpenCobalt-owned lifecycle for resumable external coding agents."""

    def __init__(
        self,
        *,
        db_path: str | Path = Path(".opencobalt") / "ledger.db",
        store: AgentBrokerStore | None = None,
        runner: BrokerRunner | None = None,
        runner_registry: BrokerRunnerRegistry | None = None,
        workspace_factory: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.store = store or AgentBrokerStore(self.db_path)
        engine = ExecutionEngine(store=ExecutionStore(self.db_path))
        self.registry = runner_registry or BrokerRunnerRegistry(engine)
        self._custom_runner = runner
        if workspace_factory is None:
            controller = StagingController(
                staging_root=self.db_path.parent / "agent-broker-workspaces"
            )

            def create_workspace(repository: str, provider_id: str = "codex-sdk") -> dict[str, Any]:
                return controller.create_workspace(repository, provider_id=provider_id)

            workspace_factory = create_workspace
        self.workspace_factory = workspace_factory

    def _create_workspace(self, repository: str, provider_id: str) -> dict[str, Any]:
        try:
            return self.workspace_factory(repository, provider_id=provider_id)
        except TypeError:
            return self.workspace_factory(repository)

    def _resolve_runner(self, runtime: str) -> BrokerRunner:
        if self._custom_runner is not None:
            return self._custom_runner
        return self.registry.get_runner(runtime)

    def start(
        self,
        *,
        repository: str,
        objective: str,
        runtime: str = "codex-sdk",
        model: str | None = None,
        execute: bool = False,
        approved: bool = False,
        timeout_seconds: int = 1800,
    ) -> tuple[AgentBrokerSession, BrokerExecution]:
        canonical_runtime = canonical_broker_runtime(runtime)
        workspace = self._create_workspace(repository, provider_id=canonical_runtime)
        baseline = workspace.get("baseline") or {}
        session = AgentBrokerSession(
            runtime=canonical_runtime,
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
        runner = self._resolve_runner(canonical_runtime)
        execution = runner.run_turn(
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
        runner = self._resolve_runner(session.runtime)
        provider_prompt = prompt
        if execute and session.provider_session_id is None:
            provider_prompt = self._first_live_prompt(session, prompt)
        execution = runner.run_turn(
            prompt=provider_prompt,
            workspace_path=session.workspace_path,
            provider_session_id=session.provider_session_id,
            model=session.model,
            execute=execute,
            approved=approved,
            timeout_seconds=timeout_seconds,
        )
        if provider_prompt != prompt:
            execution.metadata = {
                **execution.metadata,
                "first_live_turn_replayed_planned_context": True,
            }
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
            runner = self._resolve_runner(session.runtime)
            archive_result = runner.archive(
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

    def _first_live_prompt(self, session: AgentBrokerSession, prompt: str) -> str:
        """Give the first real provider session the durable plan-only context."""
        context: list[str] = []
        for candidate in [
            session.objective,
            *[turn.prompt for turn in self.store.list_turns(session.session_id)],
        ]:
            text = str(candidate or "").strip()
            if text and text not in context:
                context.append(text)
        current = prompt.strip()
        if current and current not in context:
            context.append(current)
        if len(context) <= 1:
            return current or session.objective
        prior = "\n\n".join(
            f"Planned instruction {index}:\n{text}"
            for index, text in enumerate(context[:-1], start=1)
        )
        return (
            "This is the first live provider turn for an existing OpenCobalt broker session. "
            "No provider session existed during the earlier dry-run planning records. Preserve "
            "their intent as context, then follow the current instruction.\n\n"
            f"{prior}\n\nCurrent instruction:\n{context[-1]}"
        )

    def _record_turn(
        self,
        session: AgentBrokerSession,
        prompt: str,
        execution: BrokerExecution,
    ) -> tuple[AgentBrokerSession, BrokerExecution]:
        sequence = session.turn_count + 1
        turn_status = (
            "complete"
            if execution.status == "complete"
            else "failed"
            if execution.status == "failed"
            else "planned"
        )
        turn = AgentBrokerTurn(
            session_id=session.session_id,
            sequence=sequence,
            prompt=prompt,
            response=execution.response,
            provider_session_id=execution.provider_session_id,
            receipt_id=execution.receipt_id,
            status=turn_status,
            metadata={
                **execution.metadata,
                **({"error": execution.error} if execution.error else {}),
            },
        )
        self.store.save_turn(turn)
        next_status = (
            "active"
            if execution.status == "complete"
            else "failed"
            if execution.status == "failed"
            else "planned"
        )
        session = session.model_copy(
            update={
                "provider_session_id": execution.provider_session_id
                or session.provider_session_id,
                "status": next_status,
                "turn_count": sequence,
                "last_prompt": prompt,
                "last_response": execution.response or execution.error,
                "last_receipt_id": execution.receipt_id,
                "updated_at": _now(),
            }
        )
        self.store.save_session(session)
        return session, execution
