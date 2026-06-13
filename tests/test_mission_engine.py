"""Tests for Mission State Machine v1 (core/mission_engine.py).

Every test isolates SQLite under tmp_path and chdirs there so the JSONL
event spines of the delegated engines also land in the throwaway
directory. Execution uses the noop adapter only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from opencobalt.core.approval_bridge import BlockedStepError
from opencobalt.core.mission_engine import (
    Mission,
    MissionEngine,
    MissionError,
    MissionStore,
    RiskBudgetExceededError,
    classify_mission_type,
)
from opencobalt.core.opportunity_engine import (
    OpportunityGoal,
    OpportunityPlan,
    OpportunityRun,
    OpportunityTrack,
)
from opencobalt.core.opportunity_store import OpportunityStore


@pytest.fixture
def env(tmp_path: Path, monkeypatch) -> dict:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("# TODO: improve\n", encoding="utf-8")
    db = tmp_path / "ledger.db"
    return {"db": db, "engine": MissionEngine(root=tmp_path, db_path=db)}


def _make_run_with_steps(
    db: Path, steps_spec: list[tuple[str, str]]
) -> tuple[OpportunityRun, OpportunityTrack, OpportunityPlan]:
    """Persist a minimal opportunity run with one planned track whose plan
    steps carry explicit risk levels (so risk paths are deterministic)."""
    goal = OpportunityGoal(
        goal_id="goal-000000000001", text="custom test goal", goal_class="strategy"
    )
    run = OpportunityRun(run_id="orun-000000000001", goal=goal)
    track = OpportunityTrack(
        track_id="otrk-000000000001",
        goal_id=goal.goal_id,
        name="custom track",
        track_type="strategy",
        status="scored",
    )
    run.tracks.append(track)
    order = {"green": 0, "yellow": 1, "red": 2, "black": 3}
    worst = max((risk for _, risk in steps_spec), key=lambda r: order[r])
    plan = OpportunityPlan(
        plan_id="oplan-000000000001",
        track_id=track.track_id,
        goal_id=goal.goal_id,
        delegation={},
        steps=[
            {
                "description": description,
                "risk_level": risk,
                "approval_required": risk in ("red", "black"),
            }
            for description, risk in steps_spec
        ],
        risk_level=worst,
        approval_state="not_required" if worst == "green" else "pending",
    )
    track.plan_id = plan.plan_id
    track.status = "planned"
    run.plans.append(plan)
    OpportunityStore(db).save_run(run)
    return run, track, plan


def _make_mission_at_plan_proposed(
    db: Path,
    run: OpportunityRun,
    track: OpportunityTrack,
    plan: OpportunityPlan,
    *,
    max_risk: str = "red",
) -> Mission:
    mission = Mission(
        mission_id="mis-000000000001",
        goal=run.goal.text,
        status="plan_proposed",
        max_risk=max_risk,
        run_id=run.run_id,
        selected_track_id=track.track_id,
        active_plan_id=plan.plan_id,
    )
    MissionStore(db).save_mission(mission)
    return mission


def _promote(engine: MissionEngine, mission: Mission):
    report = engine.advance(mission.mission_id)
    assert report.action == "promoted"
    return report.steps


class TestMissionPersistence:
    def test_mission_creation_persists_to_sqlite(self, env) -> None:
        mission = env["engine"].start_mission("improve code quality and test coverage")
        # A brand-new store instance against the same file sees the mission.
        reloaded = MissionStore(env["db"]).get_mission(mission.mission_id)
        assert reloaded is not None
        assert reloaded.goal == "improve code quality and test coverage"
        assert reloaded.status == "opportunities_generated"
        assert reloaded.run_id == mission.run_id

    def test_mission_state_survives_process_restart(self, env) -> None:
        mission = env["engine"].start_mission("improve code quality and test coverage")
        env["engine"].advance(mission.mission_id)
        env["engine"].advance(mission.mission_id)

        # Fresh engine simulates a new process: nothing cached in memory.
        fresh = MissionEngine(root=Path("."), db_path=env["db"])
        reloaded = fresh.store.get_mission(mission.mission_id)
        assert reloaded is not None
        assert reloaded.status == "awaiting_approval"
        assert reloaded.selected_track_id is not None
        assert fresh.store.list_steps(reloaded.mission_id)
        assert fresh.store.list_mission_events(reloaded.mission_id)

    def test_mission_events_are_append_only(self, env) -> None:
        mission = env["engine"].start_mission("improve code quality and test coverage")
        events = env["engine"].store.list_mission_events(mission.mission_id)
        assert events, "discovery must leave durable mission events"

        with sqlite3.connect(env["db"]) as conn:
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(
                    "UPDATE mission_events SET event_type = 'tampered' "
                    "WHERE event_id = ?",
                    (events[0]["event_id"],),
                )
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(
                    "DELETE FROM mission_events WHERE event_id = ?",
                    (events[0]["event_id"],),
                )
        # Still intact afterwards.
        unchanged = env["engine"].store.list_mission_events(mission.mission_id)
        assert unchanged[0]["event_type"] == events[0]["event_type"]


class TestDiscoveryAndAdvance:
    def test_start_links_opportunity_discovery(self, env) -> None:
        mission = env["engine"].start_mission("improve code quality and test coverage")
        assert mission.mission_type == "opportunity"
        run = OpportunityStore(env["db"]).get_run(mission.run_id)
        assert run is not None
        assert run.tracks and run.evidence and run.scores
        event_types = {
            e["event_type"]
            for e in env["engine"].store.list_mission_events(mission.mission_id)
        }
        assert "mission.discovery_linked" in event_types

    def test_start_never_executes(self, env, monkeypatch) -> None:
        import subprocess

        def explode(*args, **kwargs):
            raise AssertionError("mission start must not start a subprocess")

        monkeypatch.setattr(subprocess, "run", explode)
        monkeypatch.setattr(subprocess, "Popen", explode)
        mission = env["engine"].start_mission("improve code quality and test coverage")
        env["engine"].advance(mission.mission_id)
        env["engine"].advance(mission.mission_id)

    def test_advance_promotes_plan_into_mission_steps(self, env) -> None:
        mission = env["engine"].start_mission("improve code quality and test coverage")
        selected = env["engine"].advance(mission.mission_id)
        assert selected.action == "selected"
        assert selected.mission.status == "plan_proposed"
        assert selected.mission.selected_track_id
        assert selected.mission.active_plan_id

        promoted = env["engine"].advance(selected.mission.mission_id)
        assert promoted.action == "promoted"
        assert promoted.mission.status == "awaiting_approval"
        assert promoted.mission.approval_request_id
        assert promoted.steps
        for step in promoted.steps:
            assert step.step_id.startswith("mstp-")
            assert step.approval_step_id.startswith("astp-")
            assert step.approval_request_id == promoted.mission.approval_request_id
            assert step.source_track_id == promoted.mission.selected_track_id
            assert step.source_plan_id == promoted.mission.active_plan_id

    def test_advance_stops_at_approval_boundary(self, env) -> None:
        run, track, plan = _make_run_with_steps(
            env["db"], [("edit the config file safely", "yellow")]
        )
        mission = _make_mission_at_plan_proposed(env["db"], run, track, plan)
        _promote(env["engine"], mission)

        blocked = env["engine"].advance(mission.mission_id)
        assert blocked.action == "blocked_on_approval"
        assert blocked.mission.status == "awaiting_approval"
        # Advancing again does not sneak past the boundary.
        again = env["engine"].advance(mission.mission_id)
        assert again.action == "blocked_on_approval"


class TestApprovalGating:
    def test_yellow_requires_explicit_approval(self, env) -> None:
        run, track, plan = _make_run_with_steps(
            env["db"], [("edit the config file safely", "yellow")]
        )
        mission = _make_mission_at_plan_proposed(env["db"], run, track, plan)
        steps = _promote(env["engine"], mission)
        assert steps[0].approval_state == "pending"

        approved = env["engine"].approve_step(steps[0].step_id)
        assert approved.approval_state == "approved"

    def test_green_steps_auto_approve_per_existing_policy(self, env) -> None:
        run, track, plan = _make_run_with_steps(
            env["db"], [("summarize the latest results", "green")]
        )
        mission = _make_mission_at_plan_proposed(env["db"], run, track, plan)
        steps = _promote(env["engine"], mission)
        assert steps[0].approval_state == "approved"

    def test_black_steps_cannot_be_approved_or_run(self, env) -> None:
        run, track, plan = _make_run_with_steps(
            env["db"],
            [("rm -rf the build directory", "black")],
        )
        mission = _make_mission_at_plan_proposed(env["db"], run, track, plan)
        steps = _promote(env["engine"], mission)
        assert steps[0].risk_level == "black"

        with pytest.raises(BlockedStepError):
            env["engine"].approve_step(steps[0].step_id)
        with pytest.raises(BlockedStepError):
            env["engine"].run_step(steps[0].step_id, execute=True, approved=True)

    def test_red_requires_elevated_explicit_approval(self, env) -> None:
        run, track, plan = _make_run_with_steps(
            env["db"], [("deploy the release build", "red")]
        )
        mission = _make_mission_at_plan_proposed(env["db"], run, track, plan)
        steps = _promote(env["engine"], mission)

        env["engine"].approve_step(steps[0].step_id)
        # --execute alone is not enough for red.
        step, report = env["engine"].run_step(
            steps[0].step_id, runtime="noop", execute=True, approved=False
        )
        assert report.action == "refused"
        assert "approval" in report.reason
        assert step.execution_state != "executed"

        # --execute --yes satisfies the elevated gate.
        step, report = env["engine"].run_step(
            steps[0].step_id, runtime="noop", execute=True, approved=True
        )
        assert report.action == "executed"
        assert step.execution_state == "executed"

    def test_risk_budget_only_tightens(self, env) -> None:
        run, track, plan = _make_run_with_steps(
            env["db"], [("edit the config file safely", "yellow")]
        )
        mission = _make_mission_at_plan_proposed(
            env["db"], run, track, plan, max_risk="green"
        )
        steps = _promote(env["engine"], mission)
        with pytest.raises(RiskBudgetExceededError):
            env["engine"].approve_step(steps[0].step_id)
        with pytest.raises(RiskBudgetExceededError):
            env["engine"].run_step(steps[0].step_id, execute=True)

    def test_black_is_not_a_valid_budget(self, env) -> None:
        with pytest.raises(MissionError):
            env["engine"].start_mission("anything", max_risk="black")


class TestExecutionAndReceipts:
    def test_approved_step_runs_through_receipt_backed_execution(self, env) -> None:
        run, track, plan = _make_run_with_steps(
            env["db"], [("edit the config file safely", "yellow")]
        )
        mission = _make_mission_at_plan_proposed(env["db"], run, track, plan)
        steps = _promote(env["engine"], mission)
        env["engine"].approve_step(steps[0].step_id)

        # Dry-run by default: a receipt exists but nothing executed.
        step, report = env["engine"].run_step(steps[0].step_id, runtime="noop")
        assert report.action == "dry_run"
        assert step.execution_state == "dry_run"
        assert step.receipt_id is not None

        step, report = env["engine"].run_step(
            steps[0].step_id, runtime="noop", execute=True
        )
        assert report.action == "executed"
        assert step.execution_state == "executed"
        assert step.receipt_id is not None

        from opencobalt.execution.store import ExecutionStore

        receipt = ExecutionStore(env["db"]).get_receipt(step.receipt_id)
        assert receipt is not None
        assert receipt.artifact_ids, "execution must hash output artifacts"

    def test_receipt_links_back_to_mission_step_and_mission(self, env) -> None:
        run, track, plan = _make_run_with_steps(
            env["db"], [("edit the config file safely", "yellow")]
        )
        mission = _make_mission_at_plan_proposed(env["db"], run, track, plan)
        steps = _promote(env["engine"], mission)
        env["engine"].approve_step(steps[0].step_id)
        step, _ = env["engine"].run_step(
            steps[0].step_id, runtime="noop", execute=True
        )

        stored_step = env["engine"].store.get_step(step.step_id)
        assert stored_step.receipt_id == step.receipt_id
        stored_mission = env["engine"].store.get_mission(mission.mission_id)
        assert stored_mission.last_receipt_id == step.receipt_id
        assert stored_mission.status == "verifying"

    def test_verify_then_feedback_then_outcome(self, env) -> None:
        run, track, plan = _make_run_with_steps(
            env["db"], [("edit the config file safely", "yellow")]
        )
        mission = _make_mission_at_plan_proposed(env["db"], run, track, plan)
        steps = _promote(env["engine"], mission)
        env["engine"].approve_step(steps[0].step_id)
        env["engine"].run_step(steps[0].step_id, runtime="noop", execute=True)

        verified = env["engine"].advance(mission.mission_id)
        assert verified.action == "verified"
        assert verified.mission.status == "awaiting_feedback"

        outcome_id = env["engine"].record_outcome(
            mission.mission_id, "useful", notes="manual check passed"
        )
        assert outcome_id.startswith("oout-")
        final = env["engine"].store.get_mission(mission.mission_id)
        assert final.status == "completed"
        assert final.outcome == "useful"

        outcomes = OpportunityStore(env["db"]).list_outcomes(track_id=track.track_id)
        assert outcomes and outcomes[0]["outcome"] == "useful"
        assert outcomes[0]["receipt_id"] == final.last_receipt_id


class TestProvenance:
    def test_mission_why_trace_covers_the_full_chain(self, env) -> None:
        from opencobalt.core.provenance import ProvenanceBuilder, render_trace_lines

        run, track, plan = _make_run_with_steps(
            env["db"], [("edit the config file safely", "yellow")]
        )
        mission = _make_mission_at_plan_proposed(env["db"], run, track, plan)
        steps = _promote(env["engine"], mission)
        env["engine"].approve_step(steps[0].step_id)
        env["engine"].run_step(steps[0].step_id, runtime="noop", execute=True)
        env["engine"].advance(mission.mission_id)
        env["engine"].record_outcome(mission.mission_id, "useful")

        trace = ProvenanceBuilder(env["db"]).trace(mission.mission_id)
        assert trace is not None
        assert trace.focus_kind == "mission"
        kinds = {node.kind for node in trace.nodes}
        for expected in (
            "mission", "mission_step", "goal", "track", "plan",
            "approval", "step", "exec_plan", "receipt", "artifact", "outcome",
        ):
            assert expected in kinds, f"trace missing {expected}: {kinds}"
        rendered = "\n".join(render_trace_lines(trace))
        assert mission.mission_id[:14] in rendered

    def test_mission_step_id_resolves_in_provenance(self, env) -> None:
        from opencobalt.core.provenance import ProvenanceBuilder

        run, track, plan = _make_run_with_steps(
            env["db"], [("edit the config file safely", "yellow")]
        )
        mission = _make_mission_at_plan_proposed(env["db"], run, track, plan)
        steps = _promote(env["engine"], mission)
        trace = ProvenanceBuilder(env["db"]).trace(steps[0].step_id)
        assert trace is not None
        assert trace.focus_kind == "mission_step"
        assert trace.get_node(mission.mission_id) is not None


class TestEvolveIntegration:
    def test_evolve_goal_routes_to_evolve_mission_type(self) -> None:
        assert classify_mission_type("make OpenCobalt more useful this week") == "evolve"
        assert classify_mission_type("improve code quality") == "opportunity"

    def test_evolve_candidate_links_to_mission(self, env) -> None:
        mission = env["engine"].start_mission(
            "make OpenCobalt more useful this week without weakening safety gates"
        )
        assert mission.mission_type == "evolve"
        assert mission.evolve_mission_id is not None
        assert mission.status == "candidates_generated"

        from opencobalt.core.evolve import EvolveStore

        evolve_mission = EvolveStore(env["db"]).get_mission(mission.evolve_mission_id)
        assert evolve_mission is not None
        assert evolve_mission.run_id == mission.run_id

        selected = env["engine"].advance(mission.mission_id)
        assert selected.mission.selected_candidate_id is not None
        candidate = EvolveStore(env["db"]).get_candidate(
            selected.mission.selected_candidate_id
        )
        assert candidate is not None
        assert candidate.track_id == selected.mission.selected_track_id
