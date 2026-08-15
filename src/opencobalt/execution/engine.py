"""Execution engine: the Receipt-Backed Execution v0 vertical slice.

route task -> create plan -> build safe command -> enforce policy ->
run or dry-run -> capture output -> attach artifacts -> hash artifacts ->
write receipt -> verify receipt.

Every stage emits a structured event so a future TUI/UI can render live
task status (planning / running / verifying / done / failed).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Literal

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
from .normalization import (
    build_invocation,
    build_normalized_receipt,
    capability_snapshot_payload,
    events_for_receipt,
    verify_normalized_integrity,
)
from .policy import PolicyDecision, check_execution, classify_risk, max_risk
from .runner import ProcessRunner, redact_argv, redact_text
from .store import ExecutionStore

_DEFAULT_EVENTS_PATH = Path(".opencobalt") / "events" / "execution.jsonl"

EVENT_TASK_RECEIVED = "task.received"
EVENT_ROUTE_SELECTED = "route.selected"
EVENT_PLAN_CREATED = "plan.created"
EVENT_PLAN_REPLAYED = "plan.replayed"
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
        mission_id: str | None = None,
        approval_id: str | None = None,
        mission_step_id: str | None = None,
        approval_step_id: str | None = None,
        execution_context: Literal["general_task", "answer_only_inference"] = "general_task",
        risk_subject: str | None = None,
        session_handler: Callable[..., Any] | None = None,
        cancel_check: Callable[[], bool] | None = None,
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

        # 2. Classify process authority separately from answer-only subject matter.
        # Only runtimes whose adapter contract isolates inference from tools/files
        # may de-escalate topic keywords. Agent CLIs retain prompt risk, and a
        # yellow action becomes red because "answer only" is not an OS sandbox.
        authority_evidence: dict[str, Any] = {}
        if execution_context == "answer_only_inference":
            subject = risk_subject if risk_subject is not None else task
            subject_risk = max_risk(
                classify_risk(subject),
                adapter.risk_for_task(subject),
            )
            isolation_proven = bool(
                getattr(adapter, "isolates_answer_only_inference", False)
            )
            if isolation_proven:
                risk = max_risk("yellow", risk_from_route)
            else:
                risk = max_risk("red", subject_risk, risk_from_route)
            authority_evidence = {
                "execution_context": execution_context,
                "risk_subject_source": (
                    "current_user_request" if risk_subject is not None else "composed_task"
                ),
                "risk_subject_risk": subject_risk,
                "risk_subject_sha256": hashlib.sha256(
                    redact_text(subject).encode("utf-8")
                ).hexdigest(),
                "runtime_isolation_proven": isolation_proven,
            }
            route_reason = f"{route_reason}; bounded answer-only inference process"
        else:
            risk = max_risk(classify_risk(task), risk_from_route, adapter.risk_for_task(task))
        needs_approval = risk in ("red", "black")
        capability_snapshot = adapter.discover_capabilities()
        capabilities = capability_snapshot.capability_details
        limitations = list(capability_snapshot.limitations)
        if execution_context == "answer_only_inference":
            if getattr(adapter, "isolates_answer_only_inference", False):
                limitations.append(
                    "isolated answer-only inference process; subject-matter and outcome risk "
                    "remain on the linked OpenCobalt route record"
                )
            else:
                limitations.append(
                    "answer-only intent is not runtime isolation; this agent invocation "
                    "requires explicit approval through ExecutionEngine"
                )

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
        timeout = timeout_seconds or adapter.default_timeout_seconds()
        command_error: str | None = None
        command_argv: list[str] = []
        if not capability_snapshot.available:
            command_error = f"runtime unavailable: {runtime}"
        elif not capability_snapshot.supports_noninteractive:
            command_error = "non-interactive invocation unavailable"
        else:
            try:
                command_argv = adapter.build_command(redacted_task, options)
            except ValueError as exc:
                command_error = str(exc)
        if command_error:
            limitations.append(command_error)
            self._emit(
                EVENT_POLICY_CHECKED,
                runtime,
                f"adapter skipped: {command_error}",
                allowed=False,
                risk_level=risk,
            )

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
            task=redacted_task,
            runtime=runtime,
            model_policy=model,
            cwd=cwd,
            risk_level=risk,
            approval_required=needs_approval,
            steps=[step],
            dry_run=dry_run,
        )
        invocation = build_invocation(
            adapter_id=runtime,
            command_argv=command_argv,
            cwd=cwd,
            expected_artifacts=list(capability_snapshot.supported_artifact_types),
            risk_level=risk,
            dry_run=dry_run,
            timeout_seconds=timeout,
            mission_id=mission_id,
            approval_id=approval_id,
            mission_step_id=mission_step_id,
            approval_step_id=approval_step_id,
            structured_action={
                **authority_evidence,
                **({"skipped_reason": command_error} if command_error else {}),
            },
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
            allowed=policy.allowed,
            risk_level=policy.risk_level,
            **authority_evidence,
        )

        receipt = WorkReceipt(
            plan_id=plan.plan_id,
            task=redacted_task,
            selected_runtime=runtime,
            route_reason=route_reason,
            risk_level=risk,
            approval_required=needs_approval,
            capabilities_snapshot=capability_snapshot_payload(
                capabilities,
                capability_snapshot,
            ),
            command_plan=redact_argv(command_argv),
            adapter_id=runtime,
            capability_snapshot_hash=capability_snapshot.snapshot_hash,
            normalized_invocation=invocation,
            limitations=limitations,
        )

        result: ExecutionResult | None = None
        if policy.allowed and not dry_run and not command_error:
            result = self._execute(
                plan, step, receipt, session_handler=session_handler, cancel_check=cancel_check
            )
        elif dry_run or command_error:
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
        receipt = self._finalize_receipt(
            receipt=receipt,
            plan=plan,
            invocation=invocation,
            capability_snapshot=capability_snapshot,
            result=result,
            limitations=limitations,
        )

        return ExecutionOutcome(
            plan=plan,
            policy=policy,
            result=result,
            receipt=receipt,
            route_reason=route_reason,
            events=list(self._events),
        )

    def replay_plan(
        self,
        plan_id: str,
        *,
        execute: bool = False,
        approved: bool = False,
        timeout_seconds: int | None = None,
    ) -> ExecutionOutcome:
        """Replay a stored plan's command through the policy gate.

        Builds a fresh plan (new ids) from the stored command plan. The
        command is never re-routed or rebuilt, only re-gated: dry-run by
        default, red risk needs approval, black risk stays blocked.
        """
        self._events = []
        original = self.store.get_plan(plan_id)
        if original is None:
            raise KeyError(f"unknown plan: {plan_id}")
        if not original.steps:
            raise ValueError(f"plan has no steps to replay: {plan_id}")

        dry_run = not execute
        risk = original.risk_level
        needs_approval = risk in ("red", "black")
        route_reason = f"replay of plan {plan_id}"

        steps = [
            ExecutionStep(
                runtime=source.runtime,
                command_argv=list(source.command_argv),
                description=f"replay: {source.description}".rstrip(": "),
                risk_level=source.risk_level,
                approval_required=source.approval_required,
                timeout_seconds=timeout_seconds or source.timeout_seconds,
            )
            for source in original.steps
        ]
        plan = ExecutionPlan(
            task=redact_text(original.task),
            runtime=original.runtime,
            model_policy=original.model_policy,
            cwd=original.cwd,
            risk_level=risk,
            approval_required=needs_approval,
            steps=steps,
            dry_run=dry_run,
        )
        adapter = get_adapter(original.runtime)
        capability_snapshot = adapter.discover_capabilities()
        capabilities = capability_snapshot.capability_details
        limitations = list(capability_snapshot.limitations)
        invocation = build_invocation(
            adapter_id=original.runtime,
            command_argv=steps[0].command_argv,
            cwd=original.cwd,
            expected_artifacts=list(capability_snapshot.supported_artifact_types),
            risk_level=risk,
            dry_run=dry_run,
            timeout_seconds=steps[0].timeout_seconds,
            structured_action={"replay_of_plan": plan_id},
        )
        self.store.save_plan(plan)
        self._emit(
            EVENT_PLAN_REPLAYED, plan.plan_id,
            f"replaying plan {plan_id} as {plan.plan_id} (risk {risk})",
            source_plan_id=plan_id,
            command_argv=redact_argv(steps[0].command_argv),
            dry_run=dry_run,
        )

        policy = check_execution(risk, dry_run=dry_run, execute=execute, approved=approved)
        self._emit(
            EVENT_POLICY_CHECKED, plan.plan_id,
            f"policy: {'allowed' if policy.allowed else 'blocked'} ({policy.reason})",
            allowed=policy.allowed, risk_level=policy.risk_level,
        )

        receipt = WorkReceipt(
            plan_id=plan.plan_id,
            task=redact_text(original.task),
            selected_runtime=original.runtime,
            route_reason=route_reason,
            risk_level=risk,
            approval_required=needs_approval,
            capabilities_snapshot=capability_snapshot_payload(
                capabilities,
                capability_snapshot,
            ),
            command_plan=redact_argv(list(steps[0].command_argv)),
            adapter_id=original.runtime,
            capability_snapshot_hash=capability_snapshot.snapshot_hash,
            normalized_invocation=invocation,
            limitations=limitations,
        )

        result: ExecutionResult | None = None
        if policy.allowed and not dry_run:
            result = self._execute(plan, steps[0], receipt)
        elif dry_run:
            for step in steps:
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
        receipt = self._finalize_receipt(
            receipt=receipt,
            plan=plan,
            invocation=invocation,
            capability_snapshot=capability_snapshot,
            result=result,
            limitations=limitations,
        )

        return ExecutionOutcome(
            plan=plan,
            policy=policy,
            result=result,
            receipt=receipt,
            route_reason=route_reason,
            events=list(self._events),
        )

    def _execute(
        self,
        plan: ExecutionPlan,
        step: ExecutionStep,
        receipt: WorkReceipt,
        session_handler: Callable[..., Any] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ExecutionResult:
        step.status = "running"
        self._emit(
            EVENT_EXECUTION_STARTED, plan.plan_id,
            f"executing: {' '.join(step.command_argv[:4])}...",
        )
        if session_handler is not None:
            result = self.runner.interact(
                step.command_argv,
                plan_id=plan.plan_id,
                handler=session_handler,
                step_id=step.step_id,
                runtime=plan.runtime,
                cwd=plan.cwd,
                timeout_seconds=step.timeout_seconds,
                cancel_check=cancel_check,
            )
        else:
            result = self.runner.run(
                step.command_argv,
                plan_id=plan.plan_id,
                step_id=step.step_id,
                runtime=plan.runtime,
                cwd=plan.cwd,
                timeout_seconds=step.timeout_seconds,
                cancel_check=cancel_check,
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

    def _finalize_receipt(
        self,
        *,
        receipt: WorkReceipt,
        plan: ExecutionPlan,
        invocation,
        capability_snapshot,
        result: ExecutionResult | None,
        limitations: list[str],
        provenance_refs: list[str] | None = None,
    ) -> WorkReceipt:
        artifacts = [
            artifact
            for artifact_id in receipt.artifact_ids
            if (artifact := self.store.get_artifact(artifact_id)) is not None
        ]
        refs = provenance_refs or [plan.plan_id]
        if receipt.execution_id:
            refs.append(receipt.execution_id)
        refs.extend(receipt.artifact_ids)
        receipt.adapter_id = invocation.adapter_id
        receipt.capability_snapshot_hash = capability_snapshot.snapshot_hash
        receipt.normalized_invocation = invocation
        receipt.adapter_events = events_for_receipt(
            events=self._events,
            invocation_id=invocation.invocation_id,
            adapter_id=invocation.adapter_id,
        )
        receipt.provenance_refs = refs
        receipt.limitations = list(dict.fromkeys(limitations))
        receipt.normalized_receipt = build_normalized_receipt(
            receipt_id=receipt.receipt_id,
            invocation=invocation,
            capability_snapshot=capability_snapshot,
            plan=plan,
            result=result,
            artifacts=artifacts,
            verification_status=receipt.verification_status,
            limitations=receipt.limitations,
            provenance_refs=receipt.provenance_refs,
            event_count=len(self._events),
        )
        self.store.save_receipt(receipt)
        return receipt

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
            if not verify_normalized_integrity(receipt, []):
                self.store.set_receipt_verification(receipt_id, "failed")
                return "failed"
            return receipt.verification_status

        outcomes: list[bool] = []
        artifacts = []
        for artifact_id in receipt.artifact_ids:
            artifact = self.store.get_artifact(artifact_id)
            if artifact is None:
                outcomes.append(False)
                continue
            artifacts.append(artifact)
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
        if not verify_normalized_integrity(receipt, artifacts):
            status = "failed"
            self._emit(
                EVENT_VERIFICATION_FAILED, receipt_id,
                "normalized receipt integrity failed",
            )
        if receipt.normalized_receipt is not None:
            receipt.normalized_receipt.verification_status = status
            self.store.save_receipt(receipt)
        self.store.set_receipt_verification(receipt_id, status)
        return status
