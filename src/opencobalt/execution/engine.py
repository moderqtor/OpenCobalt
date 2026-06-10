"""Execution engine: the Receipt-Backed Execution v0 vertical slice.

route task -> create plan -> build safe command -> enforce policy ->
run or dry-run -> capture output -> attach artifacts -> hash artifacts ->
write receipt -> verify receipt.

Every stage emits a structured event so a future TUI/UI can render live
task status (planning / running / verifying / done / failed).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from opencobalt.core.events import append_event, make_event

from .adapters import CommandOptions, RuntimeAdapter, get_adapter
from .artifacts import attach_artifact, verify_artifact
from .models import (
    ExecutionPlan,
    ExecutionResult,
    ExecutionStep,
    WorkReceipt,
)
from .policy import PolicyDecision, check_execution, classify_risk, max_risk
from .runner import ProcessRunner, redact_argv, redact_text
from .store import ExecutionStore

_DEFAULT_EVENTS_PATH = Path(".opencobalt") / "events" / "execution.jsonl"

EVENT_TASK_RECEIVED = "task.received"
EVENT_ROUTE_SELECTED = "route.selected"
EVENT_PLAN_CREATED = "plan.created"
EVENT_POLICY_CHECKED = "policy.checked"
EVENT_EXECUTION_STARTED = "execution.started"
EVENT_EXECUTION_OUTPUT = "execution.output_captured"
EVENT_EXECUTION_SUCCEEDED = "execution.succeeded"
EVENT_EXECUTION_FAILED = "execution.failed"
EVENT_ARTIFACT_CREATED = "artifact.created"
EVENT_RECEIPT_CREATED = "receipt.created"
EVENT_VERIFICATION_PASSED = "verification.passed"
EVENT_VERIFICATION_FAILED = "verification.failed"


class ExecutionOutcome(BaseModel):
    """Everything one run produced. The receipt is the durable summary."""

    plan: ExecutionPlan
    policy: PolicyDecision
    result: ExecutionResult | None = None
    receipt: WorkReceipt
    route_reason: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def executed(self) -> bool:
        return self.result is not None and self.result.status != "not_executed"


class ExecutionEngine:
    def __init__(
        self,
        *,
        store: ExecutionStore | None = None,
        runner: ProcessRunner | None = None,
        events_path: Path | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.store = store or ExecutionStore()
        self.runner = runner or ProcessRunner()
        self.events_path = events_path or _DEFAULT_EVENTS_PATH
        self.event_sink = event_sink
        self._events: list[dict[str, Any]] = []

    # --- Events ---

    def _emit(self, event_type: str, subject_id: str, message: str, **metadata: Any) -> None:
        event = make_event(
            event_type=event_type,
            subject_type="execution",
            subject_id=subject_id,
            message=message,
            source="execution-engine",
            metadata=metadata,
        )
        self._events.append(event)
        try:
            append_event(event, path=self.events_path)
        except OSError:
            pass  # event log is best-effort; the SQLite receipt is the record
        if self.event_sink is not None:
            self.event_sink(event)

    # --- Vertical slice ---

    def run_task(
        self,
        task: str,
        *,
        runtime: str | None = None,
        model: str | None = None,
        sandbox: bool = False,
        execute: bool = False,
        approved: bool = False,
        timeout_seconds: int | None = None,
        cwd: str | None = None,
        unsafe_skip_permissions: bool = False,
        adapter: RuntimeAdapter | None = None,
    ) -> ExecutionOutcome:
        """Run the full receipt-backed slice for one task.

        Defaults to dry-run: nothing executes unless execute=True and the
        policy gate allows it. Every path writes a receipt.
        """
        self._events = []
        dry_run = not execute
        redacted_task = redact_text(task)
        self._emit(
            EVENT_TASK_RECEIVED,
            redacted_task[:80],
            f"task received: {redacted_task[:120]}",
        )

        # 1. Route (or honor explicit runtime).
        risk_from_route = "green"
        if runtime is None:
            from opencobalt.core.router import route_task

            decision = route_task(task, record=False)
            selected: str = str(decision.metadata.get("runtime", decision.recommended_tool))
            route_reason = decision.reasoning
            risk_from_route = str(decision.metadata.get("risk_level", "green"))
            self._emit(
                EVENT_ROUTE_SELECTED, selected, f"router selected {selected}",
                reasoning=decision.reasoning, score=decision.score,
            )
        else:
            selected = runtime
            route_reason = f"runtime explicitly requested: {selected}"
            self._emit(EVENT_ROUTE_SELECTED, selected, route_reason)
        runtime = selected

        if adapter is None:
            adapter = get_adapter(runtime)

        # 2. Classify risk: worst of policy keywords, router, and adapter view.
        risk = max_risk(classify_risk(task), risk_from_route, adapter.risk_for_task(task))
        needs_approval = risk in ("red", "black")

        # 3. Build the safe command. Capability mismatches fail before any plan runs.
        options = CommandOptions(
            model=model,
            sandbox=sandbox,
            dangerously_skip_permissions=unsafe_skip_permissions,
            allow_dangerously_skip_permissions=unsafe_skip_permissions,
        )
        if unsafe_skip_permissions:
            self._emit(
                EVENT_POLICY_CHECKED, runtime,
                "WARNING: unsafe permission-skip override requested",
                unsafe_override=True,
            )
        command_argv = adapter.build_command(task, options)
        timeout = timeout_seconds or adapter.default_timeout_seconds()

        # 4. Create and persist the plan.
        step = ExecutionStep(
            runtime=runtime,
            command_argv=command_argv,
            description=f"run {runtime} non-interactively",
            risk_level=risk,
            approval_required=needs_approval,
            timeout_seconds=timeout,
        )
        plan = ExecutionPlan(
            task=task,
            runtime=runtime,
            model_policy=model,
            cwd=cwd,
            risk_level=risk,
            approval_required=needs_approval,
            steps=[step],
            dry_run=dry_run,
        )
        self.store.save_plan(plan)
        self._emit(
            EVENT_PLAN_CREATED, plan.plan_id,
            f"plan created for {runtime} (risk {risk})",
            command_argv=redact_argv(command_argv), dry_run=dry_run,
        )

        # 5. Policy gate.
        policy = check_execution(risk, dry_run=dry_run, execute=execute, approved=approved)
        self._emit(
            EVENT_POLICY_CHECKED, plan.plan_id,
            f"policy: {'allowed' if policy.allowed else 'blocked'} ({policy.reason})",
            allowed=policy.allowed, risk_level=policy.risk_level,
        )

        capabilities = adapter.capabilities()
        receipt = WorkReceipt(
            plan_id=plan.plan_id,
            task=task,
            selected_runtime=runtime,
            route_reason=route_reason,
            risk_level=risk,
            approval_required=needs_approval,
            capabilities_snapshot=capabilities,
            command_plan=command_argv,
        )

        result: ExecutionResult | None = None
        if policy.allowed and not dry_run:
            result = self._execute(plan, step, receipt)
        elif dry_run:
            step.status = "skipped"
            self.store.save_plan(plan)

        self.store.save_receipt(receipt)
        self._emit(
            EVENT_RECEIPT_CREATED, receipt.receipt_id,
            f"receipt created ({'executed' if result else 'not executed'})",
            verification_status=receipt.verification_status,
        )

        if receipt.artifact_ids:
            self.verify_receipt(receipt.receipt_id)
            refreshed = self.store.get_receipt(receipt.receipt_id)
            if refreshed is not None:
                receipt = refreshed

        return ExecutionOutcome(
            plan=plan,
            policy=policy,
            result=result,
            receipt=receipt,
            route_reason=route_reason,
            events=list(self._events),
        )

    def _execute(
        self, plan: ExecutionPlan, step: ExecutionStep, receipt: WorkReceipt
    ) -> ExecutionResult:
        step.status = "running"
        self._emit(
            EVENT_EXECUTION_STARTED, plan.plan_id,
            f"executing: {' '.join(step.command_argv[:4])}...",
        )
        result = self.runner.run(
            step.command_argv,
            plan_id=plan.plan_id,
            step_id=step.step_id,
            runtime=plan.runtime,
            cwd=plan.cwd,
            timeout_seconds=step.timeout_seconds,
        )
        step.status = "succeeded" if result.status == "succeeded" else "failed"
        step.started_at = result.started_at
        step.finished_at = result.finished_at
        self.store.save_plan(plan)
        self.store.save_result(result)
        receipt.execution_id = result.execution_id

        self._emit(
            EVENT_EXECUTION_OUTPUT, result.execution_id,
            f"captured {len(result.stdout_preview)} preview chars",
            return_code=result.return_code,
        )
        if result.status == "succeeded":
            self._emit(EVENT_EXECUTION_SUCCEEDED, result.execution_id, "execution succeeded")
        else:
            self._emit(
                EVENT_EXECUTION_FAILED, result.execution_id,
                f"execution {result.status}: {result.error or 'unknown error'}",
            )

        # Attach captured output as hashed artifacts.
        for stream, file_path in (("stdout", result.stdout_path), ("stderr", result.stderr_path)):
            if not file_path:
                continue
            artifact = attach_artifact(
                file_path,
                source_runtime=plan.runtime,
                artifact_type=stream,
                plan_id=plan.plan_id,
                execution_id=result.execution_id,
                summary=f"captured {stream} for task: {plan.task[:80]}",
            )
            self.store.save_artifact(artifact)
            receipt.artifact_ids.append(artifact.artifact_id)
            self._emit(
                EVENT_ARTIFACT_CREATED, artifact.artifact_id,
                f"{stream} artifact hashed ({artifact.size_bytes} bytes)",
                sha256=artifact.sha256,
            )
        return result

    # --- Verification ---

    def verify_receipt(self, receipt_id: str) -> str:
        """Recompute hashes for all artifacts a receipt references.

        Returns the new verification status: verified, failed, partial,
        or unverified (no artifacts attached).
        """
        receipt = self.store.get_receipt(receipt_id)
        if receipt is None:
            raise KeyError(f"unknown receipt: {receipt_id}")
        if not receipt.artifact_ids:
            return receipt.verification_status

        outcomes: list[bool] = []
        for artifact_id in receipt.artifact_ids:
            artifact = self.store.get_artifact(artifact_id)
            if artifact is None:
                outcomes.append(False)
                continue
            outcomes.append(verify_artifact(artifact).verified)

        if all(outcomes):
            status = "verified"
            self._emit(EVENT_VERIFICATION_PASSED, receipt_id, "all artifact hashes match")
        elif any(outcomes):
            status = "partial"
            self._emit(
                EVENT_VERIFICATION_FAILED, receipt_id,
                "some artifact hashes failed verification",
            )
        else:
            status = "failed"
            self._emit(
                EVENT_VERIFICATION_FAILED, receipt_id,
                "all artifact hashes failed verification",
            )
        self.store.set_receipt_verification(receipt_id, status)
        return status
