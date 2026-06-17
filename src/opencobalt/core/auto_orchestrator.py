"""Deterministic automatic orchestration front door.

V1 plans over existing OpenCobalt primitives. It does not call an LLM, does
not run external runtimes directly, and does not cross authority boundaries.
Runtime dry-runs or execution remain ExecutionEngine responsibilities.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from opencobalt.execution.runner import redact_text

from .autonomy_envelopes import (
    AUTONOMY_ENVELOPES,
    COGNITIVE_BUDGETS,
    get_autonomy_envelope,
    get_cognitive_budget,
)

AutoIntent = Literal[
    "repo_improvement",
    "runtime_adapter_work",
    "bug_fix",
    "audit_merge",
    "roadmap_design",
    "external_research",
    "mission_execution",
    "status_inspection",
    "unknown",
]

RoutePrimitive = Literal[
    "status_check",
    "adapter_health_check",
    "mission_start",
    "opportunity_discovery",
    "evolve_candidate_generation",
    "approval_queue",
    "receipt_inspection",
    "provenance_why",
    "run_dry_run",
    "verification_gates",
    "roadmap_design",
    "external_research",
]


class AutoRouteStep(BaseModel):
    """One ordered internal primitive selected by the auto-orchestrator."""

    model_config = ConfigDict(frozen=True)

    order: int
    primitive: RoutePrimitive
    command_hint: str
    why: str
    produces_receipt: bool = False
    expected_receipt: bool = False
    uses_execution_engine: bool = False
    approval_required: bool = False
    blocked_authority: list[str] = Field(default_factory=list)


class AutoPlan(BaseModel):
    """Deterministic plan for one natural-language goal."""

    model_config = ConfigDict(frozen=True)

    auto_plan_id: str
    auto_plan_hash: str
    goal: str
    intent: AutoIntent
    selected_envelope: str
    selected_cognitive_budget: str
    internal_route_steps: list[AutoRouteStep] = Field(default_factory=list)
    required_approvals: list[str] = Field(default_factory=list)
    expected_receipts: list[str] = Field(default_factory=list)
    next_recommended_action: str
    did_actions: list[str] = Field(default_factory=list)
    execute_requested: bool = False


@dataclass(frozen=True)
class AutoMissionRecord:
    """Durable mission attachment created from one AutoPlan."""

    plan: AutoPlan
    mission_id: str
    route_step_ids: list[str]


_INTENT_KEYWORDS: dict[AutoIntent, tuple[str, ...]] = {
    "status_inspection": (
        "status", "health", "pending", "show", "list", "inspect current",
        "what is current", "what's current",
    ),
    "audit_merge": (
        "audit pr", "pull request", "merge", "review pr", "merge if safe",
        "merge-ready", "pr ",
    ),
    "runtime_adapter_work": (
        "runtime adapter", "adapter", "codex", "claude", "cursor",
        "antigravity", "execution runtime",
    ),
    "bug_fix": (
        "bug", "fix", "failing", "failure", "regression", "traceback",
        "broken", "pytest failure", "error",
    ),
    "external_research": (
        "external docs", "current docs", "research", "web", "internet",
        "latest", "compare options", "source",
    ),
    "mission_execution": (
        "mission", "long-running", "long running", "while i am away",
        "while i'm away", "for hours", "multi-hour", "autonomous mission",
    ),
    "roadmap_design": (
        "roadmap", "design", "strategy", "architecture", "plan the",
        "proposal", "spec",
    ),
    "repo_improvement": (
        "improve opencobalt", "self-improve", "implement", "build", "add",
        "refactor", "tests", "docs", "safely",
    ),
    "unknown": (),
}

_ENVELOPE_BY_INTENT: dict[AutoIntent, str] = {
    "status_inspection": "observe",
    "external_research": "plan",
    "roadmap_design": "plan",
    "mission_execution": "plan",
    "audit_merge": "dry_run",
    "runtime_adapter_work": "dry_run",
    "bug_fix": "dry_run",
    "repo_improvement": "dry_run",
    "unknown": "plan",
}

_BUDGET_BY_INTENT: dict[AutoIntent, str] = {
    "status_inspection": "low",
    "external_research": "research",
    "roadmap_design": "medium",
    "mission_execution": "high",
    "audit_merge": "high",
    "runtime_adapter_work": "high",
    "bug_fix": "medium",
    "repo_improvement": "high",
    "unknown": "low",
}


class AutoOrchestrator:
    """Classify a goal and build a deterministic internal route plan."""

    def classify_intent(self, goal: str) -> AutoIntent:
        """Return the first deterministic intent match for a goal."""
        lower = goal.strip().lower()
        for intent in (
            "status_inspection",
            "audit_merge",
            "runtime_adapter_work",
            "bug_fix",
            "external_research",
            "mission_execution",
            "roadmap_design",
            "repo_improvement",
        ):
            if any(keyword in lower for keyword in _INTENT_KEYWORDS[intent]):
                return intent
        return "unknown"

    def plan(
        self,
        goal: str,
        *,
        envelope_id: str | None = None,
        cognitive_budget_id: str | None = None,
        execute: bool = False,
    ) -> AutoPlan:
        """Build a deterministic route plan without executing it."""
        redacted_goal = redact_text(goal.strip())
        intent = self.classify_intent(redacted_goal)
        selected_envelope = envelope_id or _ENVELOPE_BY_INTENT[intent]
        selected_budget = cognitive_budget_id or _BUDGET_BY_INTENT[intent]

        get_autonomy_envelope(selected_envelope)
        get_cognitive_budget(selected_budget)

        steps = self._steps_for(intent, redacted_goal)
        required_approvals = self._required_approvals(intent, selected_envelope, execute)
        expected_receipts = self._expected_receipts(steps)
        did_actions = ["planned only; no subprocesses started"]
        if execute:
            did_actions.append(
                "execution was requested, but v1 does not cross approval or authority boundaries"
            )

        payload = {
            "goal": redacted_goal,
            "intent": intent,
            "selected_envelope": selected_envelope,
            "selected_cognitive_budget": selected_budget,
            "internal_route_steps": steps,
            "required_approvals": required_approvals,
            "expected_receipts": expected_receipts,
            "next_recommended_action": self._next_action(intent, redacted_goal),
            "did_actions": did_actions,
            "execute_requested": execute,
        }
        digest = _stable_plan_hash(payload)

        return AutoPlan(
            auto_plan_id="aplan-" + digest[:12],
            auto_plan_hash=digest,
            **payload,
        )

    def create_mission(
        self,
        goal: str,
        *,
        envelope_id: str | None = None,
        cognitive_budget_id: str | None = None,
        execute: bool = False,
        db_path: Path | None = None,
        root: Path | None = None,
    ) -> AutoMissionRecord:
        """Persist an AutoPlan as durable mission state without execution."""
        from .mission_engine import MissionEngine

        plan = self.plan(
            goal,
            envelope_id=envelope_id,
            cognitive_budget_id=cognitive_budget_id,
            execute=execute,
        )
        mission, steps = MissionEngine(root=root, db_path=db_path).create_auto_mission(
            plan
        )
        return AutoMissionRecord(
            plan=plan,
            mission_id=mission.mission_id,
            route_step_ids=[step.step_id for step in steps],
        )

    def _steps_for(self, intent: AutoIntent, goal: str) -> list[AutoRouteStep]:
        goal_arg = shlex.quote(goal)
        steps: list[tuple[RoutePrimitive, str, str, bool, bool, bool]]

        base_status = (
            "status_check",
            "opencobalt status",
            "Ground the plan in current ledger, approval, receipt, and health state.",
            False,
            False,
            False,
        )
        adapter_health = (
            "adapter_health_check",
            "opencobalt adapters list",
            "Inspect receipt-backed runtime capability snapshots before selecting a runtime.",
            False,
            False,
            False,
        )
        approvals = (
            "approval_queue",
            "opencobalt approvals list",
            "Find existing approval boundaries before proposing execution.",
            False,
            False,
            False,
        )
        receipts = (
            "receipt_inspection",
            "opencobalt receipts list",
            "Surface recent evidence before trusting prior work.",
            False,
            False,
            False,
        )
        verify = (
            "verification_gates",
            ".venv/bin/ruff check . ; .venv/bin/opencobalt public-check ; .venv/bin/pytest",
            "Keep the baseline and public safety gates explicit in the internal plan.",
            False,
            False,
            False,
        )

        if intent == "status_inspection":
            steps = [base_status, approvals, receipts]
        elif intent == "runtime_adapter_work":
            steps = [
                base_status,
                adapter_health,
                (
                    "run_dry_run",
                    "opencobalt run " + goal_arg + " --dry-run",
                    "Any runtime smoke must go through ExecutionEngine and produce a receipt.",
                    True,
                    True,
                    False,
                ),
                receipts,
                (
                    "provenance_why",
                    "opencobalt why <receipt_or_plan_id>",
                    "Trace the dry-run plan through receipt and provenance metadata.",
                    False,
                    False,
                    False,
                ),
                verify,
            ]
        elif intent == "bug_fix":
            steps = [
                base_status,
                (
                    "mission_start",
                    "opencobalt missions start " + goal_arg,
                    "A bug fix can become a supervised mission before any risky execution.",
                    False,
                    False,
                    True,
                ),
                verify,
                receipts,
            ]
        elif intent == "audit_merge":
            steps = [
                base_status,
                verify,
                approvals,
                receipts,
                (
                    "provenance_why",
                    "opencobalt why <mission_or_receipt_id>",
                    "Merge decisions need a local evidence chain, not a stale claim.",
                    False,
                    False,
                    False,
                ),
            ]
        elif intent == "roadmap_design":
            steps = [
                base_status,
                (
                    "roadmap_design",
                    "opencobalt evolve roadmap",
                    "Roadmap proposals are append-only and explicit when written.",
                    False,
                    False,
                    True,
                ),
                (
                    "evolve_candidate_generation",
                    "opencobalt evolve start " + goal_arg,
                    "Self-improvement proposals reuse evolve scoring and approval paths.",
                    False,
                    False,
                    True,
                ),
                approvals,
            ]
        elif intent == "external_research":
            steps = [
                base_status,
                (
                    "external_research",
                    "Context7 or official docs only when current external API docs are needed",
                    "Research is appropriate for this budget, but sources stay explicit and verified.",
                    False,
                    False,
                    True,
                ),
                (
                    "roadmap_design",
                    "opencobalt opportunities brainstorm " + goal_arg,
                    "Turn gathered evidence into local opportunity tracks without executing work.",
                    False,
                    False,
                    False,
                ),
            ]
        elif intent == "mission_execution":
            steps = [
                base_status,
                (
                    "mission_start",
                    "opencobalt missions start " + goal_arg,
                    "Start the durable mission spine, but stop at approval boundaries.",
                    False,
                    False,
                    True,
                ),
                (
                    "opportunity_discovery",
                    "opencobalt opportunities brainstorm " + goal_arg,
                    "Use existing opportunity scoring as the discovery primitive.",
                    False,
                    False,
                    False,
                ),
                approvals,
                (
                    "run_dry_run",
                    "opencobalt missions run-step <step_id>",
                    "Mission execution remains dry-run by default and receipt-backed.",
                    True,
                    True,
                    True,
                ),
                receipts,
            ]
        elif intent == "repo_improvement":
            steps = [
                base_status,
                adapter_health,
                (
                    "opportunity_discovery",
                    "opencobalt opportunities brainstorm " + goal_arg,
                    "Find and score local improvement tracks before choosing work.",
                    False,
                    False,
                    False,
                ),
                (
                    "mission_start",
                    "opencobalt missions start " + goal_arg,
                    "Promote the selected path into the durable supervised mission spine.",
                    False,
                    False,
                    True,
                ),
                approvals,
                verify,
            ]
        else:
            steps = [
                base_status,
                (
                    "roadmap_design",
                    "opencobalt route " + goal_arg,
                    "Unknown goals should be routed or clarified before autonomy expands.",
                    False,
                    False,
                    False,
                ),
            ]

        return [
            AutoRouteStep(
                order=index,
                primitive=primitive,
                command_hint=command,
                why=why,
                produces_receipt=produces_receipt,
                expected_receipt=produces_receipt,
                uses_execution_engine=uses_execution_engine,
                approval_required=approval_required,
            )
            for index, (
                primitive,
                command,
                why,
                produces_receipt,
                uses_execution_engine,
                approval_required,
            ) in enumerate(steps, start=1)
        ]

    def _required_approvals(
        self,
        intent: AutoIntent,
        envelope_id: str,
        execute: bool,
    ) -> list[str]:
        envelope = AUTONOMY_ENVELOPES[envelope_id]
        approvals = list(envelope.required_approvals)
        if intent in {"repo_improvement", "bug_fix", "runtime_adapter_work", "mission_execution"}:
            approvals.append("approve any non-dry-run execution through existing policy gates")
        if execute:
            approvals.append("v1 execute request is advisory until a future authority grant exists")
        return list(dict.fromkeys(approvals))

    def _expected_receipts(self, steps: list[AutoRouteStep]) -> list[str]:
        if any(step.produces_receipt for step in steps):
            return [
                "WorkReceipt from ExecutionEngine dry-run or approved execution",
                "Artifact hashes when a planned step creates output files",
            ]
        return [
            "No receipt is created by v1 planning alone",
            "Receipts begin when a planned ExecutionEngine dry-run or mission run-step is invoked",
        ]

    def _next_action(self, intent: AutoIntent, goal: str) -> str:
        goal_arg = shlex.quote(goal)
        if intent == "status_inspection":
            return "opencobalt status"
        if intent == "runtime_adapter_work":
            return "opencobalt adapters list"
        if intent == "audit_merge":
            return ".venv/bin/ruff check . ; .venv/bin/opencobalt public-check ; .venv/bin/pytest"
        if intent == "roadmap_design":
            return "opencobalt evolve start " + goal_arg
        if intent == "external_research":
            return "gather official documentation, then run opencobalt opportunities brainstorm " + goal_arg
        if intent == "mission_execution":
            return "opencobalt missions start " + goal_arg
        if intent in {"repo_improvement", "bug_fix"}:
            return "opencobalt opportunities brainstorm " + goal_arg
        return "opencobalt route " + goal_arg


def render_auto_plan(plan: AutoPlan) -> str:
    """Render an AutoPlan as a concise CLI and shell report."""
    budget = COGNITIVE_BUDGETS[plan.selected_cognitive_budget]
    envelope = AUTONOMY_ENVELOPES[plan.selected_envelope]
    lines = [
        "Auto orchestration plan",
        "AutoPlan: " + plan.auto_plan_id,
        "Goal: " + plan.goal,
        "Intent: " + plan.intent,
        "Envelope: " + plan.selected_envelope + " (" + envelope.max_risk_level + " max risk)",
        "Cognitive budget: "
        + plan.selected_cognitive_budget
        + " ("
        + str(budget.max_runtime_iterations)
        + " iteration cap)",
        "",
        "What I would do:",
    ]
    for step in plan.internal_route_steps:
        marker = " via ExecutionEngine" if step.uses_execution_engine else ""
        receipt = " receipt" if step.produces_receipt else ""
        lines.append(
            "  "
            + str(step.order)
            + ". "
            + step.primitive
            + marker
            + receipt
            + ": "
            + step.command_hint
        )
        lines.append("     why: " + step.why)

    lines.extend(["", "Required approvals:"])
    for approval in plan.required_approvals or ["none for planning"]:
        lines.append("  - " + approval)

    lines.extend(["", "Expected receipts:"])
    for receipt in plan.expected_receipts:
        lines.append("  - " + receipt)

    lines.extend(["", "What I did:"])
    for action in plan.did_actions:
        lines.append("  - " + action)

    lines.extend(["", "Next recommended action: " + plan.next_recommended_action])
    return "\n".join(lines)


def render_auto_mission_record(record: AutoMissionRecord) -> str:
    """Render the durable mission attachment created from an AutoPlan."""
    plan = record.plan
    lines = [
        "Mission created: " + record.mission_id,
        "",
        "What was persisted:",
        "  - original goal",
        "  - AutoPlan id/hash: " + plan.auto_plan_id + " / " + plan.auto_plan_hash[:16],
        "  - intent: " + plan.intent,
        "  - autonomy envelope: " + plan.selected_envelope,
        "  - cognitive budget: " + plan.selected_cognitive_budget,
        "  - route steps: " + str(len(record.route_step_ids)),
        "  - approval expectations",
        "  - expected receipts",
        "  - next recommended action",
        "",
        "What was not executed:",
        "  - no external runtimes started",
        "  - no subprocesses started by auto",
        "  - no approvals granted",
        "  - no receipts fabricated",
        "",
        "Inspect: opencobalt missions show " + record.mission_id[:13],
        "Why: opencobalt why " + record.mission_id[:13],
    ]
    return "\n".join(lines)


def _stable_plan_hash(payload: dict) -> str:
    serializable = json.loads(json.dumps(payload, default=_json_default, sort_keys=True))
    encoded = json.dumps(serializable, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json_default(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
