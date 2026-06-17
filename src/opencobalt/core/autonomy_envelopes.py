"""Autonomy envelopes and cognitive budgets for orchestration planning.

Autonomy describes how much OpenCobalt may do on its own. Authority describes
whether it may cross outward or irreversible boundaries such as push, merge,
deploy, spend, messages, or secrets. These definitions intentionally separate
the two so high-autonomy local loops do not become hidden authority grants.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["green", "yellow", "red", "black"]
BudgetId = Literal["low", "medium", "high", "xhigh", "research"]
EnvelopeId = Literal[
    "observe",
    "plan",
    "dry_run",
    "sandbox_exec",
    "repo_autopilot",
    "pr_drafter",
    "autonomous_lab",
    "operator_yolo",
    "production_guarded",
]
SubprocessMode = Literal[
    "none",
    "discovery_only",
    "dry_run_only",
    "policy_gated_local",
]


class AutonomyEnvelope(BaseModel):
    """Typed authority boundary for an automatic orchestration run."""

    model_config = ConfigDict(frozen=True)

    envelope_id: EnvelopeId
    description: str
    allowed_file_reads: list[str] = Field(default_factory=list)
    allowed_file_writes: list[str] = Field(default_factory=list)
    allowed_subprocess_execution: SubprocessMode = "none"
    allowed_external_runtime_execution: bool = False
    allowed_commit: bool = False
    allowed_branch_creation: bool = False
    allowed_push: bool = False
    allowed_merge: bool = False
    allowed_deploy: bool = False
    allowed_publish: bool = False
    allowed_spend: bool = False
    allowed_external_messages: bool = False
    allowed_secret_auth_access: bool = False
    required_approvals: list[str] = Field(default_factory=list)
    max_risk_level: RiskLevel = "green"
    receipt_requirements: list[str] = Field(default_factory=list)
    provenance_requirements: list[str] = Field(default_factory=list)
    default_cognitive_budget: BudgetId = "low"
    max_duration_minutes: int | None = None
    max_iterations: int | None = None


class CognitiveBudget(BaseModel):
    """Typed reasoning and fanout budget for an orchestration plan."""

    model_config = ConfigDict(frozen=True)

    budget_id: BudgetId
    intended_use: str
    allowed_runtimes: list[str] = Field(default_factory=list)
    max_subagents: int = 0
    max_recursion_depth: int = 0
    max_runtime_iterations: int = 1
    required_verification_gates: list[str] = Field(default_factory=list)
    web_research_appropriate: bool = False
    external_runtimes_may_be_invoked: bool = False
    cross_agent_debate_enabled: bool = False


_RECEIPT_REQUIREMENTS = [
    "record route plan before execution",
    "use ExecutionEngine for runtime dry-runs or execution",
    "hash artifacts when execution produces files",
]

_PROVENANCE_REQUIREMENTS = [
    "link plans to approvals, receipts, and why traces when created",
    "record whether a claim is confirmed or inferred",
]

AUTONOMY_ENVELOPES: dict[str, AutonomyEnvelope] = {
    "observe": AutonomyEnvelope(
        envelope_id="observe",
        description="Read-only inspection and reporting. No writes or subprocess task execution.",
        allowed_file_reads=["repo", "docs", "tests", "ledger"],
        allowed_file_writes=[],
        allowed_subprocess_execution="discovery_only",
        required_approvals=[],
        max_risk_level="green",
        receipt_requirements=["record findings when a higher layer persists a report"],
        provenance_requirements=["cite inspected local sources"],
        default_cognitive_budget="low",
        max_duration_minutes=15,
        max_iterations=3,
    ),
    "plan": AutonomyEnvelope(
        envelope_id="plan",
        description="Build deterministic plans over existing primitives without mutating project state.",
        allowed_file_reads=["repo", "docs", "tests", "ledger"],
        allowed_file_writes=[],
        allowed_subprocess_execution="discovery_only",
        required_approvals=[],
        max_risk_level="green",
        receipt_requirements=_RECEIPT_REQUIREMENTS,
        provenance_requirements=_PROVENANCE_REQUIREMENTS,
        default_cognitive_budget="medium",
        max_duration_minutes=30,
        max_iterations=5,
    ),
    "dry_run": AutonomyEnvelope(
        envelope_id="dry_run",
        description="Plan and create safe dry-run receipts through existing policy gates.",
        allowed_file_reads=["repo", "docs", "tests", "ledger"],
        allowed_file_writes=[".opencobalt"],
        allowed_subprocess_execution="dry_run_only",
        required_approvals=["human approval before any non-dry-run execution"],
        max_risk_level="yellow",
        receipt_requirements=_RECEIPT_REQUIREMENTS,
        provenance_requirements=_PROVENANCE_REQUIREMENTS,
        default_cognitive_budget="medium",
        max_duration_minutes=45,
        max_iterations=8,
    ),
    "sandbox_exec": AutonomyEnvelope(
        envelope_id="sandbox_exec",
        description="Run local, policy-gated subprocesses such as tests inside the repository.",
        allowed_file_reads=["repo", "docs", "tests", "ledger"],
        allowed_file_writes=[".opencobalt", "generated-artifacts"],
        allowed_subprocess_execution="policy_gated_local",
        required_approvals=["human approval for red-risk commands"],
        max_risk_level="yellow",
        receipt_requirements=_RECEIPT_REQUIREMENTS,
        provenance_requirements=_PROVENANCE_REQUIREMENTS,
        default_cognitive_budget="high",
        max_duration_minutes=60,
        max_iterations=10,
    ),
    "repo_autopilot": AutonomyEnvelope(
        envelope_id="repo_autopilot",
        description="Local repo edits, tests, and optional local commits behind explicit approval.",
        allowed_file_reads=["repo", "docs", "tests", "ledger"],
        allowed_file_writes=["repo", ".opencobalt"],
        allowed_subprocess_execution="policy_gated_local",
        allowed_commit=True,
        allowed_branch_creation=True,
        required_approvals=["approve local commits", "approve red-risk commands"],
        max_risk_level="red",
        receipt_requirements=_RECEIPT_REQUIREMENTS,
        provenance_requirements=_PROVENANCE_REQUIREMENTS,
        default_cognitive_budget="high",
        max_duration_minutes=90,
        max_iterations=16,
    ),
    "pr_drafter": AutonomyEnvelope(
        envelope_id="pr_drafter",
        description="Prepare local PR materials as artifacts without pushing or opening a PR.",
        allowed_file_reads=["repo", "docs", "tests", "ledger"],
        allowed_file_writes=["repo", ".opencobalt"],
        allowed_subprocess_execution="policy_gated_local",
        allowed_commit=True,
        allowed_branch_creation=True,
        required_approvals=["approve local commits", "approve any future remote PR action"],
        max_risk_level="red",
        receipt_requirements=_RECEIPT_REQUIREMENTS,
        provenance_requirements=_PROVENANCE_REQUIREMENTS,
        default_cognitive_budget="high",
        max_duration_minutes=120,
        max_iterations=20,
    ),
    "autonomous_lab": AutonomyEnvelope(
        envelope_id="autonomous_lab",
        description="High-autonomy local experimentation with repo writes and tests only.",
        allowed_file_reads=["repo", "docs", "tests", "ledger", ".opencobalt"],
        allowed_file_writes=["repo", ".opencobalt", "generated-artifacts"],
        allowed_subprocess_execution="policy_gated_local",
        allowed_branch_creation=True,
        required_approvals=["approve local commits", "approve red-risk commands"],
        max_risk_level="red",
        receipt_requirements=_RECEIPT_REQUIREMENTS,
        provenance_requirements=_PROVENANCE_REQUIREMENTS,
        default_cognitive_budget="xhigh",
        max_duration_minutes=180,
        max_iterations=32,
    ),
    "operator_yolo": AutonomyEnvelope(
        envelope_id="operator_yolo",
        description="Maximum local autonomy, still without outward authority or secret access.",
        allowed_file_reads=["repo", "docs", "tests", "ledger", ".opencobalt"],
        allowed_file_writes=["repo", ".opencobalt", "generated-artifacts"],
        allowed_subprocess_execution="policy_gated_local",
        allowed_commit=True,
        allowed_branch_creation=True,
        required_approvals=["approve remote actions in a future authority grant"],
        max_risk_level="red",
        receipt_requirements=_RECEIPT_REQUIREMENTS,
        provenance_requirements=_PROVENANCE_REQUIREMENTS,
        default_cognitive_budget="xhigh",
        max_duration_minutes=240,
        max_iterations=48,
    ),
    "production_guarded": AutonomyEnvelope(
        envelope_id="production_guarded",
        description="Plan production-adjacent work, but block deploy, publish, spend, and secrets.",
        allowed_file_reads=["repo", "docs", "tests", "ledger"],
        allowed_file_writes=[".opencobalt", "generated-artifacts"],
        allowed_subprocess_execution="dry_run_only",
        required_approvals=[
            "human approval for production-adjacent changes",
            "future explicit authority grant for deploy or publish",
        ],
        max_risk_level="red",
        receipt_requirements=_RECEIPT_REQUIREMENTS,
        provenance_requirements=_PROVENANCE_REQUIREMENTS,
        default_cognitive_budget="high",
        max_duration_minutes=60,
        max_iterations=10,
    ),
}

COGNITIVE_BUDGETS: dict[str, CognitiveBudget] = {
    "low": CognitiveBudget(
        budget_id="low",
        intended_use="Quick status, lookup, and deterministic planning.",
        allowed_runtimes=["internal-primitives"],
        max_subagents=0,
        max_recursion_depth=0,
        max_runtime_iterations=1,
        required_verification_gates=["public-check before commit or push"],
    ),
    "medium": CognitiveBudget(
        budget_id="medium",
        intended_use="Single-loop implementation planning and small bug triage.",
        allowed_runtimes=["internal-primitives", "receipt-backed-dry-run"],
        max_subagents=2,
        max_recursion_depth=1,
        max_runtime_iterations=3,
        required_verification_gates=["ruff", "public-check", "targeted pytest"],
    ),
    "high": CognitiveBudget(
        budget_id="high",
        intended_use="Multi-step repo work with tests, docs, and approval checkpoints.",
        allowed_runtimes=[
            "internal-primitives",
            "receipt-backed-dry-run",
            "policy-gated-local-commands",
        ],
        max_subagents=4,
        max_recursion_depth=2,
        max_runtime_iterations=8,
        required_verification_gates=["ruff", "public-check", "pytest"],
        cross_agent_debate_enabled=True,
    ),
    "xhigh": CognitiveBudget(
        budget_id="xhigh",
        intended_use="Longer local autonomy loops that still stay inside explicit authority boundaries.",
        allowed_runtimes=[
            "internal-primitives",
            "receipt-backed-dry-run",
            "policy-gated-local-commands",
        ],
        max_subagents=6,
        max_recursion_depth=3,
        max_runtime_iterations=16,
        required_verification_gates=["ruff", "public-check", "pytest", "manual smoke"],
        cross_agent_debate_enabled=True,
    ),
    "research": CognitiveBudget(
        budget_id="research",
        intended_use="Evidence gathering and comparison before design or implementation.",
        allowed_runtimes=["internal-primitives", "official-docs-context"],
        max_subagents=3,
        max_recursion_depth=2,
        max_runtime_iterations=6,
        required_verification_gates=["cite sources", "separate confirmed from inferred claims"],
        web_research_appropriate=True,
        external_runtimes_may_be_invoked=False,
        cross_agent_debate_enabled=True,
    ),
}


def get_autonomy_envelope(envelope_id: str) -> AutonomyEnvelope:
    """Return one envelope by id."""
    try:
        return AUTONOMY_ENVELOPES[envelope_id]
    except KeyError as exc:
        raise ValueError(f"unknown autonomy envelope: {envelope_id}") from exc


def get_cognitive_budget(budget_id: str) -> CognitiveBudget:
    """Return one cognitive budget by id."""
    try:
        return COGNITIVE_BUDGETS[budget_id]
    except KeyError as exc:
        raise ValueError(f"unknown cognitive budget: {budget_id}") from exc
