"""Mission State Machine v1: the durable spine across the supervised loop.

A Mission is a top-level supervised work object that links the systems
that already exist instead of replacing them:

  goal -> opportunity discovery (OpportunityEngine / EvolveEngine)
       -> selected track / candidate -> opportunity plan
       -> approval request (ApprovalBridge)
       -> policy-gated execution (ExecutionEngine) -> receipts -> artifacts
       -> verification -> outcome feedback (OpportunityStore outcomes)

Nothing here executes work directly. Approval state is owned by the
Approval Bridge; mission steps are durable mirrors that carry the link
(mission step -> approval step -> execution plan -> receipt). The
execution policy gate is never bypassed or weakened: dry-run is always
the default, green/yellow need --execute, red needs --execute --yes,
black is blocked with no override.

State machine (advance moves at most one safe stage and never crosses
an approval boundary):

  created -> evidence_gathering -> opportunities_generated
          -> candidates_generated (evolve missions only)
          -> plan_proposed -> awaiting_approval
          -> executing_approved_step -> verifying -> awaiting_feedback
          -> completed | failed | abandoned
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from .events import append_event, make_event

if TYPE_CHECKING:
    from opencobalt.execution.engine import ExecutionEngine

    from .approval_bridge import ApprovalStep, StepRunReport
    from .auto_orchestrator import AutoPlan
    from .opportunity_engine import OpportunityRun

_DEFAULT_DB = Path(".opencobalt") / "ledger.db"
_DEFAULT_EVENTS_PATH = Path(".opencobalt") / "events" / "mission.jsonl"

MISSION_STATUSES = (
    "created",
    "evidence_gathering",
    "opportunities_generated",
    "candidates_generated",
    "plan_proposed",
    "awaiting_approval",
    "executing_approved_step",
    "verifying",
    "awaiting_feedback",
    "completed",
    "failed",
    "abandoned",
)

TERMINAL_STATUSES = ("completed", "failed", "abandoned")

MISSION_TYPES = ("opportunity", "evolve", "auto")

# Outcomes reuse the opportunity outcome vocabulary unchanged.
OUTCOME_TO_STATUS = {
    "useful": "completed",
    "neutral": "completed",
    "wasted": "failed",
    "abandoned": "abandoned",
}

_RISK_ORDER = {"green": 0, "yellow": 1, "red": 2, "black": 3}
# Risk budgets only ever tighten the existing gates. Black is not a valid
# budget because black work is blocked everywhere with no override.
RISK_BUDGETS = ("green", "yellow", "red")

EXECUTION_STATES = ("not_started", "dry_run", "executed", "failed")

EVENT_MISSION_CREATED = "mission.created"
EVENT_AUTO_PLAN_ATTACHED = "mission.auto_plan_attached"
EVENT_AUTO_ROUTE_PROMOTED = "mission.auto_route_promoted"
EVENT_STATUS_CHANGED = "mission.status_changed"
EVENT_DISCOVERY_LINKED = "mission.discovery_linked"
EVENT_TARGET_SELECTED = "mission.target_selected"
EVENT_PLAN_PROMOTED = "mission.plan_promoted"
EVENT_STEPS_CREATED = "mission.steps_created"
EVENT_STEP_APPROVED = "mission.step_approved"
EVENT_STEP_RUN = "mission.step_run"
EVENT_RECEIPT_LINKED = "mission.receipt_linked"
EVENT_VERIFICATION = "mission.verification"
EVENT_OUTCOME_RECORDED = "mission.outcome_recorded"

# Deterministic keyword routing: goals about improving OpenCobalt itself
# become evolve-type missions; everything else stays a generic
# opportunity mission. No LLM is consulted.
_EVOLVE_KEYWORDS = (
    "opencobalt",
    "evolve",
    "itself",
    "yourself",
    "self-improve",
    "self improvement",
    "wrapperware",
)

_INFORMATIONAL_AUTO_PRIMITIVES = {
    "status_check",
    "adapter_health_check",
    "approval_queue",
    "receipt_inspection",
    "provenance_why",
}
_APPROVAL_AUTO_PRIMITIVES = {
    "mission_start",
    "opportunity_discovery",
    "evolve_candidate_generation",
    "roadmap_design",
    "external_research",
}
_VERIFICATION_AUTO_PRIMITIVES = {"verification_gates"}
_EXECUTION_AUTO_PRIMITIVES = {"run_dry_run"}
_BLOCKED_AUTHORITY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("push", ("git push", " push ", "push origin")),
    ("merge", ("git merge", "gh pr merge", " merge ")),
    ("deploy", ("deploy", "production")),
    ("publish", ("publish", "npm publish", "twine upload")),
    ("spend", ("spend", "purchase", "buy ", "billing", "payment")),
    ("messages", ("send message", "external message", "email", "slack", "sms")),
    (
        "secrets/auth",
        (
            "secret",
            "credential",
            "token",
            "cookie",
            "private key",
            "ssh key",
            "login",
            "logout",
            "auth state",
        ),
    ),
    ("browser-control", ("browser-control", "browser control", "remote browser")),
    ("remote irreversible action", ("remote irreversible",)),
)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _max_risk(*risks: str) -> str:
    present = [risk for risk in risks if risk]
    if not present:
        return "green"
    return max(present, key=lambda risk: _RISK_ORDER.get(risk, 0))


def _blocked_authority_for_step(step: "MissionStep") -> list[str]:
    text = f" {step.title} {step.command_or_action} ".lower()
    blocked: list[str] = []
    for label, patterns in _BLOCKED_AUTHORITY_PATTERNS:
        if any(pattern in text for pattern in patterns):
            blocked.append(label)
    return list(dict.fromkeys(blocked))


class MissionError(Exception):
    """Base error for mission state machine failures."""


class RiskBudgetExceededError(MissionError):
    """A step's risk exceeds the mission's declared risk budget."""


# --- Models ---


@dataclass
class Mission:
    """One top-level supervised work object."""

    mission_id: str
    goal: str
    mission_type: str = "opportunity"
    status: str = "created"
    max_risk: str = "red"
    run_id: str | None = None  # backing opportunity run
    evolve_mission_id: str | None = None  # bridge into evolve mode
    selected_track_id: str | None = None
    selected_candidate_id: str | None = None
    active_plan_id: str | None = None  # opportunity plan
    approval_request_id: str | None = None
    last_receipt_id: str | None = None
    outcome: str | None = None
    outcome_id: str | None = None
    summary: str = ""
    auto_plan_id: str | None = None
    auto_plan_hash: str | None = None
    auto_intent: str | None = None
    autonomy_envelope: str | None = None
    cognitive_budget: str | None = None
    auto_next_action: str | None = None
    auto_required_approvals: list[str] = field(default_factory=list)
    auto_expected_receipts: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Mission:
        return cls(**data)


@dataclass
class MissionStep:
    """A durable mirror of one approval step inside a mission.

    The Approval Bridge owns approval state; this row carries the link so
    the mission can be read end to end without re-deriving anything.
    """

    step_id: str
    mission_id: str
    title: str
    command_or_action: str = ""
    risk_level: str = "green"
    approval_state: str = "pending"
    execution_state: str = "not_started"
    source_track_id: str | None = None
    source_candidate_id: str | None = None
    source_plan_id: str | None = None  # opportunity plan
    approval_request_id: str | None = None
    approval_step_id: str | None = None
    execution_plan_id: str | None = None
    receipt_id: str | None = None
    auto_step_order: int | None = None
    auto_primitive: str | None = None
    auto_step_why: str = ""
    auto_promotion_classification: str = ""
    auto_promotion_reason: str = ""
    uses_execution_engine: bool = False
    requires_approval: bool = False
    expected_receipt: bool = False
    blocked_authority: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def touch(self) -> None:
        self.updated_at = _now_iso()


@dataclass
class AdvanceReport:
    """What one `missions advance` call did (or why it stopped)."""

    mission: Mission
    action: str  # discovered / selected / promoted / blocked_on_approval /
    #              ready_to_run / verified / awaiting_feedback / noop / abandoned
    detail: str = ""
    steps: list[MissionStep] = field(default_factory=list)


@dataclass
class AutoRoutePromotionReport:
    """Result of explicitly promoting durable auto route state."""

    mission: Mission
    action: str
    detail: str = ""
    approval_request_id: str | None = None
    promoted_steps: list[MissionStep] = field(default_factory=list)
    unpromoted_steps: list[MissionStep] = field(default_factory=list)
    blocked_steps: list[MissionStep] = field(default_factory=list)
    created: bool = False


_SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    mission_id            TEXT PRIMARY KEY,
    goal                  TEXT NOT NULL,
    mission_type          TEXT NOT NULL,
    status                TEXT NOT NULL,
    max_risk              TEXT NOT NULL,
    run_id                TEXT,
    evolve_mission_id     TEXT,
    selected_track_id     TEXT,
    selected_candidate_id TEXT,
    active_plan_id        TEXT,
    approval_request_id   TEXT,
    last_receipt_id       TEXT,
    outcome               TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    mission_json          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mission_steps (
    step_id             TEXT PRIMARY KEY,
    mission_id          TEXT NOT NULL,
    title               TEXT NOT NULL,
    risk_level          TEXT NOT NULL,
    approval_state      TEXT NOT NULL,
    execution_state     TEXT NOT NULL,
    approval_request_id TEXT,
    approval_step_id    TEXT,
    receipt_id          TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    step_json           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mission_events (
    event_id     TEXT PRIMARY KEY,
    mission_id   TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS mission_events_no_update
BEFORE UPDATE ON mission_events
BEGIN
    SELECT RAISE(ABORT, 'mission_events is append-only');
END;

CREATE TRIGGER IF NOT EXISTS mission_events_no_delete
BEFORE DELETE ON mission_events
BEGIN
    SELECT RAISE(ABORT, 'mission_events is append-only');
END;
"""


class MissionStore:
    """SQLite persistence for missions, steps, and append-only events.

    Lives in the shared ledger database. mission_events is enforced
    append-only at the SQLite level via triggers.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or _DEFAULT_DB).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- Missions ---

    def save_mission(self, mission: Mission) -> None:
        mission.updated_at = _now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO missions VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    mission.mission_id,
                    mission.goal,
                    mission.mission_type,
                    mission.status,
                    mission.max_risk,
                    mission.run_id,
                    mission.evolve_mission_id,
                    mission.selected_track_id,
                    mission.selected_candidate_id,
                    mission.active_plan_id,
                    mission.approval_request_id,
                    mission.last_receipt_id,
                    mission.outcome,
                    mission.created_at,
                    mission.updated_at,
                    json.dumps(mission.to_dict(), sort_keys=True),
                ),
            )

    def get_mission(self, mission_id: str) -> Mission | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT mission_json FROM missions "
                "WHERE mission_id = ? OR mission_id LIKE ?",
                (mission_id, f"{mission_id}%"),
            ).fetchone()
        return Mission.from_dict(json.loads(row["mission_json"])) if row else None

    def latest_mission(self) -> Mission | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT mission_json FROM missions ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return Mission.from_dict(json.loads(row["mission_json"])) if row else None

    def list_missions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT mission_id, goal, mission_type, status, "
                "selected_track_id, selected_candidate_id, "
                "approval_request_id, last_receipt_id, outcome, created_at "
                "FROM missions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Steps ---

    def save_step(self, step: MissionStep) -> None:
        step.touch()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO mission_steps VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    step.step_id,
                    step.mission_id,
                    step.title,
                    step.risk_level,
                    step.approval_state,
                    step.execution_state,
                    step.approval_request_id,
                    step.approval_step_id,
                    step.receipt_id,
                    step.created_at,
                    step.updated_at,
                    json.dumps(asdict(step), sort_keys=True),
                ),
            )

    def get_step(self, step_id: str) -> MissionStep | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT step_json FROM mission_steps "
                "WHERE step_id = ? OR step_id LIKE ?",
                (step_id, f"{step_id}%"),
            ).fetchone()
        return MissionStep(**json.loads(row["step_json"])) if row else None

    def list_steps(self, mission_id: str) -> list[MissionStep]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT step_json FROM mission_steps "
                "WHERE mission_id = ? ORDER BY created_at, step_id",
                (mission_id,),
            ).fetchall()
        return [MissionStep(**json.loads(r["step_json"])) for r in rows]

    # --- Events (append-only) ---

    def append_mission_event(
        self, mission_id: str, event_type: str, payload: dict[str, Any] | None = None
    ) -> str:
        event_id = _uid("mev")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO mission_events VALUES (?,?,?,?,?)",
                (
                    event_id,
                    mission_id,
                    event_type,
                    json.dumps(payload or {}, sort_keys=True),
                    _now_iso(),
                ),
            )
        return event_id

    def list_mission_events(
        self, mission_id: str, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mission_events WHERE mission_id = ? "
                "ORDER BY created_at, event_id LIMIT ?",
                (mission_id, limit),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            out.append(item)
        return out


# --- Engine ---


def classify_mission_type(goal: str) -> str:
    """Deterministic mission-type routing. No LLM."""
    lower = goal.lower()
    if any(kw in lower for kw in _EVOLVE_KEYWORDS):
        return "evolve"
    return "opportunity"


class MissionEngine:
    """Drives missions through the state machine by delegating to the
    existing engines. Never starts a subprocess and never bypasses the
    approval bridge or the execution policy gate."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        db_path: Path | None = None,
        events_path: Path | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.root = root or Path(".")
        self.db_path = db_path
        self.events_path = events_path or _DEFAULT_EVENTS_PATH
        self.event_sink = event_sink
        self.store = MissionStore(db_path)
        self.events: list[dict[str, Any]] = []

    # --- Lazy collaborators (import cost stays out of unrelated CLI paths) ---

    def _opportunity_store(self):
        from .opportunity_store import OpportunityStore

        return OpportunityStore(self.db_path)

    def _approval_bridge(self):
        from .approval_bridge import ApprovalBridge

        return ApprovalBridge(db_path=self.db_path)

    def _execution_engine(self) -> ExecutionEngine:
        from opencobalt.execution.engine import ExecutionEngine
        from opencobalt.execution.store import ExecutionStore

        return ExecutionEngine(store=ExecutionStore(self.db_path))

    # --- Lifecycle: start ---

    def start_mission(
        self,
        goal: str,
        *,
        mission_type: str = "auto",
        max_risk: str = "red",
        top_n: int = 3,
    ) -> Mission:
        """Create a durable mission and run opportunity discovery.

        Discovery is planning-only in both engines; nothing executes.
        """
        if max_risk not in RISK_BUDGETS:
            raise MissionError(
                f"max_risk must be one of {RISK_BUDGETS}; black work is "
                "blocked everywhere and cannot be a budget"
            )
        resolved_type = (
            classify_mission_type(goal) if mission_type == "auto" else mission_type
        )
        if resolved_type not in MISSION_TYPES:
            raise MissionError(f"unknown mission type: {mission_type}")

        mission = Mission(
            mission_id=_uid("mis"),
            goal=goal,
            mission_type=resolved_type,
            max_risk=max_risk,
        )
        self.store.save_mission(mission)
        self._record(
            mission, EVENT_MISSION_CREATED,
            f"mission created ({resolved_type}, risk budget {max_risk})",
            goal=goal, mission_type=resolved_type, max_risk=max_risk,
        )
        self._set_status(mission, "evidence_gathering", "discovery starting")

        if resolved_type == "evolve":
            from .evolve import EvolveEngine

            result = EvolveEngine(root=self.root, db_path=self.db_path).start_mission(
                goal
            )
            mission.evolve_mission_id = result.mission.mission_id
            mission.run_id = result.mission.run_id
            self._record(
                mission, EVENT_DISCOVERY_LINKED,
                f"evolve mission {result.mission.mission_id[:13]} backs this mission "
                f"({len(result.candidates)} candidate(s))",
                evolve_mission_id=result.mission.mission_id,
                run_id=mission.run_id,
                candidate_count=len(result.candidates),
            )
            self._set_status(mission, "opportunities_generated", "tracks scored")
            self._set_status(
                mission, "candidates_generated",
                f"{len(result.candidates)} evolve candidate(s) scored",
            )
        else:
            from .opportunity_engine import OpportunityEngine

            run = OpportunityEngine(root=self.root, db_path=self.db_path).brainstorm(
                goal, top_n=top_n
            )
            mission.run_id = run.run_id
            self._record(
                mission, EVENT_DISCOVERY_LINKED,
                f"opportunity run {run.run_id[:13]} backs this mission "
                f"({len(run.tracks)} track(s), {len(run.evidence)} evidence item(s))",
                run_id=run.run_id,
                track_count=len(run.tracks),
                evidence_count=len(run.evidence),
            )
            self._set_status(
                mission, "opportunities_generated",
                f"{len(run.tracks)} track(s) scored",
            )
        self.store.save_mission(mission)
        return mission

    def create_auto_mission(self, plan: AutoPlan) -> tuple[Mission, list[MissionStep]]:
        """Persist an AutoPlan as mission state without discovery or execution.

        The created route steps intentionally have no approval-step linkage.
        They record future approval and receipt expectations only; any later
        runtime work must create proper ApprovalBridge/ExecutionEngine state.
        """
        from .autonomy_envelopes import get_autonomy_envelope

        envelope = get_autonomy_envelope(plan.selected_envelope)
        max_risk = envelope.max_risk_level
        if max_risk == "black":
            max_risk = "red"
        mission = Mission(
            mission_id=_uid("mis"),
            goal=plan.goal,
            mission_type="auto",
            status="plan_proposed",
            max_risk=max_risk,
            summary=f"auto plan {plan.auto_plan_id} persisted without execution",
            auto_plan_id=plan.auto_plan_id,
            auto_plan_hash=plan.auto_plan_hash,
            auto_intent=plan.intent,
            autonomy_envelope=plan.selected_envelope,
            cognitive_budget=plan.selected_cognitive_budget,
            auto_next_action=plan.next_recommended_action,
            auto_required_approvals=list(plan.required_approvals),
            auto_expected_receipts=list(plan.expected_receipts),
        )
        self.store.save_mission(mission)
        self._record(
            mission,
            EVENT_MISSION_CREATED,
            f"auto mission created for {plan.intent}",
            goal=plan.goal,
            auto_plan_id=plan.auto_plan_id,
            auto_plan_hash=plan.auto_plan_hash,
            intent=plan.intent,
            envelope=plan.selected_envelope,
            cognitive_budget=plan.selected_cognitive_budget,
        )

        steps = [
            self._mirror_auto_step(
                mission,
                route_step,
            )
            for route_step in plan.internal_route_steps
        ]
        for step in steps:
            self.store.save_step(step)
        self._record(
            mission,
            EVENT_AUTO_PLAN_ATTACHED,
            f"auto plan {plan.auto_plan_id} attached ({len(steps)} route step(s))",
            auto_plan=plan.model_dump(mode="json"),
            step_ids=[step.step_id for step in steps],
        )
        self.store.save_mission(mission)
        return mission, steps

    def promote_auto_route(
        self,
        mission_id: str,
        *,
        new: bool = False,
    ) -> AutoRoutePromotionReport:
        """Promote selected auto route steps into pending approval requests.

        This is an explicit boundary crossing from durable planning state to
        approval state. It does not approve, execute, or fabricate receipts.
        """
        mission = self._require_mission(mission_id)
        if mission.mission_type != "auto":
            raise MissionError(
                f"mission {mission.mission_id[:13]} is {mission.mission_type}; "
                "only auto missions can promote auto routes"
            )
        if not mission.auto_plan_id or not mission.auto_plan_hash:
            raise MissionError("auto mission has no AutoPlan metadata to promote")

        route_steps = self.store.list_steps(mission.mission_id)
        if not route_steps:
            raise MissionError("auto mission has no route steps to promote")

        approval_payloads: list[dict[str, Any]] = []
        unpromoted: list[MissionStep] = []
        for step in route_steps:
            classification, blocked_authority = self._classify_auto_route_step(step)
            step.auto_promotion_classification = classification
            step.auto_promotion_reason = self._auto_promotion_reason(
                classification, blocked_authority
            )
            if classification == "blocked_authority":
                step.risk_level = "black"
                step.blocked_authority = blocked_authority
                step.requires_approval = True
            elif classification == "verification_candidate":
                step.risk_level = _max_risk(step.risk_level, "yellow")
                step.requires_approval = True
            elif classification == "execution_candidate":
                step.risk_level = _max_risk(step.risk_level, "yellow")
                step.requires_approval = True
            elif classification == "approval_candidate":
                step.requires_approval = True
            else:
                step.approval_state = "not_required"
                self.store.save_step(step)
                unpromoted.append(step)
                continue

            approval_payloads.append(
                self._auto_approval_payload(mission, step, blocked_authority)
            )
            self.store.save_step(step)

        if not approval_payloads:
            self._record(
                mission,
                EVENT_AUTO_ROUTE_PROMOTED,
                "auto route inspected; no promotable route steps found",
                auto_plan_id=mission.auto_plan_id,
                promoted_step_ids=[],
                unpromoted_step_ids=[step.step_id for step in unpromoted],
            )
            return AutoRoutePromotionReport(
                mission=mission,
                action="noop",
                detail="no promotable auto route steps found",
                unpromoted_steps=unpromoted,
            )

        bridge = self._approval_bridge()
        request, created = bridge.promote_auto_route(
            mission_id=mission.mission_id,
            auto_plan_id=mission.auto_plan_id,
            auto_plan_hash=mission.auto_plan_hash,
            goal=mission.goal,
            intent=mission.auto_intent or "",
            envelope=mission.autonomy_envelope or "",
            cognitive_budget=mission.cognitive_budget or "",
            route_steps=approval_payloads,
            new=new,
        )
        request_steps = {
            approval_step.metadata.get("route_mission_step_id"): approval_step
            for approval_step in request.steps
        }
        promoted: list[MissionStep] = []
        blocked: list[MissionStep] = []
        for step in route_steps:
            approval_step = request_steps.get(step.step_id)
            if approval_step is None:
                continue
            step.approval_request_id = request.request_id
            step.approval_step_id = approval_step.step_id
            step.approval_state = approval_step.approval_state
            step.risk_level = approval_step.risk_level
            step.execution_plan_id = approval_step.execution_plan_id
            step.receipt_id = approval_step.receipt_id
            step.requires_approval = True
            step.auto_promotion_classification = str(
                approval_step.metadata.get("promotion_classification", "")
            )
            step.auto_promotion_reason = str(
                approval_step.metadata.get("promotion_reason", "")
            )
            step.blocked_authority = list(
                approval_step.metadata.get("blocked_authority", [])
            )
            self.store.save_step(step)
            promoted.append(step)
            if step.auto_promotion_classification == "blocked_authority":
                blocked.append(step)

        mission.approval_request_id = request.request_id
        if mission.status == "plan_proposed":
            self._set_status(
                mission,
                "awaiting_approval",
                "auto route promoted into explicit pending approval requests",
            )
        self._record(
            mission,
            EVENT_AUTO_ROUTE_PROMOTED,
            f"auto route promoted to approval request {request.request_id[:13]} "
            f"({len(promoted)} promoted, {len(unpromoted)} unpromoted)",
            approval_request_id=request.request_id,
            created=created,
            auto_plan_id=mission.auto_plan_id,
            auto_plan_hash=mission.auto_plan_hash,
            envelope=mission.autonomy_envelope,
            cognitive_budget=mission.cognitive_budget,
            promoted_step_ids=[step.step_id for step in promoted],
            blocked_step_ids=[step.step_id for step in blocked],
            unpromoted_step_ids=[step.step_id for step in unpromoted],
        )
        self.store.save_mission(mission)
        return AutoRoutePromotionReport(
            mission=mission,
            action="promoted" if created else "reused",
            detail=(
                f"{len(promoted)} route step(s) linked to approval request "
                f"{request.request_id[:13]}; approval requests are pending "
                "and nothing executed"
            ),
            approval_request_id=request.request_id,
            promoted_steps=promoted,
            unpromoted_steps=unpromoted,
            blocked_steps=blocked,
            created=created,
        )

    # --- Lifecycle: advance ---

    def advance(self, mission_id: str) -> AdvanceReport:
        """Move the mission one safe stage. Never executes anything and
        never crosses an approval boundary."""
        mission = self._require_mission(mission_id)

        if mission.status in TERMINAL_STATUSES:
            return AdvanceReport(
                mission=mission, action="noop",
                detail=f"mission is {mission.status}; nothing to advance",
            )
        if mission.mission_type == "auto":
            return AdvanceReport(
                mission=mission,
                action="noop",
                detail=(
                    "auto mission stores durable route state only; follow the "
                    "recorded next action. nothing executes from advance."
                ),
                steps=self.store.list_steps(mission.mission_id),
            )
        if mission.status in ("created", "evidence_gathering"):
            return AdvanceReport(
                mission=mission, action="noop",
                detail="discovery did not finish; start a new mission",
            )
        if mission.status in ("opportunities_generated", "candidates_generated"):
            return self._advance_select_and_plan(mission)
        if mission.status == "plan_proposed":
            return self._advance_promote(mission)
        if mission.status in ("awaiting_approval", "executing_approved_step"):
            return self._advance_approval_boundary(mission)
        if mission.status == "verifying":
            return self._advance_verify(mission)
        if mission.status == "awaiting_feedback":
            return AdvanceReport(
                mission=mission, action="awaiting_feedback",
                detail=(
                    "record an outcome: opencobalt missions outcome "
                    f"{mission.mission_id[:13]} useful"
                ),
            )
        return AdvanceReport(  # pragma: no cover - statuses are exhaustive
            mission=mission, action="noop", detail=f"unknown status {mission.status}"
        )

    def _advance_select_and_plan(self, mission: Mission) -> AdvanceReport:
        run = self._require_run(mission)
        track_id, candidate_id = self._select_target(mission, run)
        track = run.get_track(track_id)
        if track is None:
            raise MissionError(f"selected track not found in run: {track_id}")

        if track.plan_id is None:
            from .opportunity_engine import OpportunityEngine

            plan = OpportunityEngine(
                root=self.root, db_path=self.db_path
            ).plan_track(run, track.track_id)
        else:
            plan = next((p for p in run.plans if p.plan_id == track.plan_id), None)
            if plan is None:
                raise MissionError(f"track references missing plan: {track.plan_id}")

        mission.selected_track_id = track.track_id
        mission.selected_candidate_id = candidate_id
        mission.active_plan_id = plan.plan_id
        score = run.score_for(track.track_id)
        message = f"selected track {track.track_id[:13]} ({track.name})"
        if score:
            message += f" score {score.total:.3f}"
        self._record(
            mission, EVENT_TARGET_SELECTED,
            message,
            track_id=track.track_id,
            candidate_id=candidate_id,
            plan_id=plan.plan_id,
            score_total=score.total if score else None,
        )
        self._set_status(
            mission, "plan_proposed",
            f"plan {plan.plan_id[:14]} proposed ({len(plan.steps)} step(s), "
            f"risk {plan.risk_level})",
        )
        self.store.save_mission(mission)
        return AdvanceReport(
            mission=mission, action="selected",
            detail=(
                f"track {track.track_id[:13]} selected; plan "
                f"{plan.plan_id[:14]} proposed (risk {plan.risk_level})"
            ),
        )

    def _advance_promote(self, mission: Mission) -> AdvanceReport:
        run = self._require_run(mission)
        if not mission.selected_track_id:
            raise MissionError("no track selected; advance the mission first")
        bridge = self._approval_bridge()
        request, created = bridge.promote(
            run, mission.selected_track_id, opportunity_store=self._opportunity_store()
        )
        mission.approval_request_id = request.request_id
        self._record(
            mission, EVENT_PLAN_PROMOTED,
            f"approval request {request.request_id[:13]} "
            f"{'created' if created else 'reused'} ({len(request.steps)} step(s))",
            approval_request_id=request.request_id, created=created,
        )

        steps = [
            self._mirror_step(mission, approval_step)
            for approval_step in request.steps
        ]
        for step in steps:
            self.store.save_step(step)
        self._record(
            mission, EVENT_STEPS_CREATED,
            f"{len(steps)} mission step(s) created from approval request",
            step_ids=[s.step_id for s in steps],
        )
        pending = [s for s in steps if s.approval_state == "pending"]
        self._set_status(
            mission, "awaiting_approval",
            f"{len(pending)} step(s) awaiting approval",
        )
        self.store.save_mission(mission)
        return AdvanceReport(
            mission=mission, action="promoted",
            detail=(
                f"{len(steps)} step(s) created; {len(pending)} pending approval. "
                "Approval is a human boundary; nothing executes."
            ),
            steps=steps,
        )

    def _advance_approval_boundary(self, mission: Mission) -> AdvanceReport:
        steps = self.sync_steps(mission)
        decidable = [s for s in steps if s.risk_level != "black"]
        pending = [s for s in decidable if s.approval_state == "pending"]
        approved = [s for s in decidable if s.approval_state == "approved"]
        executed = [s for s in decidable if s.approval_state == "executed"]
        failed = [s for s in decidable if s.approval_state == "failed"]

        if not decidable:
            self._set_status(
                mission, "abandoned", "every step is black-risk and blocked"
            )
            self.store.save_mission(mission)
            return AdvanceReport(
                mission=mission, action="abandoned",
                detail="every step is black-risk; black is blocked with no override",
                steps=steps,
            )
        if pending:
            return AdvanceReport(
                mission=mission, action="blocked_on_approval",
                detail=(
                    f"{len(pending)} step(s) need approval: opencobalt missions "
                    f"approve-step {pending[0].step_id[:14]}"
                ),
                steps=steps,
            )
        if failed and not approved:
            self._set_status(mission, "failed", f"{len(failed)} step(s) failed")
            self.store.save_mission(mission)
            return AdvanceReport(
                mission=mission, action="failed",
                detail=f"{len(failed)} step(s) failed in execution", steps=steps,
            )
        if approved:
            return AdvanceReport(
                mission=mission, action="ready_to_run",
                detail=(
                    f"{len(approved)} approved step(s) ready: opencobalt missions "
                    f"run-step {approved[0].step_id[:14]} --execute "
                    "(execution never happens implicitly)"
                ),
                steps=steps,
            )
        if executed:
            self._set_status(
                mission, "verifying", f"{len(executed)} executed step(s) to verify"
            )
            self.store.save_mission(mission)
            return AdvanceReport(
                mission=mission, action="verifying",
                detail="all decided steps executed; advance again to verify receipts",
                steps=steps,
            )
        if decidable and all(s.approval_state == "rejected" for s in decidable):
            self._set_status(mission, "abandoned", "every step was rejected")
            self.store.save_mission(mission)
            return AdvanceReport(
                mission=mission, action="abandoned",
                detail="every decidable step was rejected", steps=steps,
            )
        return AdvanceReport(
            mission=mission, action="blocked_on_approval",
            detail="no actionable steps; approve or reject pending work",
            steps=steps,
        )

    def _advance_verify(self, mission: Mission) -> AdvanceReport:
        steps = self.sync_steps(mission)
        engine = self._execution_engine()
        statuses: list[str] = []
        for step in steps:
            if not step.receipt_id or step.execution_state != "executed":
                continue
            status = engine.verify_receipt(step.receipt_id)
            statuses.append(status)
            self._record(
                mission, EVENT_VERIFICATION,
                f"receipt {step.receipt_id[:13]} verification: {status}",
                receipt_id=step.receipt_id, verification_status=status,
            )
        bad = [s for s in statuses if s in ("failed", "partial")]
        if bad:
            self._set_status(
                mission, "failed", f"{len(bad)} receipt(s) failed verification"
            )
            self.store.save_mission(mission)
            return AdvanceReport(
                mission=mission, action="failed",
                detail=f"{len(bad)} receipt(s) failed artifact verification",
                steps=steps,
            )
        self._set_status(
            mission, "awaiting_feedback",
            f"{len(statuses)} receipt(s) verified or artifact-free",
        )
        self.store.save_mission(mission)
        return AdvanceReport(
            mission=mission, action="verified",
            detail=(
                "receipts verified; record an outcome: opencobalt missions "
                f"outcome {mission.mission_id[:13]} useful"
            ),
            steps=steps,
        )

    # --- Steps: approval and execution (delegated, never bypassed) ---

    def approve_step(
        self, step_id: str, *, decided_by: str = "human", reason: str = ""
    ) -> MissionStep:
        """Approve one mission step through the Approval Bridge.

        Black steps raise BlockedStepError inside the bridge; steps above
        the mission's risk budget are refused here before the bridge is
        even asked. Approval never executes anything.
        """
        step, mission = self._require_step(step_id)
        self._check_budget(mission, step, verb="approved")
        if not step.approval_request_id or not step.approval_step_id:
            raise MissionError(f"step has no approval linkage: {step.step_id}")
        bridge = self._approval_bridge()
        bridge.approve(
            step.approval_request_id,
            step_id=step.approval_step_id,
            decided_by=decided_by,
            reason=reason,
        )
        step = self._sync_one(step)
        self._record(
            mission, EVENT_STEP_APPROVED,
            f"step {step.step_id[:14]} approved ({step.risk_level}): {step.title[:60]}",
            step_id=step.step_id, approval_step_id=step.approval_step_id,
            decided_by=decided_by,
        )
        return step

    def run_step(
        self,
        step_id: str,
        *,
        engine: ExecutionEngine | None = None,
        runtime: str | None = None,
        execute: bool = False,
        approved: bool = False,
        rerun: bool = False,
    ) -> tuple[MissionStep, StepRunReport]:
        """Hand one approved mission step to the policy-gated execution
        engine via the Approval Bridge. Dry-run unless execute=True; red
        risk additionally needs approved=True; black never runs."""
        step, mission = self._require_step(step_id)
        self._check_budget(mission, step, verb="run")
        if not step.approval_request_id or not step.approval_step_id:
            raise MissionError(f"step has no approval linkage: {step.step_id}")
        bridge = self._approval_bridge()
        reports = bridge.run_steps(
            step.approval_request_id,
            engine=engine or self._execution_engine(),
            step_id=step.approval_step_id,
            runtime=runtime,
            execute=execute,
            approved=approved,
            rerun=rerun,
        )
        report = reports[0]
        step = self._sync_one(step)
        if report.action == "dry_run" and step.execution_state == "not_started":
            step.execution_state = "dry_run"
            self.store.save_step(step)
        self._record(
            mission, EVENT_STEP_RUN,
            f"step {step.step_id[:14]} run: {report.action} ({report.reason[:80]})",
            step_id=step.step_id, action=report.action,
            receipt_id=step.receipt_id, execution_plan_id=step.execution_plan_id,
        )
        if step.receipt_id:
            mission.last_receipt_id = step.receipt_id
            self._record(
                mission, EVENT_RECEIPT_LINKED,
                f"receipt {step.receipt_id[:13]} linked to mission",
                receipt_id=step.receipt_id, step_id=step.step_id,
            )
        if report.action == "executed":
            all_steps = self.sync_steps(mission)
            still_open = [
                s for s in all_steps
                if s.approval_state in ("pending", "approved") and s.risk_level != "black"
            ]
            if still_open:
                self._set_status(
                    mission, "executing_approved_step",
                    f"{len(still_open)} step(s) still open",
                )
            else:
                self._set_status(mission, "verifying", "all decided steps executed")
        self.store.save_mission(mission)
        return step, report

    # --- Outcome feedback ---

    def record_outcome(
        self, mission_id: str, outcome: str, *, notes: str | None = None
    ) -> str:
        """Record a receipt-evidenced outcome and close the mission.

        Evolve missions route through the evolve engine so candidate
        linkage is preserved; everything lands in the same bounded,
        explainable opportunity outcome table either way.
        """
        if outcome not in OUTCOME_TO_STATUS:
            raise MissionError(
                f"unknown outcome: {outcome} (use one of {tuple(OUTCOME_TO_STATUS)})"
            )
        mission = self._require_mission(mission_id)
        if mission.selected_track_id is None:
            raise MissionError("mission has no selected track; advance it first")

        if mission.mission_type == "evolve" and mission.selected_candidate_id:
            from .evolve import EvolveEngine

            outcome_id = EvolveEngine(
                root=self.root, db_path=self.db_path
            ).record_outcome(mission.selected_candidate_id, outcome, notes=notes)
        else:
            outcome_id = self._opportunity_store().record_outcome(
                mission.selected_track_id,
                outcome=outcome,
                plan_id=mission.active_plan_id,
                receipt_id=mission.last_receipt_id,
                notes=notes,
            )
        mission.outcome = outcome
        mission.outcome_id = outcome_id
        self._record(
            mission, EVENT_OUTCOME_RECORDED,
            f"outcome {outcome} recorded ({outcome_id[:14]})",
            outcome=outcome, outcome_id=outcome_id,
            receipt_id=mission.last_receipt_id,
        )
        self._set_status(
            mission, OUTCOME_TO_STATUS[outcome], f"outcome recorded: {outcome}"
        )
        self.store.save_mission(mission)
        return outcome_id

    # --- Sync (the bridge stays authoritative) ---

    def sync_steps(self, mission: Mission) -> list[MissionStep]:
        """Refresh every mirror from the approval store."""
        return [self._sync_one(step) for step in self.store.list_steps(mission.mission_id)]

    def _sync_one(self, step: MissionStep) -> MissionStep:
        if not step.approval_step_id:
            return step
        from .approval_bridge import ApprovalStore

        found = ApprovalStore(self.db_path).find_step(step.approval_step_id)
        if found is None:
            return step
        _, approval_step = found
        step.approval_state = approval_step.approval_state
        step.execution_plan_id = approval_step.execution_plan_id
        step.receipt_id = approval_step.receipt_id
        if approval_step.approval_state == "executed":
            step.execution_state = "executed"
        elif approval_step.approval_state == "failed":
            step.execution_state = "failed"
        self.store.save_step(step)
        return step

    # --- Helpers ---

    def _select_target(
        self, mission: Mission, run: OpportunityRun
    ) -> tuple[str, str | None]:
        """Pick the highest-scored track (or evolve candidate). Returns
        (track_id, candidate_id)."""
        if mission.mission_type == "evolve" and mission.evolve_mission_id:
            from .evolve import EvolveStore

            candidates = EvolveStore(self.db_path).list_candidates(
                mission.evolve_mission_id
            )
            usable = [c for c in candidates if c.track_id]
            planned = [c for c in usable if c.opportunity_plan_id]
            pick = (planned or usable)[0] if (planned or usable) else None
            if pick is None or pick.track_id is None:
                raise MissionError("evolve mission produced no usable candidates")
            return pick.track_id, pick.candidate_id

        totals = {s.track_id: s.total for s in run.scores}
        ranked = sorted(
            run.tracks, key=lambda t: totals.get(t.track_id, 0.0), reverse=True
        )
        if not ranked:
            raise MissionError("opportunity run produced no tracks")
        planned = [t for t in ranked if t.plan_id]
        return (planned or ranked)[0].track_id, None

    def _mirror_step(self, mission: Mission, approval_step: ApprovalStep) -> MissionStep:
        return MissionStep(
            step_id=_uid("mstp"),
            mission_id=mission.mission_id,
            title=approval_step.task[:120],
            command_or_action=approval_step.task,
            risk_level=approval_step.risk_level,
            approval_state=approval_step.approval_state,
            source_track_id=mission.selected_track_id,
            source_candidate_id=mission.selected_candidate_id,
            source_plan_id=mission.active_plan_id,
            approval_request_id=approval_step.request_id,
            approval_step_id=approval_step.step_id,
        )

    def _mirror_auto_step(
        self,
        mission: Mission,
        route_step: Any,
    ) -> MissionStep:
        risk_level = "green"
        if route_step.approval_required:
            risk_level = mission.max_risk
        elif route_step.uses_execution_engine:
            risk_level = "yellow"
        return MissionStep(
            step_id=_uid("mstp"),
            mission_id=mission.mission_id,
            title=f"{route_step.order}. {route_step.primitive}",
            command_or_action=route_step.command_hint,
            risk_level=risk_level,
            approval_state="not_required",
            execution_state="not_started",
            auto_step_order=route_step.order,
            auto_primitive=route_step.primitive,
            auto_step_why=route_step.why,
            uses_execution_engine=route_step.uses_execution_engine,
            requires_approval=route_step.approval_required,
            expected_receipt=route_step.expected_receipt,
            blocked_authority=list(route_step.blocked_authority),
        )

    def _classify_auto_route_step(
        self, step: MissionStep
    ) -> tuple[str, list[str]]:
        blocked_authority = _blocked_authority_for_step(step)
        if blocked_authority:
            return "blocked_authority", blocked_authority
        if step.uses_execution_engine or step.auto_primitive in _EXECUTION_AUTO_PRIMITIVES:
            return "execution_candidate", []
        if step.auto_primitive in _VERIFICATION_AUTO_PRIMITIVES:
            return "verification_candidate", []
        if step.requires_approval or step.auto_primitive in _APPROVAL_AUTO_PRIMITIVES:
            return "approval_candidate", []
        if step.auto_primitive in _INFORMATIONAL_AUTO_PRIMITIVES:
            return "informational", []
        return "informational", []

    @staticmethod
    def _auto_promotion_reason(
        classification: str,
        blocked_authority: list[str],
    ) -> str:
        if classification == "blocked_authority":
            return (
                "route step asks for blocked authority: "
                + ", ".join(blocked_authority)
            )
        if classification == "execution_candidate":
            return "route step expects ExecutionEngine-backed work or receipt evidence"
        if classification == "verification_candidate":
            return "route step represents verification gates that require explicit supervision"
        if classification == "approval_candidate":
            return "route step advances supervised mission or opportunity state"
        return "route step is informational and remains unpromoted"

    @staticmethod
    def _auto_approval_payload(
        mission: Mission,
        step: MissionStep,
        blocked_authority: list[str],
    ) -> dict[str, Any]:
        expected_receipt = (
            "WorkReceipt from ExecutionEngine dry-run or approved execution"
            if step.expected_receipt or step.uses_execution_engine
            else "No receipt expected until a later explicit ExecutionEngine handoff"
        )
        boundary = (
            "blocked authority; no approval can grant this in the current envelope"
            if step.auto_promotion_classification == "blocked_authority"
            else "explicit ApprovalBridge decision before any run"
        )
        task = step.command_or_action or step.title
        return {
            "route_mission_step_id": step.step_id,
            "route_step_order": step.auto_step_order,
            "route_step_primitive": step.auto_primitive,
            "route_step_why": step.auto_step_why,
            "task": task,
            "risk_level": step.risk_level,
            "promotion_classification": step.auto_promotion_classification,
            "promotion_reason": step.auto_promotion_reason,
            "expected_receipt_description": expected_receipt,
            "execution_primitive": step.auto_primitive or "",
            "required_approval_boundary": boundary,
            "blocked_authority": blocked_authority,
            "mission_id": mission.mission_id,
            "auto_plan_id": mission.auto_plan_id,
            "auto_plan_hash": mission.auto_plan_hash,
        }

    def _check_budget(self, mission: Mission, step: MissionStep, *, verb: str) -> None:
        if step.risk_level == "black":
            from .approval_bridge import BlockedStepError

            raise BlockedStepError(
                f"step {step.step_id[:14]} is black-risk and can never be {verb}"
            )
        if _RISK_ORDER.get(step.risk_level, 0) > _RISK_ORDER.get(mission.max_risk, 2):
            raise RiskBudgetExceededError(
                f"step risk {step.risk_level} exceeds mission risk budget "
                f"{mission.max_risk}; this budget only tightens the normal gates"
            )

    def _require_mission(self, mission_id: str) -> Mission:
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise KeyError(f"unknown mission: {mission_id}")
        return mission

    def _require_step(self, step_id: str) -> tuple[MissionStep, Mission]:
        step = self.store.get_step(step_id)
        if step is None:
            raise KeyError(f"unknown mission step: {step_id}")
        mission = self._require_mission(step.mission_id)
        return step, mission

    def _require_run(self, mission: Mission) -> OpportunityRun:
        if not mission.run_id:
            raise MissionError("mission has no backing opportunity run")
        run = self._opportunity_store().get_run(mission.run_id)
        if run is None:
            raise MissionError(f"backing run not found: {mission.run_id}")
        return run

    def _set_status(self, mission: Mission, status: str, note: str) -> None:
        if status not in MISSION_STATUSES:
            raise MissionError(f"unknown mission status: {status}")
        previous = mission.status
        mission.status = status
        self.store.save_mission(mission)
        self._record(
            mission, EVENT_STATUS_CHANGED,
            f"{previous} -> {status}: {note}",
            from_status=previous, to_status=status, note=note,
        )

    def _record(
        self, mission: Mission, event_type: str, message: str, **payload: Any
    ) -> None:
        """Write the durable mission event row plus the JSONL spine entry."""
        payload = {"message": message, **payload}
        self.store.append_mission_event(mission.mission_id, event_type, payload)
        event = make_event(
            event_type=event_type,
            subject_type="mission",
            subject_id=mission.mission_id,
            message=message,
            source="mission-engine",
            metadata=payload,
        )
        self.events.append(event)
        try:
            append_event(event, path=self.events_path)
        except OSError:
            pass
        if self.event_sink is not None:
            self.event_sink(event)


def render_auto_route_promotion_report(report: AutoRoutePromotionReport) -> str:
    """Render explicit auto route promotion without implying execution."""
    mission = report.mission
    request_id = report.approval_request_id or ""
    lines = [
        "Auto route promoted" if report.action != "noop" else "Auto route inspected",
        "Mission: " + mission.mission_id,
    ]
    if request_id:
        lines.append("Approval request: " + request_id)
    lines.extend(
        [
            "AutoPlan id/hash: "
            + (mission.auto_plan_id or "")
            + " / "
            + ((mission.auto_plan_hash or "")[:16]),
            "Envelope: " + (mission.autonomy_envelope or ""),
            "Cognitive budget: " + (mission.cognitive_budget or ""),
            "",
            "Promotion result:",
            "  - promoted route steps: " + str(len(report.promoted_steps)),
            "  - blocked authority placeholders: " + str(len(report.blocked_steps)),
            "  - unpromoted informational steps: " + str(len(report.unpromoted_steps)),
            "  - approval requests are pending",
            "",
            "What was not done:",
            "  - no approvals granted",
            "  - no execution started",
            "  - no receipts fabricated",
        ]
    )
    if request_id:
        lines.extend(
            [
                "",
                "Inspect: opencobalt approvals show " + request_id[:13],
                "Mission: opencobalt missions show " + mission.mission_id[:13],
                "Why: opencobalt why " + mission.mission_id[:13],
            ]
        )
    return "\n".join(lines)
