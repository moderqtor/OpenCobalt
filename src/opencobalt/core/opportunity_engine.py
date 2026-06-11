"""Autonomous Opportunity Engine v0.

Supervised, local-first opportunity discovery. Takes a broad goal, classifies
it deterministically (no LLM), decomposes it into candidate opportunity
tracks, gathers local evidence, scores each track transparently, and builds
policy-aware delegation plans through the existing nested subagent
primitives.

Nothing in this module executes external actions. Plans are proposals: they
carry risk levels and approval state, and any real execution must flow
through the existing receipt-backed execution policy gate (opencobalt run /
plans execute). The moat is receipts, evidence, policy, and outcomes -- not
raw autonomy.

Pipeline (all automatic inside brainstorm()):

  goal_received -> track_created* -> evidence_attached* -> scored*
                -> plan_created*  -> report_created
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from opencobalt.execution.policy import classify_risk, max_risk

from .delegation import DelegationPlan
from .events import append_event, make_event
from .subagent_registry import SubagentRegistry, SubagentSpec

GOAL_CLASSES = (
    "product",
    "code_quality",
    "security_authorized",
    "growth",
    "research",
    "automation",
    "cost_saving",
    "design",
    "unknown",
)

EVIDENCE_SOURCES = (
    "repo_file",
    "tests",
    "docs",
    "receipt",
    "execution_result",
    "artifact_metadata",
    "route_history",
    "subagent_report",
    "note",
)

EVENT_GOAL_RECEIVED = "opportunity.goal_received"
EVENT_TRACK_CREATED = "opportunity.track_created"
EVENT_EVIDENCE_ATTACHED = "opportunity.evidence_attached"
EVENT_SCORED = "opportunity.scored"
EVENT_PLAN_CREATED = "opportunity.plan_created"
EVENT_REPORT_CREATED = "opportunity.report_created"

_DEFAULT_EVENTS_PATH = Path(".opencobalt") / "events" / "opportunity.jsonl"

# Transparent score weights. Positive dimensions add, penalty dimensions
# subtract. Every contribution is written into the score explanation.
SCORE_WEIGHTS: dict[str, float] = {
    "expected_impact": 0.18,
    "feasibility": 0.14,
    "evidence_strength": 0.14,
    "reversibility": 0.10,
    "novelty": 0.08,
    "monetization_potential": 0.08,
    "verification_quality": 0.10,
}
PENALTY_WEIGHTS: dict[str, float] = {
    "risk": 0.10,
    "time_cost": 0.08,
}
SCORE_DIMENSIONS = tuple(SCORE_WEIGHTS) + tuple(PENALTY_WEIGHTS)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# --- Goal classification (deterministic, keyword-scored) ---

_GOAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "product": (
        "product", "feature", "ship", "user experience", "polish", "launch",
        "onboarding", "useful", "opportunit",
    ),
    "code_quality": (
        "code quality", "refactor", "test", "coverage", "lint", "bug",
        "cleanup", "tech debt", "reliability", "maintainab",
    ),
    "security_authorized": (
        "security", "audit", "vulnerab", "hardening", "policy gate",
        "permission", "threat",
    ),
    "growth": (
        "growth", "adoption", "marketing", "audience", "stars", "community",
        "distribution", "users",
    ),
    "research": (
        "research", "investigate", "explore", "compare", "prior art",
        "feasibility study", "evaluate options",
    ),
    "automation": (
        "automat", "workflow", "pipeline", "orchestrat", "schedule",
        "hands-off", "autonomous",
    ),
    "cost_saving": (
        "cost", "spend", "cheaper", "budget", "token", "efficiency",
        "optimize usage",
    ),
    "design": (
        "design", "ui", "ux", "tui", "visual", "layout", "dashboard",
        "interface",
    ),
}


def classify_goal(text: str) -> str:
    """Classify a goal string into one of GOAL_CLASSES. Deterministic."""
    lowered = text.lower()
    best_class = "unknown"
    best_score = 0
    for goal_class in GOAL_CLASSES:
        keywords = _GOAL_KEYWORDS.get(goal_class, ())
        score = sum(1 for kw in keywords if kw in lowered)
        if score > best_score:
            best_class = goal_class
            best_score = score
    return best_class


# --- Models ---


@dataclass
class OpportunityGoal:
    """The broad goal the engine was asked to find opportunities for."""

    goal_id: str
    text: str
    goal_class: str
    created_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpportunityTrack:
    """One candidate direction decomposed from a goal."""

    track_id: str
    goal_id: str
    name: str
    track_type: str
    description: str = ""
    status: str = "proposed"  # proposed / scored / planned / done / dropped
    priors: dict[str, float] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    hypothesis_ids: list[str] = field(default_factory=list)
    plan_id: str | None = None


@dataclass
class OpportunityHypothesis:
    """A falsifiable statement a track is betting on."""

    hypothesis_id: str
    track_id: str
    statement: str
    status: str = "open"  # open / supported / refuted


@dataclass
class OpportunityEvidence:
    """One local-first piece of evidence attached to a track."""

    evidence_id: str
    track_id: str
    source_type: str  # one of EVIDENCE_SOURCES
    reference: str
    summary: str
    strength: float = 0.5  # 0..1
    collected_by: str = "engine"
    created_at: str = field(default_factory=_now_iso)


@dataclass
class OpportunityScore:
    """Transparent multi-dimension score. Every point is explainable."""

    track_id: str
    dimensions: dict[str, float]
    total: float
    explanation: list[str] = field(default_factory=list)
    scored_at: str = field(default_factory=_now_iso)


@dataclass
class OpportunityPlan:
    """A policy-aware, non-executing plan for one track.

    Holds a serialized delegation tree plus proposed local steps. Each step
    is risk-classified through the execution policy keywords; nothing here
    starts a process. approval_state gates anything above green.
    """

    plan_id: str
    track_id: str
    goal_id: str
    delegation: dict[str, Any]
    steps: list[dict[str, Any]] = field(default_factory=list)
    risk_level: str = "green"
    approval_state: str = "not_required"  # not_required / pending / approved
    executed: bool = False
    created_at: str = field(default_factory=_now_iso)


@dataclass
class OpportunityReport:
    """Ranked summary of one run, renderable as a table."""

    run_id: str
    goal_text: str
    goal_class: str
    ranked: list[dict[str, Any]] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=_now_iso)


@dataclass
class OpportunityRun:
    """Everything one brainstorm produced. Serializes losslessly to JSON."""

    run_id: str
    goal: OpportunityGoal
    tracks: list[OpportunityTrack] = field(default_factory=list)
    hypotheses: list[OpportunityHypothesis] = field(default_factory=list)
    evidence: list[OpportunityEvidence] = field(default_factory=list)
    scores: list[OpportunityScore] = field(default_factory=list)
    plans: list[OpportunityPlan] = field(default_factory=list)
    report: OpportunityReport | None = None
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": asdict(self.goal),
            "tracks": [asdict(t) for t in self.tracks],
            "hypotheses": [asdict(h) for h in self.hypotheses],
            "evidence": [asdict(e) for e in self.evidence],
            "scores": [asdict(s) for s in self.scores],
            "plans": [asdict(p) for p in self.plans],
            "report": asdict(self.report) if self.report else None,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpportunityRun:
        return cls(
            run_id=data["run_id"],
            goal=OpportunityGoal(**data["goal"]),
            tracks=[OpportunityTrack(**t) for t in data.get("tracks", [])],
            hypotheses=[OpportunityHypothesis(**h) for h in data.get("hypotheses", [])],
            evidence=[OpportunityEvidence(**e) for e in data.get("evidence", [])],
            scores=[OpportunityScore(**s) for s in data.get("scores", [])],
            plans=[OpportunityPlan(**p) for p in data.get("plans", [])],
            report=OpportunityReport(**data["report"]) if data.get("report") else None,
            created_at=data.get("created_at", _now_iso()),
        )

    def get_track(self, track_id: str) -> OpportunityTrack | None:
        for track in self.tracks:
            if track.track_id == track_id or track.track_id.startswith(track_id):
                return track
        return None

    def score_for(self, track_id: str) -> OpportunityScore | None:
        for score in self.scores:
            if score.track_id == track_id:
                return score
        return None


# --- Track library (extensible) ---


@dataclass
class TrackTemplate:
    """A reusable track idea with prior estimates for scoring.

    Priors are starting points on a 0..1 scale; evidence adjusts the final
    score. Register new templates with register_track_template().
    """

    name: str
    track_type: str
    description: str
    priors: dict[str, float] = field(default_factory=dict)


_BASE_TRACKS: list[TrackTemplate] = [
    TrackTemplate(
        name="docs improvement",
        track_type="docs",
        description="Close documentation gaps surfaced by the repo scan.",
        priors={"expected_impact": 0.55, "feasibility": 0.9, "risk": 0.1,
                "reversibility": 0.95, "time_cost": 0.25},
    ),
    TrackTemplate(
        name="test gaps",
        track_type="tests",
        description="Add tests for modules with weak or missing coverage.",
        priors={"expected_impact": 0.7, "feasibility": 0.8, "risk": 0.15,
                "reversibility": 0.9, "time_cost": 0.35,
                "verification_quality": 0.9},
    ),
    TrackTemplate(
        name="bug-risk scan",
        track_type="triage",
        description="Sweep TODO/FIXME markers and failure-prone paths.",
        priors={"expected_impact": 0.6, "feasibility": 0.85, "risk": 0.1,
                "reversibility": 0.95, "time_cost": 0.3},
    ),
]

_CLASS_TRACKS: dict[str, list[TrackTemplate]] = {
    "product": [
        TrackTemplate(
            name="product polish",
            track_type="product",
            description="Sharpen the highest-traffic CLI flows and outputs.",
            priors={"expected_impact": 0.75, "feasibility": 0.7, "risk": 0.25,
                    "novelty": 0.4, "monetization_potential": 0.5,
                    "time_cost": 0.45},
        ),
        TrackTemplate(
            name="integration opportunity",
            track_type="integration",
            description="Wire one more local tool into routing and receipts.",
            priors={"expected_impact": 0.65, "feasibility": 0.6, "risk": 0.35,
                    "novelty": 0.55, "monetization_potential": 0.45,
                    "time_cost": 0.55},
        ),
    ],
    "code_quality": [
        TrackTemplate(
            name="refactor hotspots",
            track_type="refactor",
            description="Refactor the largest modules without behavior change.",
            priors={"expected_impact": 0.6, "feasibility": 0.7, "risk": 0.3,
                    "reversibility": 0.8, "time_cost": 0.5},
        ),
    ],
    "security_authorized": [
        TrackTemplate(
            name="compliance/audit improvement",
            track_type="security",
            description="Audit policy gates, secrets scanning, and receipts.",
            priors={"expected_impact": 0.7, "feasibility": 0.75, "risk": 0.2,
                    "verification_quality": 0.85, "time_cost": 0.4},
        ),
    ],
    "growth": [
        TrackTemplate(
            name="monetization research",
            track_type="research",
            description="Map which receipt/provenance features teams pay for.",
            priors={"expected_impact": 0.6, "feasibility": 0.65, "risk": 0.2,
                    "novelty": 0.5, "monetization_potential": 0.85,
                    "time_cost": 0.45},
        ),
    ],
    "research": [
        TrackTemplate(
            name="local benchmark idea",
            track_type="benchmark",
            description="Design a reproducible local benchmark with receipts.",
            priors={"expected_impact": 0.55, "feasibility": 0.7, "risk": 0.2,
                    "novelty": 0.65, "verification_quality": 0.8,
                    "time_cost": 0.5},
        ),
    ],
    "automation": [
        TrackTemplate(
            name="routing improvement",
            track_type="routing",
            description="Use ledger outcomes to refine deterministic routing.",
            priors={"expected_impact": 0.7, "feasibility": 0.65, "risk": 0.25,
                    "novelty": 0.6, "time_cost": 0.5},
        ),
    ],
    "cost_saving": [
        TrackTemplate(
            name="cost optimization",
            track_type="cost",
            description="Shift more eligible work to worker-tier local tools.",
            priors={"expected_impact": 0.65, "feasibility": 0.7, "risk": 0.2,
                    "monetization_potential": 0.4, "time_cost": 0.35},
        ),
    ],
    "design": [
        TrackTemplate(
            name="UI/TUI improvement",
            track_type="design",
            description="Tighten the TUI and dashboard against DESIGN.md.",
            priors={"expected_impact": 0.6, "feasibility": 0.7, "risk": 0.2,
                    "novelty": 0.45, "time_cost": 0.45},
        ),
    ],
}


def register_track_template(goal_class: str, template: TrackTemplate) -> None:
    """Extend the track library for a goal class at runtime."""
    if goal_class not in GOAL_CLASSES:
        raise ValueError(f"unknown goal class: {goal_class}")
    _CLASS_TRACKS.setdefault(goal_class, []).append(template)


# --- Project context and evidence collectors ---


@dataclass
class ProjectContext:
    """Cheap deterministic snapshot of local project state."""

    root: Path
    py_files: int = 0
    test_files: int = 0
    doc_files: int = 0
    todo_count: int = 0

    @classmethod
    def scan(cls, root: Path, *, max_files: int = 2000) -> ProjectContext:
        ctx = cls(root=root)
        seen = 0
        for path in root.rglob("*"):
            if seen >= max_files:
                break
            parts = path.parts
            if any(p in (".git", ".venv", "node_modules", "__pycache__") for p in parts):
                continue
            if not path.is_file():
                continue
            seen += 1
            if path.suffix == ".py":
                ctx.py_files += 1
                if path.name.startswith("test_") or "tests" in parts:
                    ctx.test_files += 1
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    ctx.todo_count += text.count("TODO") + text.count("FIXME")
                except OSError:
                    continue
            elif path.suffix in (".md", ".rst"):
                ctx.doc_files += 1
        return ctx


class EvidenceCollector(Protocol):
    """Pluggable evidence source. v0 ships local-first collectors only;
    a web research collector can implement this same interface later."""

    source_type: str

    def collect(
        self, track: OpportunityTrack, *, context: ProjectContext
    ) -> list[OpportunityEvidence]: ...


class RepoEvidenceCollector:
    """Evidence from repo structure: file counts, test ratio, TODO markers."""

    source_type = "repo_file"

    def collect(
        self, track: OpportunityTrack, *, context: ProjectContext
    ) -> list[OpportunityEvidence]:
        items: list[OpportunityEvidence] = []
        if track.track_type == "tests" and context.py_files:
            ratio = context.test_files / max(context.py_files, 1)
            items.append(
                OpportunityEvidence(
                    evidence_id=_uid("ev"),
                    track_id=track.track_id,
                    source_type="tests",
                    reference=str(context.root),
                    summary=(
                        f"{context.test_files} test files for {context.py_files} "
                        f"python files (ratio {ratio:.2f})"
                    ),
                    strength=min(1.0, 0.9 - ratio * 0.5) if ratio < 1 else 0.3,
                    collected_by=type(self).__name__,
                )
            )
        if track.track_type == "docs":
            strength = 0.7 if context.doc_files < max(context.py_files // 4, 1) else 0.35
            items.append(
                OpportunityEvidence(
                    evidence_id=_uid("ev"),
                    track_id=track.track_id,
                    source_type="docs",
                    reference=str(context.root),
                    summary=f"{context.doc_files} doc files alongside {context.py_files} modules",
                    strength=strength,
                    collected_by=type(self).__name__,
                )
            )
        if track.track_type == "triage" and context.todo_count:
            items.append(
                OpportunityEvidence(
                    evidence_id=_uid("ev"),
                    track_id=track.track_id,
                    source_type="repo_file",
                    reference=str(context.root),
                    summary=f"{context.todo_count} TODO/FIXME markers in tree",
                    strength=min(1.0, 0.3 + context.todo_count * 0.02),
                    collected_by=type(self).__name__,
                )
            )
        return items


class ReceiptEvidenceCollector:
    """Evidence from the receipt-backed execution history in the ledger."""

    source_type = "receipt"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def collect(
        self, track: OpportunityTrack, *, context: ProjectContext
    ) -> list[OpportunityEvidence]:
        try:
            from opencobalt.execution.store import ExecutionStore

            receipts = ExecutionStore(self.db_path).list_receipts(limit=50)
        except Exception:
            return []
        if not receipts:
            return []
        verified = sum(1 for r in receipts if r.verification_status == "verified")
        return [
            OpportunityEvidence(
                evidence_id=_uid("ev"),
                track_id=track.track_id,
                source_type="receipt",
                reference=f"ledger:{len(receipts)} receipts",
                summary=f"{verified}/{len(receipts)} recent receipts verified",
                strength=0.3 + 0.6 * (verified / len(receipts)),
                collected_by=type(self).__name__,
            )
        ]


class RouteHistoryEvidenceCollector:
    """Evidence from recorded route decisions (what work actually happens)."""

    source_type = "route_history"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def collect(
        self, track: OpportunityTrack, *, context: ProjectContext
    ) -> list[OpportunityEvidence]:
        try:
            from .ledger import Ledger

            decisions = Ledger(self.db_path).list_route_decisions(limit=50)
        except Exception:
            return []
        if not decisions:
            return []
        return [
            OpportunityEvidence(
                evidence_id=_uid("ev"),
                track_id=track.track_id,
                source_type="route_history",
                reference=f"ledger:{len(decisions)} route decisions",
                summary=f"{len(decisions)} recent route decisions inform this track",
                strength=min(1.0, 0.3 + len(decisions) * 0.01),
                collected_by=type(self).__name__,
            )
        ]


# --- Scoring ---


def score_track(
    track: OpportunityTrack, evidence: list[OpportunityEvidence]
) -> OpportunityScore:
    """Score one track. Transparent: every contribution is one line.

    Dimension values start from the track's priors. evidence_strength is
    computed from attached evidence, and verification_quality gets a small
    boost when receipt-backed evidence is present.
    """
    dims = {dim: 0.5 for dim in SCORE_DIMENSIONS}
    dims.update({k: v for k, v in track.priors.items() if k in dims})

    if evidence:
        dims["evidence_strength"] = sum(e.strength for e in evidence) / len(evidence)
        if any(e.source_type == "receipt" for e in evidence):
            dims["verification_quality"] = min(1.0, dims["verification_quality"] + 0.15)
    else:
        dims["evidence_strength"] = 0.2

    explanation: list[str] = []
    total = 0.0
    for dim, weight in SCORE_WEIGHTS.items():
        contribution = dims[dim] * weight
        total += contribution
        explanation.append(f"{dim}={dims[dim]:.2f} x {weight:+.2f} -> {contribution:+.3f}")
    for dim, weight in PENALTY_WEIGHTS.items():
        contribution = dims[dim] * weight
        total -= contribution
        explanation.append(f"{dim}={dims[dim]:.2f} x -{weight:.2f} -> {-contribution:+.3f}")

    total = max(0.0, min(1.0, round(total, 4)))
    explanation.append(f"total={total:.4f} (clamped 0..1)")
    return OpportunityScore(
        track_id=track.track_id,
        dimensions=dims,
        total=total,
        explanation=explanation,
    )


# --- Delegation planning ---

_OPPORTUNITY_SPECS: list[SubagentSpec] = [
    SubagentSpec(
        agent_id="strategist",
        specialization="opportunity track ownership and sequencing",
        tier="executive",
        tool="claude-code",
        task_types=["strategy"],
        prompt_template="Own this opportunity track end to end: {task}",
        capabilities=["planning"],
        risk_ceiling="yellow",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="researcher",
        specialization="local evidence gathering for opportunity tracks",
        tier="executive",
        tool="gemini-cli",
        task_types=["research"],
        prompt_template="Gather local evidence for: {task}",
        capabilities=["research"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="implementer",
        specialization="bounded local implementation of approved steps",
        tier="executive",
        tool="claude-code",
        task_types=["impl"],
        prompt_template="Implement, within policy bounds: {task}",
        capabilities=["code-edit"],
        risk_ceiling="yellow",
        permission_scope="write",
        output_contract="artifact",
    ),
    SubagentSpec(
        agent_id="test-writer",
        specialization="test authoring for opportunity deliverables",
        tier="manager",
        tool="codex-cli",
        task_types=["tests"],
        prompt_template="Write pytest coverage for: {task}",
        capabilities=["tests"],
        risk_ceiling="yellow",
        permission_scope="write",
        output_contract="artifact",
    ),
    SubagentSpec(
        agent_id="security-auditor",
        specialization="authorized local security and policy review",
        tier="executive",
        tool="claude-code",
        task_types=["security"],
        prompt_template="Audit, within authorized local scope: {task}",
        capabilities=["security", "review"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="docs-editor",
        specialization="documentation drafting and editing",
        tier="manager",
        tool="codex-cli",
        task_types=["docs"],
        prompt_template="Draft or edit documentation for: {task}",
        capabilities=["docs"],
        risk_ceiling="yellow",
        permission_scope="write",
        output_contract="artifact",
    ),
]


def opportunity_registry() -> SubagentRegistry:
    """Default registry plus the opportunity-specific roles."""
    registry = SubagentRegistry()
    for spec in _OPPORTUNITY_SPECS:
        if registry.get(spec.agent_id) is None:
            registry.register(spec)
    return registry


_TRACK_SPECIALISTS: dict[str, list[str]] = {
    "docs": ["docs-editor"],
    "tests": ["test-writer", "implementer"],
    "triage": ["failure-triager", "test-writer"],
    "security": ["security-auditor", "receipt-verifier"],
    "design": ["design-reviewer", "implementer"],
    "cost": ["cost-optimizer"],
    "routing": ["cost-optimizer", "implementer"],
    "benchmark": ["benchmark-runner", "test-writer"],
    "product": ["implementer", "design-reviewer"],
    "integration": ["implementer", "test-writer"],
    "refactor": ["refactorer", "test-writer"],
    "research": ["researcher"],
}


def build_delegation_tree(
    track: OpportunityTrack,
    *,
    registry: SubagentRegistry | None = None,
    max_depth: int = 3,
) -> DelegationPlan:
    """Map one track into a nested delegation tree.

    strategist (root) -> researcher -> specialists, with a receipt-verifier
    reporting to the strategist. Depth, risk ceilings, and permission scopes
    are enforced by DelegationPlan at construction time. Planning only.
    """
    registry = registry or opportunity_registry()
    plan = DelegationPlan(track.description or track.name, registry=registry, max_depth=max_depth)
    root = plan.add_root("strategist", f"Own opportunity track: {track.name}")
    researcher = plan.delegate(
        root.node_id, "researcher", f"Collect local evidence for: {track.name}"
    )
    for agent_id in _TRACK_SPECIALISTS.get(track.track_type, ["implementer"]):
        spec = registry.get(agent_id)
        if spec is None:
            continue
        plan.delegate(
            researcher.node_id,
            agent_id,
            f"{track.name}: produce {spec.output_contract} within policy bounds",
        )
    plan.delegate(
        root.node_id, "receipt-verifier", f"Verify receipts produced for: {track.name}"
    )
    return plan


_TRACK_STEPS: dict[str, list[str]] = {
    "docs": ["draft documentation update", "review documentation draft"],
    "tests": ["write tests for weakest module", "run pytest suite locally"],
    "triage": ["list TODO/FIXME hotspots", "file triage notes per hotspot"],
    "security": ["review policy gate coverage", "scan repo with public-check"],
    "design": ["review TUI output against DESIGN.md", "propose layout patch"],
    "cost": ["analyze route history for spend", "propose tier shift"],
    "routing": ["analyze outcome history", "propose routing keyword update"],
    "benchmark": ["design local benchmark", "record baseline scores"],
    "product": ["map highest-traffic CLI flows", "propose polish patch"],
    "integration": ["survey installed local tools", "propose adapter plan"],
    "refactor": ["identify largest modules", "propose behavior-safe refactor"],
    "research": ["summarize local prior art", "write findings note"],
}


def build_opportunity_plan(
    track: OpportunityTrack,
    goal: OpportunityGoal,
    *,
    registry: SubagentRegistry | None = None,
    max_depth: int = 3,
) -> OpportunityPlan:
    """Build the non-executing, policy-aware plan for one track."""
    delegation = build_delegation_tree(track, registry=registry, max_depth=max_depth)
    steps: list[dict[str, Any]] = []
    worst = "green"
    for description in _TRACK_STEPS.get(track.track_type, ["analyze track locally"]):
        risk = classify_risk(description)
        worst = max_risk(worst, risk)
        steps.append(
            {
                "description": description,
                "risk_level": risk,
                "approval_required": risk in ("red", "black"),
            }
        )
    return OpportunityPlan(
        plan_id=_uid("oplan"),
        track_id=track.track_id,
        goal_id=goal.goal_id,
        delegation=delegation.to_dict(),
        steps=steps,
        risk_level=worst,
        approval_state="not_required" if worst == "green" else "pending",
        executed=False,
    )


# --- Engine ---


class OpportunityEngine:
    """Runs the full supervised opportunity pipeline automatically.

    brainstorm() is the autopilot entry point: classify, decompose, gather
    evidence, score, plan the top tracks, and report -- emitting structured
    events throughout. It never executes anything; execution stays behind
    the existing policy gate.
    """

    def __init__(
        self,
        *,
        root: Path | None = None,
        db_path: Path | None = None,
        events_path: Path | None = None,
        registry: SubagentRegistry | None = None,
        collectors: list[EvidenceCollector] | None = None,
        max_depth: int = 3,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.root = root or Path(".")
        self.db_path = db_path
        self.events_path = events_path or _DEFAULT_EVENTS_PATH
        self.registry = registry or opportunity_registry()
        self.collectors: list[EvidenceCollector] = (
            collectors
            if collectors is not None
            else [
                RepoEvidenceCollector(),
                ReceiptEvidenceCollector(db_path),
                RouteHistoryEvidenceCollector(db_path),
            ]
        )
        self.max_depth = max_depth
        self.event_sink = event_sink
        self.events: list[dict[str, Any]] = []

    # --- Pipeline stages ---

    def brainstorm(self, goal_text: str, *, top_n: int = 3, plan: bool = True) -> OpportunityRun:
        """Full autonomous pipeline for one goal. Returns the persisted run."""
        goal = OpportunityGoal(
            goal_id=_uid("goal"), text=goal_text, goal_class=classify_goal(goal_text)
        )
        run = OpportunityRun(run_id=_uid("orun"), goal=goal)
        self._emit(
            EVENT_GOAL_RECEIVED, goal.goal_id,
            f"goal received ({goal.goal_class}): {goal_text[:80]}",
            run_id=run.run_id, goal_class=goal.goal_class,
        )

        context = ProjectContext.scan(self.root)
        run.tracks = self.generate_tracks(goal, run_id=run.run_id)

        for track in run.tracks:
            evidence = self.collect_evidence(track, context=context, run_id=run.run_id)
            run.evidence.extend(evidence)
            hypothesis = OpportunityHypothesis(
                hypothesis_id=_uid("hyp"),
                track_id=track.track_id,
                statement=f"Pursuing '{track.name}' measurably advances: {goal.text[:80]}",
            )
            track.hypothesis_ids.append(hypothesis.hypothesis_id)
            run.hypotheses.append(hypothesis)

            score = score_track(track, evidence)
            track.status = "scored"
            run.scores.append(score)
            self._emit(
                EVENT_SCORED, track.track_id,
                f"scored {track.name}: {score.total:.3f}",
                run_id=run.run_id, total=score.total,
            )

        if plan:
            for track in self.rank_tracks(run)[:top_n]:
                self.plan_track(run, track.track_id)  # appends to run.plans

        run.report = self.build_report(run)
        self._persist(run)
        return run

    def generate_tracks(self, goal: OpportunityGoal, *, run_id: str) -> list[OpportunityTrack]:
        templates = list(_BASE_TRACKS) + list(_CLASS_TRACKS.get(goal.goal_class, []))
        tracks: list[OpportunityTrack] = []
        for template in templates:
            track = OpportunityTrack(
                track_id=_uid("otrk"),
                goal_id=goal.goal_id,
                name=template.name,
                track_type=template.track_type,
                description=template.description,
                priors=dict(template.priors),
            )
            tracks.append(track)
            self._emit(
                EVENT_TRACK_CREATED, track.track_id,
                f"track created: {track.name} ({track.track_type})",
                run_id=run_id, goal_id=goal.goal_id,
            )
        return tracks

    def collect_evidence(
        self,
        track: OpportunityTrack,
        *,
        context: ProjectContext,
        run_id: str,
    ) -> list[OpportunityEvidence]:
        collected: list[OpportunityEvidence] = []
        for collector in self.collectors:
            try:
                items = collector.collect(track, context=context)
            except Exception:
                continue  # a broken collector never blocks the run
            for item in items:
                track.evidence_ids.append(item.evidence_id)
                collected.append(item)
                self._emit(
                    EVENT_EVIDENCE_ATTACHED, item.evidence_id,
                    f"evidence attached to {track.name}: {item.summary[:80]}",
                    run_id=run_id, track_id=track.track_id,
                    source_type=item.source_type, strength=item.strength,
                )
        return collected

    def attach_note(
        self, run: OpportunityRun, track_id: str, note: str, *, strength: float = 0.5
    ) -> OpportunityEvidence:
        """Manually attach a note as evidence and rescore the track."""
        track = run.get_track(track_id)
        if track is None:
            raise KeyError(f"unknown track: {track_id}")
        evidence = OpportunityEvidence(
            evidence_id=_uid("ev"),
            track_id=track.track_id,
            source_type="note",
            reference="manual",
            summary=note,
            strength=strength,
            collected_by="human",
        )
        track.evidence_ids.append(evidence.evidence_id)
        run.evidence.append(evidence)
        self._emit(
            EVENT_EVIDENCE_ATTACHED, evidence.evidence_id,
            f"note attached to {track.name}: {note[:80]}",
            run_id=run.run_id, track_id=track.track_id, source_type="note",
        )
        self.rescore(run)
        return evidence

    def rescore(self, run: OpportunityRun) -> list[OpportunityScore]:
        """Recompute every track score from current evidence."""
        run.scores = []
        for track in run.tracks:
            evidence = [e for e in run.evidence if e.track_id == track.track_id]
            score = score_track(track, evidence)
            run.scores.append(score)
            self._emit(
                EVENT_SCORED, track.track_id,
                f"rescored {track.name}: {score.total:.3f}",
                run_id=run.run_id, total=score.total,
            )
        run.report = self.build_report(run)
        self._persist(run)
        return run.scores

    def rank_tracks(self, run: OpportunityRun) -> list[OpportunityTrack]:
        totals = {s.track_id: s.total for s in run.scores}
        return sorted(
            run.tracks, key=lambda t: totals.get(t.track_id, 0.0), reverse=True
        )

    def plan_track(
        self, run: OpportunityRun, track_id: str, *, new: bool = False
    ) -> OpportunityPlan:
        """Build (and persist) the non-executing plan for one track.

        Idempotent by default: if the track already has a plan in this run,
        it is reused. Pass new=True to build a replacement plan.
        """
        track = run.get_track(track_id)
        if track is None:
            raise KeyError(f"unknown track: {track_id}")
        if not new and track.plan_id:
            for existing in run.plans:
                if existing.plan_id == track.plan_id:
                    return existing
        plan = build_opportunity_plan(
            track, run.goal, registry=self.registry, max_depth=self.max_depth
        )
        track.plan_id = plan.plan_id
        track.status = "planned"
        run.plans.append(plan)
        self._emit(
            EVENT_PLAN_CREATED, plan.plan_id,
            f"plan created for {track.name} (risk {plan.risk_level}, "
            f"approval {plan.approval_state}, not executed)",
            run_id=run.run_id, track_id=track.track_id,
            risk_level=plan.risk_level, approval_state=plan.approval_state,
        )
        self._persist(run)
        return plan

    def build_report(self, run: OpportunityRun) -> OpportunityReport:
        ranked = []
        for track in self.rank_tracks(run):
            score = run.score_for(track.track_id)
            ranked.append(
                {
                    "track_id": track.track_id,
                    "name": track.name,
                    "track_type": track.track_type,
                    "status": track.status,
                    "total": score.total if score else 0.0,
                    "evidence_count": len(track.evidence_ids),
                    "plan_id": track.plan_id,
                }
            )
        next_actions = []
        for entry in ranked[:3]:
            if entry["plan_id"]:
                next_actions.append(
                    f"Review plan {entry['plan_id'][:14]} for '{entry['name']}' and "
                    "approve execution through the policy gate."
                )
            else:
                next_actions.append(
                    f"Run: opencobalt opportunities plan {entry['track_id'][:14]}"
                )
        report = OpportunityReport(
            run_id=run.run_id,
            goal_text=run.goal.text,
            goal_class=run.goal.goal_class,
            ranked=ranked,
            next_actions=next_actions,
        )
        self._emit(
            EVENT_REPORT_CREATED, run.run_id,
            f"report created: {len(ranked)} tracks ranked",
            run_id=run.run_id, track_count=len(ranked),
        )
        return report

    # --- Persistence and events ---

    def _persist(self, run: OpportunityRun) -> None:
        try:
            from .opportunity_store import OpportunityStore

            OpportunityStore(self.db_path).save_run(run)
        except Exception:
            pass  # persistence is best-effort; the run object is the result

    def _emit(self, event_type: str, subject_id: str, message: str, **metadata: Any) -> None:
        event = make_event(
            event_type=event_type,
            subject_type="opportunity",
            subject_id=subject_id,
            message=message,
            source="opportunity-engine",
            metadata=metadata,
        )
        self.events.append(event)
        try:
            append_event(event, path=self.events_path)
        except OSError:
            pass
        if self.event_sink is not None:
            self.event_sink(event)
