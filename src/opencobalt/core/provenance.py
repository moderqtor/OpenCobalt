"""Provenance tracing: answer "why does this object exist?" for any id.

Builds a small in-memory lineage graph around one focus id, walking the
existing SQLite stores (opportunity runs, approval requests, execution
plans, receipts, artifacts, outcomes). No new tables, no graph database:
the stored references are the graph.

Lineage shape:

  goal -> track -> opportunity plan -> approval request -> approval step
       -> execution plan -> receipt -> artifact
  evidence supports tracks; outcomes feed back into tracks.

Read-only. Nothing here executes or mutates state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_DB = Path(".opencobalt") / "ledger.db"

# How many recent runs to scan when an id (goal, evidence) has no direct
# index column. Keeps lookups bounded on long-lived ledgers.
_RUN_SCAN_LIMIT = 25


@dataclass
class ProvenanceNode:
    """One object in the lineage graph."""

    node_id: str
    kind: str  # goal / track / evidence / plan / approval / step /
    #            exec_plan / receipt / artifact / outcome
    label: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProvenanceEdge:
    """A directed cause -> effect (or support) relation."""

    source_id: str
    target_id: str
    relation: str


@dataclass
class ProvenanceTrace:
    """The lineage graph around one focus id."""

    focus_id: str
    focus_kind: str
    nodes: list[ProvenanceNode] = field(default_factory=list)
    edges: list[ProvenanceEdge] = field(default_factory=list)

    def get_node(self, node_id: str) -> ProvenanceNode | None:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def add_node(self, node: ProvenanceNode) -> ProvenanceNode:
        existing = self.get_node(node.node_id)
        if existing is not None:
            return existing
        self.nodes.append(node)
        return node

    def add_edge(self, source_id: str, target_id: str, relation: str) -> None:
        for edge in self.edges:
            if (
                edge.source_id == source_id
                and edge.target_id == target_id
                and edge.relation == relation
            ):
                return
        self.edges.append(ProvenanceEdge(source_id, target_id, relation))

    def children(self, node_id: str) -> list[tuple[str, ProvenanceNode]]:
        out: list[tuple[str, ProvenanceNode]] = []
        for edge in self.edges:
            if edge.source_id == node_id:
                node = self.get_node(edge.target_id)
                if node is not None:
                    out.append((edge.relation, node))
        return out

    def roots(self) -> list[ProvenanceNode]:
        targets = {edge.target_id for edge in self.edges}
        return [node for node in self.nodes if node.node_id not in targets]


class ProvenanceBuilder:
    """Resolves any known id into a ProvenanceTrace. Read-only."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _DEFAULT_DB

    # Lazy store accessors keep import cost out of unrelated CLI paths.

    def _opportunity_store(self):
        from .opportunity_store import OpportunityStore

        return OpportunityStore(self.db_path)

    def _approval_store(self):
        from .approval_bridge import ApprovalStore

        return ApprovalStore(self.db_path)

    def _execution_store(self):
        from opencobalt.execution.store import ExecutionStore

        return ExecutionStore(self.db_path)

    # --- Entry point ---

    def trace(self, any_id: str) -> ProvenanceTrace | None:
        """Build the lineage trace around one id, or None if unknown."""
        any_id = any_id.strip()
        if not any_id:
            return None
        resolvers = (
            self._trace_mission,
            self._trace_evolve,
            self._trace_opportunity_side,
            self._trace_approval_side,
            self._trace_outcome,
            self._trace_execution_side,
        )
        for resolver in resolvers:
            trace = resolver(any_id)
            if trace is not None:
                return trace
        return None

    # --- Resolution by id family ---

    def _trace_opportunity_side(self, any_id: str) -> ProvenanceTrace | None:
        store = self._opportunity_store()
        run = None
        kind = None
        if any_id.startswith("otrk"):
            run, kind = store.find_run_for_track(any_id), "track"
        elif any_id.startswith("oplan"):
            run, kind = store.find_run_for_plan(any_id), "plan"
        elif any_id.startswith("orun"):
            run, kind = store.get_run(any_id), "run"
        elif any_id.startswith(("goal", "ev", "hyp")):
            run = self._scan_runs_for_id(store, any_id)
            kind = {"g": "goal", "e": "evidence", "h": "hypothesis"}[any_id[0]]
        if run is None or kind is None:
            return None

        focus_id, focus_kind = any_id, kind
        if kind == "run":
            focus_id, focus_kind = run.goal.goal_id, "goal"
        trace = ProvenanceTrace(focus_id=focus_id, focus_kind=focus_kind)
        track_ids: list[str] | None = None
        if kind == "track":
            track = run.get_track(any_id)
            track_ids = [track.track_id] if track else None
            if track:
                trace.focus_id = track.track_id
        elif kind == "plan":
            for plan in run.plans:
                if plan.plan_id.startswith(any_id):
                    track_ids = [plan.track_id]
                    trace.focus_id = plan.plan_id
        elif kind == "evidence":
            for item in run.evidence:
                if item.evidence_id.startswith(any_id):
                    track_ids = [item.track_id]
                    trace.focus_id = item.evidence_id
        self._add_run_lineage(trace, run, only_tracks=track_ids)
        return trace

    def _trace_mission(self, any_id: str) -> ProvenanceTrace | None:
        if not any_id.startswith(("mis-", "mstp-")):
            return None
        from .mission_engine import MissionStore

        store = MissionStore(self.db_path)
        step = None
        if any_id.startswith("mstp-"):
            step = store.get_step(any_id)
            if step is None:
                return None
            mission = store.get_mission(step.mission_id)
        else:
            mission = store.get_mission(any_id)
        if mission is None:
            return None

        focus_id = step.step_id if step else mission.mission_id
        focus_kind = "mission_step" if step else "mission"
        trace = ProvenanceTrace(focus_id=focus_id, focus_kind=focus_kind)
        trace.add_node(
            ProvenanceNode(
                node_id=mission.mission_id,
                kind="mission",
                label=mission.goal[:80],
                data={
                    "mission_type": mission.mission_type,
                    "status": mission.status,
                    "outcome": mission.outcome,
                },
            )
        )
        if mission.run_id:
            run = self._opportunity_store().get_run(mission.run_id)
            if run is not None:
                only = (
                    [mission.selected_track_id] if mission.selected_track_id else None
                )
                self._add_run_lineage(trace, run, only_tracks=only)
                trace.add_edge(mission.mission_id, run.goal.goal_id, "pursues")
        for mission_step in store.list_steps(mission.mission_id):
            trace.add_node(
                ProvenanceNode(
                    node_id=mission_step.step_id,
                    kind="mission_step",
                    label=mission_step.title[:70],
                    data={
                        "risk_level": mission_step.risk_level,
                        "approval_state": mission_step.approval_state,
                        "execution_state": mission_step.execution_state,
                    },
                )
            )
            trace.add_edge(mission.mission_id, mission_step.step_id, "tracks")
            if mission_step.approval_step_id and trace.get_node(
                mission_step.approval_step_id
            ):
                trace.add_edge(
                    mission_step.step_id, mission_step.approval_step_id, "mirrors"
                )
        return trace

    def _trace_evolve(self, any_id: str) -> ProvenanceTrace | None:
        if not any_id.startswith(("emis", "ecand")):
            return None
        from .evolve import EvolveStore

        store = EvolveStore(self.db_path)
        if any_id.startswith("emis"):
            mission = store.get_mission(any_id)
            if mission is None:
                return None
            trace = ProvenanceTrace(focus_id=mission.mission_id, focus_kind="mission")
            if mission.run_id:
                run = self._opportunity_store().get_run(mission.run_id)
                if run is not None:
                    self._add_run_lineage(trace, run, only_tracks=None)
            self._attach_mission_node(trace, mission, store)
            return trace
        candidate = store.get_candidate(any_id)
        if candidate is None:
            return None
        trace = ProvenanceTrace(focus_id=candidate.candidate_id, focus_kind="candidate")
        if candidate.track_id:
            run = self._opportunity_store().find_run_for_track(candidate.track_id)
            if run is not None:
                self._add_run_lineage(trace, run, only_tracks=[candidate.track_id])
        mission = store.get_mission(candidate.mission_id)
        if mission is not None:
            self._attach_mission_node(trace, mission, store)
        return trace

    def _attach_mission_node(self, trace, mission, store) -> None:
        """Add the mission node plus mission -> candidate -> track edges."""
        trace.add_node(
            ProvenanceNode(
                node_id=mission.mission_id,
                kind="mission",
                label=mission.goal[:80],
                data={"status": mission.status, "run_id": mission.run_id},
            )
        )
        for candidate in store.list_candidates(mission.mission_id):
            in_trace = candidate.track_id and trace.get_node(candidate.track_id)
            if not in_trace and trace.focus_id != candidate.candidate_id:
                continue
            trace.add_node(
                ProvenanceNode(
                    node_id=candidate.candidate_id,
                    kind="candidate",
                    label=candidate.title[:70],
                    data={
                        "candidate_type": candidate.candidate_type,
                        "status": candidate.status,
                        "score_total": candidate.score.total if candidate.score else None,
                        "risk_level": candidate.risk_level,
                    },
                )
            )
            trace.add_edge(mission.mission_id, candidate.candidate_id, "proposed")
            if candidate.track_id and trace.get_node(candidate.track_id):
                trace.add_edge(candidate.candidate_id, candidate.track_id, "realized_as")

    def _trace_approval_side(self, any_id: str) -> ProvenanceTrace | None:
        if not any_id.startswith(("areq", "astp")):
            return None
        store = self._approval_store()
        if any_id.startswith("areq"):
            request = store.get_request(any_id)
            if request is None:
                return None
            focus_id, focus_kind = request.request_id, "approval"
        else:
            found = store.find_step(any_id)
            if found is None:
                return None
            request, step = found
            focus_id, focus_kind = step.step_id, "step"
        trace = ProvenanceTrace(focus_id=focus_id, focus_kind=focus_kind)
        run = self._opportunity_store().find_run_for_track(request.track_id)
        if run is not None:
            self._add_run_lineage(trace, run, only_tracks=[request.track_id])
        else:
            self._add_request_lineage(trace, request, parent_id=None)
        return trace

    def _trace_outcome(self, any_id: str) -> ProvenanceTrace | None:
        if not any_id.startswith("oout"):
            return None
        store = self._opportunity_store()
        match = None
        for outcome in store.list_outcomes(limit=500):
            if outcome["outcome_id"].startswith(any_id):
                match = outcome
                break
        if match is None:
            return None
        trace = ProvenanceTrace(focus_id=match["outcome_id"], focus_kind="outcome")
        run = store.find_run_for_track(match["track_id"])
        if run is not None:
            self._add_run_lineage(trace, run, only_tracks=[match["track_id"]])
        return trace

    def _trace_execution_side(self, any_id: str) -> ProvenanceTrace | None:
        store = self._execution_store()
        receipt = self._find_receipt(store, any_id)
        if receipt is None:
            plan = self._find_exec_plan(store, any_id)
            if plan is not None:
                receipt = next(
                    (r for r in store.list_receipts(limit=500) if r.plan_id == plan.plan_id),
                    None,
                )
                if receipt is None:
                    trace = ProvenanceTrace(focus_id=plan.plan_id, focus_kind="exec_plan")
                    self._add_exec_plan_node(trace, plan)
                    return trace
            else:
                artifact = self._find_artifact(store, any_id)
                if artifact is None:
                    return None
                receipt = next(
                    (
                        r
                        for r in store.list_receipts(limit=500)
                        if artifact.artifact_id in r.artifact_ids
                    ),
                    None,
                )
                if receipt is None:
                    trace = ProvenanceTrace(
                        focus_id=artifact.artifact_id, focus_kind="artifact"
                    )
                    trace.add_node(self._artifact_node(artifact))
                    return trace

        focus_kind = "receipt"
        focus_id = receipt.receipt_id
        if any_id != receipt.receipt_id and not receipt.receipt_id.startswith(any_id):
            # Entered via plan or artifact id; keep that as the focus.
            plan = self._find_exec_plan(store, any_id)
            artifact = self._find_artifact(store, any_id)
            if plan is not None:
                focus_kind, focus_id = "exec_plan", plan.plan_id
            elif artifact is not None:
                focus_kind, focus_id = "artifact", artifact.artifact_id

        # If an approval step produced this receipt, climb to the full chain.
        linked = self._approval_store().find_step_by_receipt(receipt.receipt_id)
        trace = ProvenanceTrace(focus_id=focus_id, focus_kind=focus_kind)
        if linked is not None:
            request, _step = linked
            run = self._opportunity_store().find_run_for_track(request.track_id)
            if run is not None:
                self._add_run_lineage(trace, run, only_tracks=[request.track_id])
            else:
                self._add_request_lineage(trace, request, parent_id=None)
            return trace
        # Standalone execution: receipt -> plan -> artifacts only.
        self._add_receipt_lineage(trace, receipt, parent_id=None)
        return trace

    # --- Lookup helpers (prefix tolerant) ---

    @staticmethod
    def _scan_runs_for_id(store, any_id: str):
        for row in store.list_runs(limit=_RUN_SCAN_LIMIT):
            run = store.get_run(row["run_id"])
            if run is None:
                continue
            if run.goal.goal_id.startswith(any_id):
                return run
            if any(e.evidence_id.startswith(any_id) for e in run.evidence):
                return run
            if any(h.hypothesis_id.startswith(any_id) for h in run.hypotheses):
                return run
        return None

    @staticmethod
    def _find_receipt(store, any_id: str):
        receipt = store.get_receipt(any_id)
        if receipt is not None:
            return receipt
        matches = [
            r for r in store.list_receipts(limit=500) if r.receipt_id.startswith(any_id)
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _find_exec_plan(store, any_id: str):
        plan = store.get_plan(any_id)
        if plan is not None:
            return plan
        matches = [p for p in store.list_plans(limit=500) if p.plan_id.startswith(any_id)]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _find_artifact(store, any_id: str):
        artifact = store.get_artifact(any_id)
        if artifact is not None:
            return artifact
        matches = [
            a for a in store.list_artifacts(limit=500) if a.artifact_id.startswith(any_id)
        ]
        return matches[0] if len(matches) == 1 else None

    # --- Graph assembly ---

    def _add_run_lineage(self, trace, run, *, only_tracks: list[str] | None) -> None:
        goal = run.goal
        trace.add_node(
            ProvenanceNode(
                node_id=goal.goal_id,
                kind="goal",
                label=goal.text[:80],
                data={"goal_class": goal.goal_class, "run_id": run.run_id},
            )
        )
        totals = {s.track_id: s.total for s in run.scores}
        for track in run.tracks:
            if only_tracks is not None and track.track_id not in only_tracks:
                continue
            trace.add_node(
                ProvenanceNode(
                    node_id=track.track_id,
                    kind="track",
                    label=track.name,
                    data={
                        "track_type": track.track_type,
                        "status": track.status,
                        "score_total": totals.get(track.track_id),
                    },
                )
            )
            trace.add_edge(goal.goal_id, track.track_id, "decomposed_into")
            self._attach_candidate_for_track(trace, track.track_id)
            for item in run.evidence:
                if item.track_id != track.track_id:
                    continue
                trace.add_node(
                    ProvenanceNode(
                        node_id=item.evidence_id,
                        kind="evidence",
                        label=item.summary[:70],
                        data={"source_type": item.source_type, "strength": item.strength},
                    )
                )
                trace.add_edge(item.evidence_id, track.track_id, "supports")
            for plan in run.plans:
                if plan.track_id != track.track_id:
                    continue
                trace.add_node(
                    ProvenanceNode(
                        node_id=plan.plan_id,
                        kind="plan",
                        label=f"opportunity plan ({len(plan.steps)} step(s))",
                        data={
                            "risk_level": plan.risk_level,
                            "approval_state": plan.approval_state,
                        },
                    )
                )
                trace.add_edge(track.track_id, plan.plan_id, "planned_as")
                request = self._approval_store().find_request_for_source(track.track_id)
                if request is not None and request.opportunity_plan_id == plan.plan_id:
                    self._add_request_lineage(trace, request, parent_id=plan.plan_id)
            self._add_outcomes(trace, track.track_id)

    def _attach_candidate_for_track(self, trace, track_id: str) -> None:
        """If an evolve candidate backs this track, attach it and its mission."""
        try:
            from .evolve import EvolveStore

            store = EvolveStore(self.db_path)
            candidate = store.find_candidate_for_track(track_id)
            if candidate is None:
                return
            mission = store.get_mission(candidate.mission_id)
            if mission is not None:
                self._attach_mission_node(trace, mission, store)
        except Exception:
            return  # evolve lineage is additive; never break a base trace

    def _add_request_lineage(self, trace, request, *, parent_id: str | None) -> None:
        trace.add_node(
            ProvenanceNode(
                node_id=request.request_id,
                kind="approval",
                label=f"approval request ({len(request.steps)} step(s))",
                data={
                    "state": request.state,
                    "risk_level": request.risk_level,
                    "track_id": request.track_id,
                    "score_total": request.score_total,
                },
            )
        )
        if parent_id is not None:
            trace.add_edge(parent_id, request.request_id, "promoted_to")
        exec_store = self._execution_store()
        for step in request.steps:
            trace.add_node(
                ProvenanceNode(
                    node_id=step.step_id,
                    kind="step",
                    label=step.task[:70],
                    data={
                        "risk_level": step.risk_level,
                        "approval_state": step.approval_state,
                        "approval_required": step.approval_required,
                    },
                )
            )
            trace.add_edge(request.request_id, step.step_id, "contains")
            if step.execution_plan_id:
                plan = exec_store.get_plan(step.execution_plan_id)
                if plan is not None:
                    self._add_exec_plan_node(trace, plan)
                    trace.add_edge(step.step_id, plan.plan_id, "handed_off_as")
            if step.receipt_id:
                receipt = exec_store.get_receipt(step.receipt_id)
                if receipt is not None:
                    self._add_receipt_lineage(
                        trace, receipt, parent_id=step.execution_plan_id or step.step_id
                    )

    def _add_exec_plan_node(self, trace, plan) -> None:
        trace.add_node(
            ProvenanceNode(
                node_id=plan.plan_id,
                kind="exec_plan",
                label=f"execution plan ({plan.runtime})",
                data={
                    "risk_level": plan.risk_level,
                    "dry_run": plan.dry_run,
                    "runtime": plan.runtime,
                },
            )
        )

    def _add_receipt_lineage(self, trace, receipt, *, parent_id: str | None) -> None:
        exec_store = self._execution_store()
        if parent_id is None:
            plan = exec_store.get_plan(receipt.plan_id)
            if plan is not None:
                self._add_exec_plan_node(trace, plan)
                parent_id = plan.plan_id
        trace.add_node(
            ProvenanceNode(
                node_id=receipt.receipt_id,
                kind="receipt",
                label=f"receipt ({receipt.selected_runtime})",
                data={
                    "verification_status": receipt.verification_status,
                    "risk_level": receipt.risk_level,
                    "task": receipt.task[:70],
                },
            )
        )
        if parent_id is not None:
            trace.add_edge(parent_id, receipt.receipt_id, "produced")
        for artifact_id in receipt.artifact_ids:
            artifact = exec_store.get_artifact(artifact_id)
            if artifact is None:
                continue
            trace.add_node(self._artifact_node(artifact))
            trace.add_edge(receipt.receipt_id, artifact.artifact_id, "attests")

    @staticmethod
    def _artifact_node(artifact) -> ProvenanceNode:
        return ProvenanceNode(
            node_id=artifact.artifact_id,
            kind="artifact",
            label=f"{artifact.artifact_type} ({artifact.size_bytes} bytes)",
            data={"path": artifact.path, "sha256": artifact.sha256},
        )

    def _add_outcomes(self, trace, track_id: str) -> None:
        for outcome in self._opportunity_store().list_outcomes(
            track_id=track_id, limit=20
        ):
            trace.add_node(
                ProvenanceNode(
                    node_id=outcome["outcome_id"],
                    kind="outcome",
                    label=f"outcome: {outcome['outcome']}",
                    data={
                        "receipt_id": outcome["receipt_id"],
                        "notes": outcome["notes"],
                    },
                )
            )
            source = outcome["receipt_id"] or track_id
            relation = "informed" if outcome["receipt_id"] else "recorded_for"
            if outcome["receipt_id"] and trace.get_node(outcome["receipt_id"]) is None:
                source, relation = track_id, "recorded_for"
            trace.add_edge(source, outcome["outcome_id"], relation)


def render_trace_lines(trace: ProvenanceTrace) -> list[str]:
    """Render a trace as indented plain-text lines (CLI/TUI friendly)."""
    lines: list[str] = []
    seen: set[str] = set()

    def describe(node: ProvenanceNode) -> str:
        bits = [f"{node.kind} {node.node_id[:14]}"]
        if node.label:
            bits.append(f'"{node.label}"')
        detail = []
        for key in (
            "goal_class", "track_type", "candidate_type", "status", "score_total",
            "risk_level", "approval_state", "state", "dry_run",
            "verification_status", "source_type", "strength",
        ):
            value = node.data.get(key)
            if value is None:
                continue
            if isinstance(value, float):
                value = f"{value:.3f}"
            detail.append(f"{key}={value}")
        if detail:
            bits.append(f"[{' '.join(detail)}]")
        if node.node_id == trace.focus_id:
            bits.append("<-- you asked about this")
        return "  ".join(bits)

    def walk(node: ProvenanceNode, depth: int, relation: str | None) -> None:
        if node.node_id in seen:
            return
        seen.add(node.node_id)
        prefix = "  " * depth
        arrow = f"{relation} -> " if relation else ""
        lines.append(f"{prefix}{arrow}{describe(node)}")
        # Support edges point evidence -> track; render them nested under
        # the supported node so evidence reads in context.
        for edge in trace.edges:
            if edge.target_id == node.node_id and edge.relation == "supports":
                source = trace.get_node(edge.source_id)
                if source is not None:
                    walk(source, depth + 1, "supported_by")
        for child_relation, child in trace.children(node.node_id):
            walk(child, depth + 1, child_relation)

    for root in trace.roots():
        walk(root, 0, None)
    for node in trace.nodes:  # disconnected leftovers, if any
        walk(node, 0, None)
    return lines
