"""Approval Bridge: promote opportunity plans into approvable execution.

This module closes the gap between what the Opportunity Engine proposes and
what the Execution Engine runs:

  Opportunity Engine proposes -> Approval Bridge authorizes ->
  Execution Engine runs -> receipts verify -> outcomes teach scoring.

Nothing here starts a subprocess. ApprovalBridge.run_steps hands approved
steps to the existing ExecutionEngine, which still enforces the central
policy gate: dry-run is always the default, green/yellow execution needs
--execute, red needs --execute plus --yes, black stays blocked.

Approval states:
  pending     created, awaiting a human decision (or blocked if black risk)
  approved    explicitly approved (or auto-approved green if policy allows)
  rejected    explicitly declined
  executed    handed to the execution engine and the run succeeded
  failed      handed to the execution engine and the run failed
  superseded  replaced by a newer approval request for the same source
  expired     wait bound elapsed without a decision
  stale       live provider session is gone (restart, crash, or cancellation)
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
    from opencobalt.execution.engine import ExecutionEngine, ExecutionOutcome

    from .opportunity_engine import OpportunityPlan, OpportunityRun, OpportunityTrack
    from .opportunity_store import OpportunityStore

APPROVAL_STATES = (
    "pending",
    "approved",
    "rejected",
    "executed",
    "failed",
    "superseded",
    "expired",
    "stale",
)

SOURCE_TYPES = (
    "opportunity_track",
    "opportunity_plan",
    "delegation_node",
    "auto_route",
    "acp_permission",
)

EVENT_REQUEST_CREATED = "approval.request_created"
EVENT_REQUEST_SUPERSEDED = "approval.request_superseded"
EVENT_STEP_APPROVED = "approval.step_approved"
EVENT_STEP_REJECTED = "approval.step_rejected"
EVENT_STEP_EXECUTED = "approval.step_executed"
EVENT_STEP_FAILED = "approval.step_failed"
EVENT_STEP_EXPIRED = "approval.step_expired"
EVENT_STEP_STALE = "approval.step_stale"

_DEFAULT_DB = Path(".opencobalt") / "ledger.db"
_DEFAULT_EVENTS_PATH = Path(".opencobalt") / "events" / "approval.jsonl"

_RISK_SCOPES = {"green": "read", "yellow": "write", "red": "write", "black": "read"}
_RISK_ORDER = {"green": 0, "yellow": 1, "red": 2, "black": 3}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ApprovalError(Exception):
    """Base error for approval bridge failures."""


class BlockedStepError(ApprovalError):
    """Black-risk steps cannot be approved or executed."""


class NotApprovedError(ApprovalError):
    """A step must be approved before it can be handed to execution."""


class InvalidApprovalTransitionError(ApprovalError):
    """The requested decision is not valid for the current approval state."""


class StaleApprovalError(ApprovalError):
    """The live provider session that owned this approval is gone."""


@dataclass
class ApprovalStep:
    """One approvable unit of work inside an approval request."""

    step_id: str
    request_id: str
    source_type: str
    source_id: str
    task: str
    risk_level: str = "green"
    permission_scope: str = "read"
    approval_required: bool = False
    approval_state: str = "pending"
    execution_plan_id: str | None = None
    receipt_id: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.risk_level == "black"

    def touch(self) -> None:
        self.updated_at = _now_iso()


@dataclass
class ApprovalDecision:
    """A recorded human (or policy) decision on a request or step."""

    decision_id: str
    request_id: str
    step_id: str | None
    decision: str  # approved / rejected
    reason: str = ""
    decided_by: str = "human"
    created_at: str = field(default_factory=_now_iso)


@dataclass
class ApprovalPolicy:
    """What the bridge may decide without a human.

    Only green (read-only) steps may ever be auto-approved, and only when
    auto_approve_green is set. Yellow and red always require an explicit
    decision; black is blocked outright and has no override here.
    """

    auto_approve_green: bool = True


@dataclass
class ApprovalRequest:
    """An opportunity track/plan promoted into approvable steps."""

    request_id: str
    source_type: str
    source_id: str
    run_id: str
    goal_id: str
    track_id: str
    opportunity_plan_id: str
    goal_text: str = ""
    track_name: str = ""
    score_total: float | None = None
    risk_level: str = "green"
    state: str = "pending"
    steps: list[ApprovalStep] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    delegation_plan_id: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_step(self, step_id: str) -> ApprovalStep | None:
        for step in self.steps:
            if step.step_id == step_id or step.step_id.startswith(step_id):
                return step
        return None

    def refresh_state(self) -> str:
        """Aggregate request state from step states. Superseded is sticky."""
        if self.state == "superseded":
            return self.state
        states = {step.approval_state for step in self.steps}
        if "pending" in states:
            self.state = "pending"
        elif "approved" in states:
            self.state = "approved"
        elif "failed" in states:
            self.state = "failed"
        elif "executed" in states:
            self.state = "executed"
        elif "stale" in states:
            self.state = "stale"
        elif "expired" in states:
            self.state = "expired"
        else:
            self.state = "rejected"
        self.updated_at = _now_iso()
        return self.state

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [asdict(s) for s in self.steps]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRequest:
        data = dict(data)
        steps = [ApprovalStep(**s) for s in data.pop("steps", [])]
        return cls(steps=steps, **data)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    request_id   TEXT PRIMARY KEY,
    source_type  TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    track_id     TEXT NOT NULL,
    state        TEXT NOT NULL,
    risk_level   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    request_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_steps (
    step_id           TEXT PRIMARY KEY,
    request_id        TEXT NOT NULL,
    task              TEXT NOT NULL,
    risk_level        TEXT NOT NULL,
    approval_state    TEXT NOT NULL,
    approval_required INTEGER NOT NULL,
    execution_plan_id TEXT,
    receipt_id        TEXT,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_decisions (
    decision_id TEXT PRIMARY KEY,
    request_id  TEXT NOT NULL,
    step_id     TEXT,
    decision    TEXT NOT NULL,
    reason      TEXT,
    decided_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


class ApprovalStore:
    """SQLite persistence for approval requests, steps, and decisions.

    The request JSON is the source of truth; approval_steps mirrors scalar
    columns so provenance and the UI can query by receipt or plan id without
    decoding JSON.
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

    def save_request(self, request: ApprovalRequest) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO approval_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    request.request_id,
                    request.source_type,
                    request.source_id,
                    request.run_id,
                    request.track_id,
                    request.state,
                    request.risk_level,
                    request.created_at,
                    request.updated_at,
                    json.dumps(request.to_dict(), sort_keys=True),
                ),
            )
            conn.execute(
                "DELETE FROM approval_steps WHERE request_id = ?",
                (request.request_id,),
            )
            for step in request.steps:
                conn.execute(
                    "INSERT INTO approval_steps VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        step.step_id,
                        request.request_id,
                        step.task,
                        step.risk_level,
                        step.approval_state,
                        int(step.approval_required),
                        step.execution_plan_id,
                        step.receipt_id,
                        step.updated_at,
                    ),
                )

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT request_json FROM approval_requests "
                "WHERE request_id = ? OR request_id LIKE ?",
                (request_id, f"{request_id}%"),
            ).fetchone()
        return ApprovalRequest.from_dict(json.loads(row["request_json"])) if row else None

    def list_requests(
        self,
        *,
        state: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
    ) -> list[ApprovalRequest]:
        sql = "SELECT request_json FROM approval_requests"
        clauses: list[str] = []
        params: list[Any] = []
        if state:
            clauses.append("state = ?")
            params.append(state)
        if source_type:
            clauses.append("source_type = ?")
            params.append(source_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [ApprovalRequest.from_dict(json.loads(r["request_json"])) for r in rows]

    def find_request_for_source(self, source_id: str) -> ApprovalRequest | None:
        """Latest non-superseded request for a track or opportunity plan."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT request_json FROM approval_requests "
                "WHERE (source_id = ? OR source_id LIKE ? "
                "       OR track_id = ? OR track_id LIKE ?) "
                "AND state != 'superseded' "
                "ORDER BY created_at DESC LIMIT 1",
                (source_id, f"{source_id}%", source_id, f"{source_id}%"),
            ).fetchone()
        return ApprovalRequest.from_dict(json.loads(row["request_json"])) if row else None

    def find_step(self, step_id: str) -> tuple[ApprovalRequest, ApprovalStep] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT request_id, step_id FROM approval_steps "
                "WHERE step_id = ? OR step_id LIKE ?",
                (step_id, f"{step_id}%"),
            ).fetchone()
        if row is None:
            return None
        request = self.get_request(row["request_id"])
        if request is None:
            return None
        step = request.get_step(row["step_id"])
        return (request, step) if step else None

    def find_step_by_receipt(
        self, receipt_id: str
    ) -> tuple[ApprovalRequest, ApprovalStep] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT request_id, step_id FROM approval_steps "
                "WHERE receipt_id = ? OR receipt_id LIKE ?",
                (receipt_id, f"{receipt_id}%"),
            ).fetchone()
        if row is None:
            return None
        request = self.get_request(row["request_id"])
        if request is None:
            return None
        step = request.get_step(row["step_id"])
        return (request, step) if step else None

    def find_step_by_execution_plan(
        self, execution_plan_id: str
    ) -> tuple[ApprovalRequest, ApprovalStep] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT request_id, step_id FROM approval_steps "
                "WHERE execution_plan_id = ? OR execution_plan_id LIKE ?",
                (execution_plan_id, f"{execution_plan_id}%"),
            ).fetchone()
        if row is None:
            return None
        request = self.get_request(row["request_id"])
        if request is None:
            return None
        step = request.get_step(row["step_id"])
        return (request, step) if step else None

    def record_decision(self, decision: ApprovalDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO approval_decisions VALUES (?,?,?,?,?,?,?)",
                (
                    decision.decision_id,
                    decision.request_id,
                    decision.step_id,
                    decision.decision,
                    decision.reason,
                    decision.decided_by,
                    decision.created_at,
                ),
            )

    def list_decisions(self, request_id: str) -> list[ApprovalDecision]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM approval_decisions WHERE request_id = ? "
                "ORDER BY created_at",
                (request_id,),
            ).fetchall()
        return [ApprovalDecision(**dict(r)) for r in rows]

    def count_pending(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM approval_requests WHERE state = 'pending'"
            ).fetchone()
        return int(row["n"])


@dataclass
class StepRunReport:
    """What happened when one approval step was handed to execution."""

    step: ApprovalStep
    action: str  # executed / dry_run / refused / skipped / blocked
    reason: str = ""
    outcome: Any = None  # ExecutionOutcome when the engine was invoked


class ApprovalBridge:
    """Promotes opportunity tracks/plans into approval requests and hands
    approved steps to the existing execution engine. Never executes directly."""

    def __init__(
        self,
        *,
        store: ApprovalStore | None = None,
        db_path: Path | None = None,
        policy: ApprovalPolicy | None = None,
        events_path: Path | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.store = store or ApprovalStore(db_path)
        self.policy = policy or ApprovalPolicy()
        self.events_path = events_path or _DEFAULT_EVENTS_PATH
        self.event_sink = event_sink
        self.events: list[dict[str, Any]] = []

    # --- Promotion ---

    def promote(
        self,
        run: OpportunityRun,
        source_id: str,
        *,
        new: bool = False,
        opportunity_store: OpportunityStore | None = None,
    ) -> tuple[ApprovalRequest, bool]:
        """Promote a track or opportunity plan into an approval request.

        Returns (request, created). An existing non-superseded request for
        the same source is reused unless new=True, which supersedes it.
        If the track has no plan yet, a plan is built (planning only) and
        persisted through the opportunity store when one is provided.
        """
        track, plan = self._resolve_source(
            run, source_id, opportunity_store=opportunity_store
        )

        existing = self.store.find_request_for_source(track.track_id)
        if existing is not None:
            if not new:
                return existing, False
            existing.state = "superseded"
            existing.updated_at = _now_iso()
            self.store.save_request(existing)
            self._emit(
                EVENT_REQUEST_SUPERSEDED, existing.request_id,
                f"request superseded for track {track.track_id}",
                track_id=track.track_id,
            )

        source_type = (
            "opportunity_plan" if source_id.startswith("oplan") else "opportunity_track"
        )
        score = run.score_for(track.track_id)
        request = ApprovalRequest(
            request_id=_uid("areq"),
            source_type=source_type,
            source_id=plan.plan_id if source_type == "opportunity_plan" else track.track_id,
            run_id=run.run_id,
            goal_id=run.goal.goal_id,
            track_id=track.track_id,
            opportunity_plan_id=plan.plan_id,
            goal_text=run.goal.text,
            track_name=track.name,
            score_total=score.total if score else None,
            risk_level=plan.risk_level,
            evidence_ids=list(track.evidence_ids),
            delegation_plan_id=plan.delegation.get("plan_id"),
        )
        for raw in plan.steps:
            request.steps.append(self._make_step(request, raw))
        request.refresh_state()
        self.store.save_request(request)
        self._emit(
            EVENT_REQUEST_CREATED, request.request_id,
            f"approval request created for {track.name} "
            f"({len(request.steps)} step(s), risk {request.risk_level})",
            run_id=run.run_id, track_id=track.track_id,
            opportunity_plan_id=plan.plan_id, state=request.state,
        )
        return request, True

    def promote_auto_route(
        self,
        *,
        mission_id: str,
        auto_plan_id: str,
        auto_plan_hash: str,
        goal: str,
        intent: str,
        envelope: str,
        cognitive_budget: str,
        route_steps: list[dict[str, Any]],
        new: bool = False,
    ) -> tuple[ApprovalRequest, bool]:
        """Promote durable auto route steps into an explicit approval request.

        Auto route promotion deliberately disables green auto-approval. These
        steps are pending placeholders until a human or later policy-gated
        command approves them. Nothing executes here.
        """
        existing = self.store.find_request_for_source(mission_id)
        if existing is not None:
            if not new:
                return existing, False
            existing.state = "superseded"
            existing.updated_at = _now_iso()
            self.store.save_request(existing)
            self._emit(
                EVENT_REQUEST_SUPERSEDED,
                existing.request_id,
                f"auto route request superseded for mission {mission_id}",
                mission_id=mission_id,
                auto_plan_id=auto_plan_id,
            )

        request = ApprovalRequest(
            request_id=_uid("areq"),
            source_type="auto_route",
            source_id=mission_id,
            run_id=mission_id,
            goal_id=auto_plan_id,
            track_id=mission_id,
            opportunity_plan_id=auto_plan_id,
            goal_text=goal,
            track_name="Auto route promotion",
            risk_level=_max_risk(step["risk_level"] for step in route_steps),
            metadata={
                "mission_id": mission_id,
                "auto_plan_id": auto_plan_id,
                "auto_plan_hash": auto_plan_hash,
                "intent": intent,
                "envelope": envelope,
                "cognitive_budget": cognitive_budget,
                "promotion_source": "auto_route",
            },
        )
        for raw in route_steps:
            risk = raw["risk_level"]
            request.steps.append(
                ApprovalStep(
                    step_id=_uid("astp"),
                    request_id=request.request_id,
                    source_type="auto_route",
                    source_id=mission_id,
                    task=raw["task"],
                    risk_level=risk,
                    permission_scope=_RISK_SCOPES.get(risk, "read"),
                    approval_required=True,
                    approval_state="pending",
                    metadata={
                        "mission_id": mission_id,
                        "auto_plan_id": auto_plan_id,
                        "auto_plan_hash": auto_plan_hash,
                        "route_mission_step_id": raw["route_mission_step_id"],
                        "route_step_order": raw["route_step_order"],
                        "route_step_primitive": raw["route_step_primitive"],
                        "route_step_why": raw["route_step_why"],
                        "promotion_classification": raw["promotion_classification"],
                        "promotion_reason": raw["promotion_reason"],
                        "expected_receipt_description": raw[
                            "expected_receipt_description"
                        ],
                        "execution_primitive": raw["execution_primitive"],
                        "required_approval_boundary": raw[
                            "required_approval_boundary"
                        ],
                        "blocked_authority": list(raw["blocked_authority"]),
                        "auto_approved": False,
                        "blocked": risk == "black",
                    },
                )
            )
        request.refresh_state()
        self.store.save_request(request)
        self._emit(
            EVENT_REQUEST_CREATED,
            request.request_id,
            f"auto route approval request created for mission {mission_id[:13]} "
            f"({len(request.steps)} step(s), risk {request.risk_level})",
            mission_id=mission_id,
            auto_plan_id=auto_plan_id,
            state=request.state,
        )
        return request, True

    def _resolve_source(
        self,
        run: OpportunityRun,
        source_id: str,
        *,
        opportunity_store: OpportunityStore | None,
    ) -> tuple[OpportunityTrack, OpportunityPlan]:
        plan = None
        for candidate in run.plans:
            if candidate.plan_id == source_id or candidate.plan_id.startswith(source_id):
                plan = candidate
                break
        if plan is not None:
            track = run.get_track(plan.track_id)
            if track is None:
                raise KeyError(f"plan {plan.plan_id} references unknown track")
            return track, plan

        track = run.get_track(source_id)
        if track is None:
            raise KeyError(f"no track or plan matches: {source_id}")
        if track.plan_id:
            for candidate in run.plans:
                if candidate.plan_id == track.plan_id:
                    return track, candidate
        # Build the plan now (planning only -- nothing executes).
        from .opportunity_engine import build_opportunity_plan

        plan = build_opportunity_plan(track, run.goal)
        track.plan_id = plan.plan_id
        track.status = "planned"
        run.plans.append(plan)
        if opportunity_store is not None:
            opportunity_store.save_run(run)
        return track, plan

    def _make_step(self, request: ApprovalRequest, raw: dict[str, Any]) -> ApprovalStep:
        risk = raw.get("risk_level", "green")
        auto_approved = risk == "green" and self.policy.auto_approve_green
        step = ApprovalStep(
            step_id=_uid("astp"),
            request_id=request.request_id,
            source_type=request.source_type,
            source_id=request.source_id,
            task=raw.get("description", ""),
            risk_level=risk,
            permission_scope=_RISK_SCOPES.get(risk, "read"),
            approval_required=risk != "green",
            approval_state="approved" if auto_approved else "pending",
            metadata={"blocked": risk == "black", "auto_approved": auto_approved},
        )
        return step

    # --- Decisions ---

    def approve(
        self,
        request_id: str,
        *,
        step_id: str | None = None,
        decided_by: str = "human",
        reason: str = "",
    ) -> list[ApprovalStep]:
        """Approve one step or every approvable step of a request.

        Black-risk steps cannot be approved: targeting one directly raises
        BlockedStepError; whole-request approval skips them.
        """
        request = self._require_request(request_id)
        targets = self._target_steps(request, step_id)
        if step_id is not None and targets and targets[0].blocked:
            raise BlockedStepError(
                f"step {targets[0].step_id} is black-risk and cannot be approved"
            )
        approved: list[ApprovalStep] = []
        for step in targets:
            if step.blocked or step.approval_state not in ("pending", "rejected"):
                continue
            step.approval_state = "approved"
            step.touch()
            approved.append(step)
            self.store.record_decision(
                ApprovalDecision(
                    decision_id=_uid("adec"),
                    request_id=request.request_id,
                    step_id=step.step_id,
                    decision="approved",
                    reason=reason,
                    decided_by=decided_by,
                )
            )
            self._emit(
                EVENT_STEP_APPROVED, step.step_id,
                f"step approved ({step.risk_level}): {step.task[:80]}",
                request_id=request.request_id, decided_by=decided_by,
            )
        request.refresh_state()
        self.store.save_request(request)
        return approved

    def reject(
        self,
        request_id: str,
        *,
        step_id: str | None = None,
        decided_by: str = "human",
        reason: str = "",
    ) -> list[ApprovalStep]:
        """Reject one step or every still-decidable step of a request."""
        request = self._require_request(request_id)
        rejected: list[ApprovalStep] = []
        for step in self._target_steps(request, step_id):
            if step.approval_state in ("executed", "failed"):
                continue
            step.approval_state = "rejected"
            step.touch()
            rejected.append(step)
            self.store.record_decision(
                ApprovalDecision(
                    decision_id=_uid("adec"),
                    request_id=request.request_id,
                    step_id=step.step_id,
                    decision="rejected",
                    reason=reason,
                    decided_by=decided_by,
                )
            )
            self._emit(
                EVENT_STEP_REJECTED, step.step_id,
                f"step rejected: {step.task[:80]}",
                request_id=request.request_id, reason=reason,
            )
        request.refresh_state()
        self.store.save_request(request)
        return rejected

    def decide_pending(
        self,
        request_id: str,
        *,
        decision: str,
        step_id: str | None = None,
        decided_by: str = "human",
        reason: str = "",
        decision_kind: str | None = None,
    ) -> list[ApprovalStep]:
        """Apply one strict pending-only decision. Duplicate or terminal states fail."""
        if decision not in {"approved", "rejected"}:
            raise InvalidApprovalTransitionError(f"unsupported decision: {decision}")
        request = self._require_request(request_id)
        if request.state in {"superseded", "stale", "expired"}:
            raise StaleApprovalError(
                f"approval {request.request_id} is {request.state} and cannot be decided"
            )
        targets = self._target_steps(request, step_id)
        decided: list[ApprovalStep] = []
        for step in targets:
            if step.blocked and decision == "approved":
                raise BlockedStepError(
                    f"step {step.step_id} is black-risk and cannot be approved"
                )
            if step.approval_state in {"stale", "expired", "superseded"}:
                raise StaleApprovalError(
                    f"step {step.step_id} is {step.approval_state} and cannot be decided"
                )
            if step.approval_state != "pending":
                raise InvalidApprovalTransitionError(
                    f"step {step.step_id} is {step.approval_state}, not pending"
                )
            if decision == "approved":
                step.approval_state = "approved"
                step.metadata = {
                    **step.metadata,
                    "decision_kind": decision_kind or "allow_once",
                    "decision_source": decided_by,
                }
                event = EVENT_STEP_APPROVED
                message = f"step approved ({step.risk_level}): {step.task[:80]}"
            else:
                step.approval_state = "rejected"
                step.metadata = {
                    **step.metadata,
                    "decision_kind": "deny",
                    "decision_source": decided_by,
                }
                event = EVENT_STEP_REJECTED
                message = f"step rejected: {step.task[:80]}"
            step.touch()
            decided.append(step)
            self.store.record_decision(
                ApprovalDecision(
                    decision_id=_uid("adec"),
                    request_id=request.request_id,
                    step_id=step.step_id,
                    decision=decision,
                    reason=reason,
                    decided_by=decided_by,
                )
            )
            self._emit(
                event,
                step.step_id,
                message,
                request_id=request.request_id,
                decided_by=decided_by,
                decision_kind=step.metadata.get("decision_kind"),
            )
        if not decided:
            raise InvalidApprovalTransitionError("no pending step could be decided")
        request.refresh_state()
        self.store.save_request(request)
        return decided

    def mark_terminal(
        self,
        request_id: str,
        *,
        state: str,
        step_id: str | None = None,
        reason: str = "",
        decided_by: str = "runtime",
    ) -> list[ApprovalStep]:
        """Move pending steps to expired or stale. Already-terminal steps are skipped."""
        if state not in {"expired", "stale"}:
            raise InvalidApprovalTransitionError(f"unsupported terminal state: {state}")
        request = self._require_request(request_id)
        changed: list[ApprovalStep] = []
        for step in self._target_steps(request, step_id):
            if step.approval_state != "pending":
                continue
            step.approval_state = state
            step.metadata = {
                **step.metadata,
                "terminal_reason": reason,
                "decision_source": decided_by,
            }
            step.touch()
            changed.append(step)
            event = EVENT_STEP_EXPIRED if state == "expired" else EVENT_STEP_STALE
            self._emit(
                event,
                step.step_id,
                f"step {state}: {step.task[:80]}",
                request_id=request.request_id,
                reason=reason,
                decided_by=decided_by,
            )
        request.refresh_state()
        self.store.save_request(request)
        return changed

    # --- Execution handoff ---

    def run_steps(
        self,
        request_id: str,
        *,
        engine: ExecutionEngine,
        step_id: str | None = None,
        runtime: str | None = None,
        execute: bool = False,
        approved: bool = False,
        rerun: bool = False,
    ) -> list[StepRunReport]:
        """Hand approved steps to the execution engine, one receipt each.

        The engine's policy gate stays fully in charge: dry-run unless
        execute=True, red risk additionally needs approved=True (--yes),
        black risk never runs. Unapproved steps are refused, already
        executed steps are skipped unless rerun=True.
        """
        request = self._require_request(request_id)
        reports: list[StepRunReport] = []
        for step in self._target_steps(request, step_id):
            report = self._run_one(
                request, step,
                engine=engine, runtime=runtime,
                execute=execute, approved=approved, rerun=rerun,
            )
            reports.append(report)
        request.refresh_state()
        self.store.save_request(request)
        return reports

    def _run_one(
        self,
        request: ApprovalRequest,
        step: ApprovalStep,
        *,
        engine: ExecutionEngine,
        runtime: str | None,
        execute: bool,
        approved: bool,
        rerun: bool,
    ) -> StepRunReport:
        if step.blocked:
            return StepRunReport(
                step=step, action="blocked",
                reason="black-risk steps are blocked; there is no override",
            )
        if step.approval_state == "executed" and not rerun:
            return StepRunReport(
                step=step, action="skipped",
                reason="already executed; pass --rerun to run again",
            )
        if step.approval_state not in ("approved", "executed", "failed"):
            return StepRunReport(
                step=step, action="refused",
                reason=(
                    "step is not approved; run: opencobalt approvals approve "
                    f"{request.request_id[:13]} --step {step.step_id[:13]}"
                ),
            )

        outcome: ExecutionOutcome = engine.run_task(
            step.task,
            runtime=runtime,
            execute=execute,
            approved=approved,
            approval_id=request.request_id,
            approval_step_id=step.step_id,
        )
        step.execution_plan_id = outcome.plan.plan_id
        step.receipt_id = outcome.receipt.receipt_id
        step.touch()

        if outcome.executed:
            succeeded = outcome.result is not None and outcome.result.status == "succeeded"
            step.approval_state = "executed" if succeeded else "failed"
            event = EVENT_STEP_EXECUTED if succeeded else EVENT_STEP_FAILED
            self._emit(
                event, step.step_id,
                f"step {'executed' if succeeded else 'failed'}: {step.task[:80]}",
                request_id=request.request_id,
                receipt_id=step.receipt_id,
                execution_plan_id=step.execution_plan_id,
            )
            return StepRunReport(
                step=step,
                action="executed",
                reason=outcome.policy.reason,
                outcome=outcome,
            )
        action = "dry_run" if outcome.plan.dry_run else "refused"
        return StepRunReport(
            step=step, action=action, reason=outcome.policy.reason, outcome=outcome
        )

    # --- Helpers ---

    def _require_request(self, request_id: str) -> ApprovalRequest:
        request = self.store.get_request(request_id)
        if request is None:
            raise KeyError(f"unknown approval request: {request_id}")
        return request

    def _target_steps(
        self, request: ApprovalRequest, step_id: str | None
    ) -> list[ApprovalStep]:
        if step_id is None:
            return list(request.steps)
        step = request.get_step(step_id)
        if step is None:
            raise KeyError(f"unknown step: {step_id}")
        return [step]

    def _emit(self, event_type: str, subject_id: str, message: str, **metadata: Any) -> None:
        event = make_event(
            event_type=event_type,
            subject_type="approval",
            subject_id=subject_id,
            message=message,
            source="approval-bridge",
            metadata=metadata,
        )
        self.events.append(event)
        try:
            append_event(event, path=self.events_path)
        except OSError:
            pass
        if self.event_sink is not None:
            self.event_sink(event)


def _max_risk(risks: Any) -> str:
    ordered = list(risks)
    if not ordered:
        return "green"
    return max(ordered, key=lambda risk: _RISK_ORDER.get(str(risk), 0))
