"""Evolve Mode v0: supervised self-improvement missions.

OpenCobalt working on itself, bounded and inspectable:

  propose -> score -> approve -> execute -> verify -> receipt -> explain -> learn

This is not a free-running self-replicating agent. An evolve mission reads
the local repo and roadmap docs, generates candidate self-improvements,
scores them transparently (wrapperware escape value rewards features that
connect subsystems into the vertical loop), plans a subagent analysis tree,
and then reuses the existing machinery for everything that matters:

  - Candidates ARE opportunity tracks inside a mission-owned opportunity
    run, so the Approval Bridge, policy-gated execution, receipts,
    provenance, and outcome history all work on them unchanged.
  - Approval goes through core.approval_bridge. Nothing here executes.
  - Roadmap edits are proposals only; writing docs/ROADMAP.md requires an
    explicit --write flag (and even then appends a marked section).

Hard boundaries in v0: no self-replication, no background persistence, no
auto-merge, no auto-push, no network calls, no credential or spend paths.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .delegation import DelegationPlan
from .events import append_event, make_event
from .opportunity_engine import (
    OpportunityEvidence,
    OpportunityGoal,
    OpportunityPlan,
    OpportunityRun,
    OpportunityTrack,
    ProjectContext,
    opportunity_registry,
    score_track,
)
from .subagent_registry import SubagentRegistry, SubagentSpec, with_context_sentinel

EVOLVE_STATUS = (
    "proposed",
    "scored",
    "approval_pending",
    "approved",
    "executing",
    "verified",
    "failed",
    "abandoned",
)

CANDIDATE_TYPES = (
    "tiny_polish",
    "vertical_loop",
    "adapter_integration",
    "safety_provenance",
    "demo_ux",
    "research_moonshot",
)

EVENT_MISSION_STARTED = "evolve.mission_started"
EVENT_ROADMAP_LOADED = "evolve.roadmap_loaded"
EVENT_CANDIDATE_CREATED = "evolve.candidate_created"
EVENT_CANDIDATE_SCORED = "evolve.candidate_scored"
EVENT_DELEGATION_CREATED = "evolve.delegation_created"
EVENT_APPROVAL_CREATED = "evolve.approval_created"
EVENT_EXECUTION_REQUESTED = "evolve.execution_requested"
EVENT_RECEIPT_LINKED = "evolve.receipt_linked"
EVENT_OUTCOME_RECORDED = "evolve.outcome_recorded"
EVENT_REPORT_CREATED = "evolve.report_created"

_DEFAULT_DB = Path(".opencobalt") / "ledger.db"
_DEFAULT_EVENTS_PATH = Path(".opencobalt") / "events" / "evolve.jsonl"

ROADMAP_DOCS = (
    "docs/ROADMAP.md",
    "docs/OPPORTUNITY_ENGINE.md",
    "docs/APPROVAL_BRIDGE.md",
    "docs/EXECUTION_LAYER.md",
    "docs/SUBAGENTS.md",
    "README.md",
)

# Transparent score weights. Wrapperware escape value carries the largest
# positive weight on purpose: features that close the vertical loop or
# create proprietary local evidence beat features that wrap another tool.
SELF_SCORE_WEIGHTS: dict[str, float] = {
    "user_value": 0.14,
    "implementation_feasibility": 0.12,
    "testability": 0.10,
    "demo_impact": 0.10,
    "novelty": 0.08,
    "provenance_value": 0.10,
    "autonomy_leverage": 0.08,
    "wrapperware_escape_value": 0.16,
}
SELF_SCORE_PENALTIES: dict[str, float] = {
    "safety_risk": 0.08,
    "time_cost": 0.04,
}
SELF_SCORE_DIMENSIONS = tuple(SELF_SCORE_WEIGHTS) + tuple(SELF_SCORE_PENALTIES)

# Base wrapperware escape by candidate type: connecting subsystems scores
# high; adding another runtime wrapper scores low.
_ESCAPE_BASE = {
    "vertical_loop": 0.9,
    "safety_provenance": 0.75,
    "research_moonshot": 0.55,
    "demo_ux": 0.45,
    "tiny_polish": 0.35,
    "adapter_integration": 0.25,
}
_ESCAPE_KEYWORDS = (
    "loop", "receipt", "provenance", "approval", "outcome", "connect",
    "lineage", "verify", "evidence", "score",
)

_TYPE_TO_TRACK_TYPE = {
    "tiny_polish": "triage",
    "vertical_loop": "strategy",
    "adapter_integration": "integration",
    "safety_provenance": "security",
    "demo_ux": "design",
    "research_moonshot": "research",
}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# --- Models ---


@dataclass
class EvolvePolicy:
    """What an evolve mission may do without further human action.

    Roadmap writes and pushes are off by default and stay off in v0
    unless the human passes the explicit CLI flags. Network collectors
    do not exist yet; the flag is here so a future collector ships
    disabled by default.
    """

    allow_roadmap_write: bool = False
    allow_push: bool = False
    network_collectors_enabled: bool = False
    max_candidates: int = 6
    plan_top_n: int = 3


@dataclass
class SelfImprovementScore:
    """Explainable self-improvement score for one candidate."""

    candidate_id: str
    dimensions: dict[str, float]
    total: float
    explanation: list[str] = field(default_factory=list)
    scored_at: str = field(default_factory=_now_iso)


@dataclass
class RoadmapProposal:
    """A structured roadmap idea. Proposals never edit docs by themselves."""

    proposal_id: str
    mission_id: str
    proposal_type: str  # one of CANDIDATE_TYPES
    title: str
    why_it_matters: str = ""
    repo_fit: str = ""
    likely_files: list[str] = field(default_factory=list)
    risk_level: str = "green"
    tests: str = ""
    demo_impact: str = ""
    wrapperware_escape_value: float = 0.5
    status: str = "proposed"  # proposed / written / rejected
    created_at: str = field(default_factory=_now_iso)


@dataclass
class EvolveCandidate:
    """One candidate self-improvement. Backed by an opportunity track."""

    candidate_id: str
    mission_id: str
    title: str
    candidate_type: str
    description: str = ""
    likely_files: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    track_id: str | None = None
    opportunity_plan_id: str | None = None
    approval_request_id: str | None = None
    execution_plan_ids: list[str] = field(default_factory=list)
    receipt_ids: list[str] = field(default_factory=list)
    outcome_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    risk_level: str = "green"
    status: str = "proposed"
    score: SelfImprovementScore | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def touch(self) -> None:
        self.updated_at = _now_iso()


@dataclass
class EvolveCycle:
    """One pass through propose -> score -> plan inside a mission."""

    cycle_id: str
    mission_id: str
    cycle_number: int
    summary: str = ""
    started_at: str = field(default_factory=_now_iso)
    finished_at: str | None = None


@dataclass
class EvolveReport:
    """Ranked candidates plus the exact next commands."""

    mission_id: str
    goal: str
    ranked: list[dict[str, Any]] = field(default_factory=list)
    next_commands: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=_now_iso)


@dataclass
class EvolveMission:
    """One supervised self-improvement mission."""

    mission_id: str
    goal: str
    branch_name: str = ""
    base_ref: str = ""
    cycle_number: int = 1
    run_id: str | None = None  # backing opportunity run
    status: str = "proposed"
    delegation: dict[str, Any] = field(default_factory=dict)
    roadmap_proposals: list[RoadmapProposal] = field(default_factory=list)
    cycles: list[EvolveCycle] = field(default_factory=list)
    report: EvolveReport | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvolveMission:
        data = dict(data)
        data["roadmap_proposals"] = [
            RoadmapProposal(**p) for p in data.get("roadmap_proposals", [])
        ]
        data["cycles"] = [EvolveCycle(**c) for c in data.get("cycles", [])]
        report = data.get("report")
        data["report"] = EvolveReport(**report) if report else None
        return cls(**data)


@dataclass
class EvolveResult:
    """Everything one evolve invocation produced."""

    mission: EvolveMission
    candidates: list[EvolveCandidate]
    report: EvolveReport


# --- Persistence ---

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evolve_missions (
    mission_id   TEXT PRIMARY KEY,
    goal         TEXT NOT NULL,
    status       TEXT NOT NULL,
    run_id       TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    mission_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evolve_candidates (
    candidate_id        TEXT PRIMARY KEY,
    mission_id          TEXT NOT NULL,
    track_id            TEXT,
    title               TEXT NOT NULL,
    candidate_type      TEXT NOT NULL,
    status              TEXT NOT NULL,
    score_total         REAL,
    risk_level          TEXT NOT NULL,
    approval_request_id TEXT,
    updated_at          TEXT NOT NULL,
    candidate_json      TEXT NOT NULL
);
"""


class EvolveStore:
    """SQLite persistence for evolve missions and candidates."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or _DEFAULT_DB).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self):
        from opencobalt.core.sqlite import closing_sqlite

        return closing_sqlite(self.db_path)

    def save_mission(self, mission: EvolveMission) -> None:
        mission.updated_at = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO evolve_missions VALUES (?,?,?,?,?,?,?)",
                (
                    mission.mission_id,
                    mission.goal,
                    mission.status,
                    mission.run_id,
                    mission.created_at,
                    mission.updated_at,
                    json.dumps(mission.to_dict(), sort_keys=True),
                ),
            )

    def save_candidate(self, candidate: EvolveCandidate) -> None:
        candidate.touch()
        data = asdict(candidate)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO evolve_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    candidate.candidate_id,
                    candidate.mission_id,
                    candidate.track_id,
                    candidate.title,
                    candidate.candidate_type,
                    candidate.status,
                    candidate.score.total if candidate.score else None,
                    candidate.risk_level,
                    candidate.approval_request_id,
                    candidate.updated_at,
                    json.dumps(data, sort_keys=True),
                ),
            )

    def get_mission(self, mission_id: str) -> EvolveMission | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT mission_json FROM evolve_missions "
                "WHERE mission_id = ? OR mission_id LIKE ?",
                (mission_id, f"{mission_id}%"),
            ).fetchone()
        return EvolveMission.from_dict(json.loads(row["mission_json"])) if row else None

    def latest_mission(self) -> EvolveMission | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT mission_json FROM evolve_missions ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return EvolveMission.from_dict(json.loads(row["mission_json"])) if row else None

    def list_missions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT mission_id, goal, status, run_id, created_at "
                "FROM evolve_missions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_candidate(self, candidate_id: str) -> EvolveCandidate | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT candidate_json FROM evolve_candidates "
                "WHERE candidate_id = ? OR candidate_id LIKE ?",
                (candidate_id, f"{candidate_id}%"),
            ).fetchone()
        return _decode_candidate(row) if row else None

    def find_candidate_for_track(self, track_id: str) -> EvolveCandidate | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT candidate_json FROM evolve_candidates "
                "WHERE track_id = ? OR track_id LIKE ?",
                (track_id, f"{track_id}%"),
            ).fetchone()
        return _decode_candidate(row) if row else None

    def list_candidates(self, mission_id: str) -> list[EvolveCandidate]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT candidate_json FROM evolve_candidates "
                "WHERE mission_id = ? ORDER BY score_total DESC",
                (mission_id,),
            ).fetchall()
        return [_decode_candidate(r) for r in rows]


def _decode_candidate(row: sqlite3.Row) -> EvolveCandidate:
    data = json.loads(row["candidate_json"])
    score = data.pop("score", None)
    candidate = EvolveCandidate(**data)
    if score:
        candidate.score = SelfImprovementScore(**score)
    return candidate


# --- Scoring ---


def wrapperware_escape_value(candidate_type: str, description: str) -> float:
    """0..1. Connecting subsystems into the vertical loop scores high;
    wrapping yet another runtime scores low."""
    base = _ESCAPE_BASE.get(candidate_type, 0.4)
    text = description.lower()
    boost = sum(0.05 for kw in _ESCAPE_KEYWORDS if kw in text)
    return max(0.0, min(1.0, base + min(boost, 0.25)))


def score_candidate(
    candidate: EvolveCandidate, *, priors: dict[str, float] | None = None
) -> SelfImprovementScore:
    """Score one candidate. Every contribution is one explanation line."""
    dims = {dim: 0.5 for dim in SELF_SCORE_DIMENSIONS}
    dims.update({k: v for k, v in (priors or {}).items() if k in dims})
    dims["wrapperware_escape_value"] = wrapperware_escape_value(
        candidate.candidate_type, f"{candidate.title} {candidate.description}"
    )

    explanation: list[str] = []
    total = 0.0
    for dim, weight in SELF_SCORE_WEIGHTS.items():
        contribution = dims[dim] * weight
        total += contribution
        explanation.append(f"{dim}={dims[dim]:.2f} x {weight:+.2f} -> {contribution:+.3f}")
    for dim, weight in SELF_SCORE_PENALTIES.items():
        contribution = dims[dim] * weight
        total -= contribution
        explanation.append(f"{dim}={dims[dim]:.2f} x -{weight:.2f} -> {-contribution:+.3f}")
    total = max(0.0, min(1.0, round(total, 4)))
    explanation.append(f"total={total:.4f} (clamped 0..1)")
    return SelfImprovementScore(
        candidate_id=candidate.candidate_id,
        dimensions=dims,
        total=total,
        explanation=explanation,
    )


# --- Roadmap reading and proposals ---


@dataclass
class RoadmapSnapshot:
    """What the mission read from local docs. Evidence, not instruction."""

    docs_found: list[str] = field(default_factory=list)
    docs_missing: list[str] = field(default_factory=list)
    next_items: list[str] = field(default_factory=list)  # In Progress bullets


def load_roadmap_snapshot(root: Path) -> RoadmapSnapshot:
    snapshot = RoadmapSnapshot()
    for rel in ROADMAP_DOCS:
        path = root / rel
        if path.exists():
            snapshot.docs_found.append(rel)
        else:
            snapshot.docs_missing.append(rel)
    roadmap = root / "docs" / "ROADMAP.md"
    if roadmap.exists():
        text = roadmap.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"## In Progress / Next(.*?)(?:\n## |\Z)", text, re.S)
        if match:
            for line in match.group(1).splitlines():
                stripped = line.strip()
                if stripped.startswith("- ") and len(stripped) > 8:
                    snapshot.next_items.append(stripped[2:].strip())
    return snapshot


# --- Candidate generation (deterministic, local-only) ---


_BASE_CANDIDATES: list[dict[str, Any]] = [
    {
        "title": "close an open vertical-loop gap from the roadmap",
        "candidate_type": "vertical_loop",
        "description": (
            "connect existing subsystems (opportunity, approval, execution, "
            "receipt, provenance, outcome) one step further into the loop"
        ),
        "priors": {"user_value": 0.8, "implementation_feasibility": 0.65,
                   "testability": 0.7, "demo_impact": 0.7, "novelty": 0.6,
                   "provenance_value": 0.8, "autonomy_leverage": 0.7,
                   "safety_risk": 0.25, "time_cost": 0.5},
        "steps": [
            "draft implementation note for the chosen loop gap",
            "write tests for the loop connection",
            "patch docs with the loop change",
        ],
    },
    {
        "title": "deepen receipt verification coverage",
        "candidate_type": "safety_provenance",
        "description": "strengthen receipt and artifact verification paths with evidence",
        "priors": {"user_value": 0.6, "implementation_feasibility": 0.75,
                   "testability": 0.85, "demo_impact": 0.5, "novelty": 0.4,
                   "provenance_value": 0.9, "autonomy_leverage": 0.5,
                   "safety_risk": 0.15, "time_cost": 0.35},
        "steps": [
            "audit receipt verification gaps",
            "write tests for verification edge cases",
        ],
    },
    {
        "title": "raise test coverage on weakest modules",
        "candidate_type": "tiny_polish",
        "description": "add tests where module-to-test ratio is weakest",
        "priors": {"user_value": 0.55, "implementation_feasibility": 0.85,
                   "testability": 0.95, "demo_impact": 0.3, "novelty": 0.2,
                   "provenance_value": 0.4, "autonomy_leverage": 0.4,
                   "safety_risk": 0.1, "time_cost": 0.35},
        "steps": [
            "list weakest-covered modules",
            "write tests for the weakest module",
        ],
    },
    {
        "title": "polish shell and status output for the control plane demo",
        "candidate_type": "demo_ux",
        "description": "tighten shell, status, and report output for the demo loop",
        "priors": {"user_value": 0.6, "implementation_feasibility": 0.8,
                   "testability": 0.6, "demo_impact": 0.85, "novelty": 0.4,
                   "provenance_value": 0.35, "autonomy_leverage": 0.35,
                   "safety_risk": 0.15, "time_cost": 0.3},
        "steps": [
            "review status and shell output against DESIGN.md",
            "draft output polish note",
        ],
    },
    {
        "title": "wrap one more local runtime adapter",
        "candidate_type": "adapter_integration",
        "description": "add another runtime wrapper adapter",
        "priors": {"user_value": 0.5, "implementation_feasibility": 0.7,
                   "testability": 0.6, "demo_impact": 0.4, "novelty": 0.3,
                   "provenance_value": 0.3, "autonomy_leverage": 0.4,
                   "safety_risk": 0.3, "time_cost": 0.5},
        "steps": [
            "survey installed local tools",
            "draft adapter plan",
        ],
    },
    {
        "title": "design a bounded evaluator-driven discovery domain",
        "candidate_type": "research_moonshot",
        "description": (
            "use the evaluator loop on a bounded local domain with receipts "
            "and outcome evidence"
        ),
        "priors": {"user_value": 0.5, "implementation_feasibility": 0.5,
                   "testability": 0.6, "demo_impact": 0.6, "novelty": 0.8,
                   "provenance_value": 0.6, "autonomy_leverage": 0.75,
                   "safety_risk": 0.3, "time_cost": 0.6},
        "steps": [
            "pick a bounded local domain",
            "design evaluator and stop conditions",
        ],
    },
]


# --- Subagent fanout (planning only) ---

_EVOLVE_SPECS: list[SubagentSpec] = [
    SubagentSpec(
        agent_id="evolution-strategist",
        specialization="owns one evolve mission end to end",
        tier="executive",
        tool="claude-code",
        task_types=["strategy"],
        prompt_template=with_context_sentinel("Own this evolve mission: {task}"),
        capabilities=["planning"],
        risk_ceiling="yellow",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="repo-cartographer",
        specialization="maps repo structure, hotspots, and coverage",
        tier="executive",
        tool="gemini-cli",
        task_types=["research"],
        prompt_template=with_context_sentinel("Map the repo for: {task}"),
        capabilities=["research"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="roadmap-critic",
        specialization="critiques roadmap proposals for leverage and fit",
        tier="executive",
        tool="claude-code",
        task_types=["review"],
        prompt_template=with_context_sentinel("Critique roadmap proposals for: {task}"),
        capabilities=["review"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="implementation-planner",
        specialization="turns a candidate into a bounded implementation plan",
        tier="executive",
        tool="claude-code",
        task_types=["impl"],
        prompt_template=with_context_sentinel(
            "Plan implementation, within policy bounds: {task}"
        ),
        capabilities=["planning"],
        risk_ceiling="yellow",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="test-gap-finder",
        specialization="finds the tests a candidate change would need",
        tier="manager",
        tool="codex-cli",
        task_types=["tests"],
        prompt_template=with_context_sentinel("Find test gaps for: {task}"),
        capabilities=["tests"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="safety-auditor",
        specialization="audits a candidate for policy and safety impact",
        tier="executive",
        tool="claude-code",
        task_types=["security"],
        prompt_template=with_context_sentinel(
            "Audit safety impact, authorized local scope: {task}"
        ),
        capabilities=["security", "review"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="demo-designer",
        specialization="designs the demo path that proves a candidate worked",
        tier="manager",
        tool="codex-cli",
        task_types=["docs"],
        prompt_template=with_context_sentinel("Design the demo for: {task}"),
        capabilities=["docs"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
]


def evolve_registry() -> SubagentRegistry:
    """Opportunity registry plus the evolve analysis roles."""
    registry = opportunity_registry()
    for spec in _EVOLVE_SPECS:
        if registry.get(spec.agent_id) is None:
            registry.register(spec)
    return registry


def build_evolve_delegation(goal: str, *, registry: SubagentRegistry | None = None) -> DelegationPlan:
    """Analysis-only fanout. No node may execute externally."""
    registry = registry or evolve_registry()
    plan = DelegationPlan(f"evolve mission: {goal}", registry=registry, max_depth=3)
    root = plan.add_root("evolution-strategist", f"Own evolve mission: {goal}")
    plan.delegate(root.node_id, "repo-cartographer", "Map repo hotspots and coverage")
    plan.delegate(root.node_id, "roadmap-critic", "Critique roadmap proposals")
    planner = plan.delegate(
        root.node_id, "implementation-planner", "Plan top candidate implementations"
    )
    plan.delegate(planner.node_id, "test-gap-finder", "Find test gaps per candidate")
    plan.delegate(planner.node_id, "demo-designer", "Design demo per candidate")
    plan.delegate(root.node_id, "safety-auditor", "Audit candidates for safety impact")
    plan.delegate(root.node_id, "receipt-verifier", "Verify receipts produced by the mission")
    return plan


# --- Engine ---


class EvolveEngine:
    """Runs supervised self-improvement missions. Never executes anything;
    execution flows through the Approval Bridge and the policy-gated
    execution engine exactly like every other piece of work."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        db_path: Path | None = None,
        events_path: Path | None = None,
        policy: EvolvePolicy | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.root = root or Path(".")
        self.db_path = db_path
        self.events_path = events_path or _DEFAULT_EVENTS_PATH
        self.policy = policy or EvolvePolicy()
        self.event_sink = event_sink
        self.store = EvolveStore(db_path)
        self.events: list[dict[str, Any]] = []
        self._context_priors: dict[str, float] = {}

    # --- Mission lifecycle ---

    def start_mission(self, goal: str) -> EvolveResult:
        """Propose, score, plan, and report. No execution, no doc writes."""
        mission = EvolveMission(
            mission_id=_uid("emis"),
            goal=goal,
            base_ref=self._current_ref(),
        )
        self._emit(
            EVENT_MISSION_STARTED, mission.mission_id,
            f"evolve mission started: {goal[:80]}",
            goal=goal,
        )

        snapshot = load_roadmap_snapshot(self.root)
        self._emit(
            EVENT_ROADMAP_LOADED, mission.mission_id,
            f"roadmap loaded: {len(snapshot.docs_found)} doc(s), "
            f"{len(snapshot.next_items)} next item(s)",
            docs_found=snapshot.docs_found,
        )
        mission.roadmap_proposals = self._build_proposals(mission, snapshot)

        context = ProjectContext.scan(self.root)
        candidates = self._generate_candidates(mission, snapshot, context)
        for candidate in candidates:
            candidate.score = score_candidate(
                candidate, priors=self._priors_for(candidate)
            )
            candidate.status = "scored"
            self._emit(
                EVENT_CANDIDATE_SCORED, candidate.candidate_id,
                f"candidate scored {candidate.score.total:.3f}: {candidate.title[:60]}",
                mission_id=mission.mission_id, total=candidate.score.total,
            )

        delegation = build_evolve_delegation(goal)
        mission.delegation = delegation.to_dict()
        self._emit(
            EVENT_DELEGATION_CREATED, delegation.plan_id,
            f"delegation tree planned ({len(delegation.nodes)} node(s), analysis only)",
            mission_id=mission.mission_id,
        )

        # Back the mission with an opportunity run so approvals, execution,
        # receipts, provenance, and outcomes work on candidates unchanged.
        run = self._build_opportunity_run(mission, candidates, snapshot)
        mission.run_id = run.run_id

        mission.cycles.append(
            EvolveCycle(
                cycle_id=_uid("ecyc"),
                mission_id=mission.mission_id,
                cycle_number=mission.cycle_number,
                summary=f"{len(candidates)} candidate(s) proposed and scored",
                finished_at=_now_iso(),
            )
        )
        mission.status = "scored"
        report = self._build_report(mission, candidates)
        mission.report = report
        self._persist(mission, candidates, run)
        self._emit(
            EVENT_REPORT_CREATED, mission.mission_id,
            f"report created: {len(report.ranked)} candidate(s) ranked",
            mission_id=mission.mission_id,
        )
        return EvolveResult(mission=mission, candidates=candidates, report=report)

    # --- Internals ---

    def _current_ref(self) -> str:
        head = self.root / ".git" / "HEAD"
        try:
            return head.read_text(encoding="utf-8").strip()[:80]
        except OSError:
            return ""

    def _build_proposals(
        self, mission: EvolveMission, snapshot: RoadmapSnapshot
    ) -> list[RoadmapProposal]:
        proposals: list[RoadmapProposal] = []
        for item in snapshot.next_items[:8]:
            proposals.append(
                RoadmapProposal(
                    proposal_id=_uid("eprop"),
                    mission_id=mission.mission_id,
                    proposal_type="vertical_loop",
                    title=item[:90],
                    why_it_matters="already named on the roadmap as in-progress work",
                    repo_fit="extends existing subsystems; no new framework",
                    risk_level="green",
                    tests="unit tests per the repo's tmp_path isolation pattern",
                    demo_impact="extends the supervised loop demo",
                    wrapperware_escape_value=wrapperware_escape_value(
                        "vertical_loop", item
                    ),
                )
            )
        return proposals

    def _generate_candidates(
        self,
        mission: EvolveMission,
        snapshot: RoadmapSnapshot,
        context: ProjectContext,
    ) -> list[EvolveCandidate]:
        candidates: list[EvolveCandidate] = []
        # Roadmap-derived candidates first: the repo already voted for them.
        for item in snapshot.next_items[: self.policy.max_candidates // 2]:
            candidates.append(
                EvolveCandidate(
                    candidate_id=_uid("ecand"),
                    mission_id=mission.mission_id,
                    title=item[:90],
                    candidate_type="vertical_loop",
                    description=item,
                    steps=[
                        f"draft implementation note for: {item[:60]}",
                        f"write tests for: {item[:60]}",
                    ],
                )
            )
        for template in _BASE_CANDIDATES:
            if len(candidates) >= self.policy.max_candidates:
                break
            candidates.append(
                EvolveCandidate(
                    candidate_id=_uid("ecand"),
                    mission_id=mission.mission_id,
                    title=template["title"],
                    candidate_type=template["candidate_type"],
                    description=template["description"],
                    steps=list(template["steps"]),
                )
            )
        for candidate in candidates:
            self._emit(
                EVENT_CANDIDATE_CREATED, candidate.candidate_id,
                f"candidate created ({candidate.candidate_type}): {candidate.title[:60]}",
                mission_id=mission.mission_id,
            )
        # Local context nudges: weak test ratio raises the test candidate.
        self._context_priors = {}
        if context.py_files:
            ratio = context.test_files / max(context.py_files, 1)
            self._context_priors["test_ratio"] = ratio
        return candidates

    def _priors_for(self, candidate: EvolveCandidate) -> dict[str, float]:
        for template in _BASE_CANDIDATES:
            if template["title"] == candidate.title:
                priors = dict(template["priors"])
                break
        else:
            priors = {"user_value": 0.7, "implementation_feasibility": 0.6,
                      "testability": 0.65, "demo_impact": 0.6,
                      "provenance_value": 0.7, "autonomy_leverage": 0.6,
                      "safety_risk": 0.2, "time_cost": 0.45}
        ratio = self._context_priors.get("test_ratio")
        if ratio is not None and candidate.candidate_type == "tiny_polish" and ratio < 0.5:
            priors["user_value"] = min(1.0, priors.get("user_value", 0.5) + 0.15)
        return priors

    def _build_opportunity_run(
        self,
        mission: EvolveMission,
        candidates: list[EvolveCandidate],
        snapshot: RoadmapSnapshot,
    ) -> OpportunityRun:
        from opencobalt.execution.policy import classify_risk, max_risk

        goal = OpportunityGoal(
            goal_id=_uid("goal"),
            text=mission.goal,
            goal_class="strategy",
            metadata={"mission_id": mission.mission_id, "source": "evolve"},
        )
        run = OpportunityRun(run_id=_uid("orun"), goal=goal)
        ranked = sorted(
            candidates, key=lambda c: c.score.total if c.score else 0.0, reverse=True
        )
        for candidate in candidates:
            track = OpportunityTrack(
                track_id=_uid("otrk"),
                goal_id=goal.goal_id,
                name=candidate.title[:60],
                track_type=_TYPE_TO_TRACK_TYPE.get(candidate.candidate_type, "strategy"),
                description=candidate.description,
                status="scored",
            )
            candidate.track_id = track.track_id
            run.tracks.append(track)
            for rel in snapshot.docs_found[:3]:
                evidence = OpportunityEvidence(
                    evidence_id=_uid("ev"),
                    track_id=track.track_id,
                    source_type="docs",
                    reference=rel,
                    summary=f"roadmap doc informs candidate: {rel}",
                    strength=0.6,
                    collected_by="evolve-engine",
                )
                track.evidence_ids.append(evidence.evidence_id)
                candidate.evidence_ids.append(evidence.evidence_id)
                run.evidence.append(evidence)
            evidence_items = [
                e for e in run.evidence if e.track_id == track.track_id
            ]
            run.scores.append(score_track(track, evidence_items))

            if candidate in ranked[: self.policy.plan_top_n]:
                steps = []
                worst = "green"
                for description in candidate.steps:
                    risk = classify_risk(description)
                    worst = max_risk(worst, risk)
                    steps.append(
                        {
                            "description": description,
                            "risk_level": risk,
                            "approval_required": risk in ("red", "black"),
                        }
                    )
                plan = OpportunityPlan(
                    plan_id=_uid("oplan"),
                    track_id=track.track_id,
                    goal_id=goal.goal_id,
                    delegation=mission.delegation or {},
                    steps=steps,
                    risk_level=worst,
                    approval_state="not_required" if worst == "green" else "pending",
                )
                candidate.opportunity_plan_id = plan.plan_id
                candidate.risk_level = worst
                track.plan_id = plan.plan_id
                track.status = "planned"
                run.plans.append(plan)
        return run

    def _build_report(
        self, mission: EvolveMission, candidates: list[EvolveCandidate]
    ) -> EvolveReport:
        ranked = sorted(
            candidates, key=lambda c: c.score.total if c.score else 0.0, reverse=True
        )
        entries = [
            {
                "candidate_id": c.candidate_id,
                "title": c.title,
                "candidate_type": c.candidate_type,
                "total": c.score.total if c.score else 0.0,
                "wrapperware_escape": (
                    c.score.dimensions.get("wrapperware_escape_value") if c.score else None
                ),
                "risk_level": c.risk_level,
                "status": c.status,
                "track_id": c.track_id,
            }
            for c in ranked
        ]
        next_commands = []
        if entries:
            top = entries[0]["candidate_id"][:14]
            next_commands = [
                f"opencobalt evolve candidates {mission.mission_id[:13]}",
                f"opencobalt evolve approve {top}",
                f"opencobalt evolve run {top} --runtime noop",
                f"opencobalt why {top}",
            ]
        return EvolveReport(
            mission_id=mission.mission_id,
            goal=mission.goal,
            ranked=entries,
            next_commands=next_commands,
        )

    def _persist(
        self,
        mission: EvolveMission,
        candidates: list[EvolveCandidate],
        run: OpportunityRun,
    ) -> None:
        try:
            from .opportunity_store import OpportunityStore

            OpportunityStore(self.db_path).save_run(run)
        except Exception:
            pass  # best effort; mission JSON still records everything
        self.store.save_mission(mission)
        for candidate in candidates:
            self.store.save_candidate(candidate)

    # --- Approval / execution handoff (delegates to the bridge) ---

    def approve_candidate(self, candidate_id: str) -> tuple[EvolveCandidate, Any]:
        """Create (or reuse) an approval request for a candidate and approve
        its approvable steps. Black steps stay blocked as always."""
        from .approval_bridge import ApprovalBridge
        from .opportunity_store import OpportunityStore

        candidate = self._require_candidate(candidate_id)
        store = OpportunityStore(self.db_path)
        run = store.find_run_for_track(candidate.track_id) if candidate.track_id else None
        if run is None:
            raise KeyError(f"no opportunity run backs candidate {candidate_id}")
        bridge = ApprovalBridge(db_path=self.db_path)
        request, created = bridge.promote(
            run, candidate.track_id, opportunity_store=store
        )
        if created:
            self._emit(
                EVENT_APPROVAL_CREATED, request.request_id,
                f"approval request created for candidate {candidate.title[:60]}",
                candidate_id=candidate.candidate_id,
            )
        bridge.approve(request.request_id, decided_by="human")
        request = bridge.store.get_request(request.request_id)
        candidate.approval_request_id = request.request_id
        candidate.status = "approved" if request.state == "approved" else "approval_pending"
        self.store.save_candidate(candidate)
        return candidate, request

    def run_candidate(
        self,
        candidate_id: str,
        *,
        engine: Any,
        runtime: str | None = None,
        execute: bool = False,
        approved: bool = False,
        rerun: bool = False,
    ) -> tuple[EvolveCandidate, list[Any]]:
        """Hand a candidate's approved steps to the execution engine via the
        Approval Bridge. All policy gates apply unchanged."""
        from .approval_bridge import ApprovalBridge

        candidate = self._require_candidate(candidate_id)
        if not candidate.approval_request_id:
            raise KeyError(
                f"candidate has no approval request; run: "
                f"opencobalt evolve approve {candidate.candidate_id[:14]}"
            )
        self._emit(
            EVENT_EXECUTION_REQUESTED, candidate.candidate_id,
            f"execution requested (execute={execute}) for {candidate.title[:60]}",
            approval_request_id=candidate.approval_request_id,
        )
        bridge = ApprovalBridge(db_path=self.db_path)
        reports = bridge.run_steps(
            candidate.approval_request_id,
            engine=engine,
            runtime=runtime,
            execute=execute,
            approved=approved,
            rerun=rerun,
        )
        executed = [r for r in reports if r.action == "executed"]
        for report in reports:
            if report.step.receipt_id and report.step.receipt_id not in candidate.receipt_ids:
                candidate.receipt_ids.append(report.step.receipt_id)
                self._emit(
                    EVENT_RECEIPT_LINKED, report.step.receipt_id,
                    f"receipt linked to candidate {candidate.candidate_id[:14]}",
                    candidate_id=candidate.candidate_id,
                )
            if report.step.execution_plan_id and (
                report.step.execution_plan_id not in candidate.execution_plan_ids
            ):
                candidate.execution_plan_ids.append(report.step.execution_plan_id)
        if executed:
            all_verified = all(
                r.outcome is not None
                and r.outcome.receipt.verification_status in ("verified", "unverified")
                and r.step.approval_state == "executed"
                for r in executed
            )
            candidate.status = "verified" if all_verified else "failed"
        elif execute and any(r.action in ("refused", "blocked") for r in reports):
            candidate.status = "approval_pending"
        self.store.save_candidate(candidate)
        return candidate, reports

    def record_outcome(
        self, candidate_id: str, outcome: str, *, notes: str | None = None
    ) -> str:
        """Record an outcome for the candidate's backing track, receipt-linked."""
        from .opportunity_store import OpportunityStore

        candidate = self._require_candidate(candidate_id)
        if candidate.track_id is None:
            raise KeyError(f"candidate has no backing track: {candidate_id}")
        receipt_id = candidate.receipt_ids[-1] if candidate.receipt_ids else None
        outcome_id = OpportunityStore(self.db_path).record_outcome(
            candidate.track_id,
            outcome=outcome,
            plan_id=candidate.opportunity_plan_id,
            receipt_id=receipt_id,
            notes=notes,
        )
        candidate.outcome_ids.append(outcome_id)
        self.store.save_candidate(candidate)
        self._emit(
            EVENT_OUTCOME_RECORDED, outcome_id,
            f"outcome {outcome} recorded for candidate {candidate.candidate_id[:14]}",
            candidate_id=candidate.candidate_id, receipt_id=receipt_id,
        )
        return outcome_id

    # --- Roadmap writing (explicitly gated) ---

    _ROADMAP_MARKER = "<!-- evolve-proposals -->"

    def write_roadmap_proposals(self, mission: EvolveMission) -> Path:
        """Append mission proposals to docs/ROADMAP.md. Caller must hold the
        explicit consent (--write flag); policy.allow_roadmap_write must be
        set by that same explicit flag. Never rewrites existing content."""
        if not self.policy.allow_roadmap_write:
            raise PermissionError(
                "roadmap writes are gated; pass --write to opencobalt evolve roadmap"
            )
        roadmap = self.root / "docs" / "ROADMAP.md"
        text = roadmap.read_text(encoding="utf-8") if roadmap.exists() else "# Roadmap\n"
        block_lines = [
            "",
            self._ROADMAP_MARKER,
            f"### Candidate ideas (evolve mission {mission.mission_id[:13]})",
            "",
            "Proposed by Evolve Mode; supervised, not yet committed work.",
            "",
        ]
        for proposal in mission.roadmap_proposals[:8]:
            block_lines.append(
                f"- [{proposal.proposal_type}] {proposal.title} "
                f"(escape value {proposal.wrapperware_escape_value:.2f})"
            )
            proposal.status = "written"
        block = "\n".join(block_lines) + "\n"
        if f"evolve mission {mission.mission_id[:13]}" not in text:
            roadmap.write_text(text + block, encoding="utf-8")
        self.store.save_mission(mission)
        return roadmap

    # --- Helpers ---

    def _require_candidate(self, candidate_id: str) -> EvolveCandidate:
        candidate = self.store.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(f"unknown evolve candidate: {candidate_id}")
        return candidate

    def _emit(self, event_type: str, subject_id: str, message: str, **metadata: Any) -> None:
        event = make_event(
            event_type=event_type,
            subject_type="evolve",
            subject_id=subject_id,
            message=message,
            source="evolve-engine",
            metadata=metadata,
        )
        self.events.append(event)
        try:
            append_event(event, path=self.events_path)
        except OSError:
            pass
        if self.event_sink is not None:
            self.event_sink(event)
