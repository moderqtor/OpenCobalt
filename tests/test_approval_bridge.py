"""Tests for the approval bridge: promotion, decisions, and execution handoff.

Everything runs against tmp_path-isolated SQLite databases. No live agent
runtimes: execution handoff uses the noop adapter, and promotion paths are
guarded against starting any subprocess at all.
"""

from __future__ import annotations

import subprocess

import pytest

from opencobalt.core.approval_bridge import (
    APPROVAL_STATES,
    ApprovalBridge,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStore,
    BlockedStepError,
)
from opencobalt.core.opportunity_engine import OpportunityEngine
from opencobalt.core.opportunity_store import OpportunityStore
from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.store import ExecutionStore


@pytest.fixture
def env(tmp_path):
    """Isolated engine/store/bridge trio sharing one ledger db."""
    db = tmp_path / "ledger.db"
    events = tmp_path / "events"
    engine = OpportunityEngine(
        root=tmp_path, db_path=db, events_path=events / "opportunity.jsonl"
    )
    run = engine.brainstorm("improve code quality and test coverage", plan=True)
    bridge = ApprovalBridge(db_path=db, events_path=events / "approval.jsonl")
    return {
        "db": db,
        "run": run,
        "bridge": bridge,
        "store": OpportunityStore(db),
    }


def _planned_track(run):
    for track in run.tracks:
        if track.plan_id:
            return track
    raise AssertionError("no planned track in run")


def _unplanned_track(run):
    for track in run.tracks:
        if not track.plan_id:
            return track
    raise AssertionError("no unplanned track in run")


def _track_named(run, name):
    for track in run.tracks:
        if track.name == name:
            return track
    raise AssertionError(f"no track named {name} in run")


class TestPromotion:
    def test_promote_track_with_existing_plan(self, env):
        track = _planned_track(env["run"])
        request, created = env["bridge"].promote(env["run"], track.track_id)
        assert created
        assert request.track_id == track.track_id
        assert request.opportunity_plan_id == track.plan_id
        assert request.source_type == "opportunity_track"
        assert request.goal_id == env["run"].goal.goal_id
        assert request.steps
        assert request.state in APPROVAL_STATES

    def test_promote_plan_directly(self, env):
        plan = env["run"].plans[0]
        request, created = env["bridge"].promote(env["run"], plan.plan_id)
        assert created
        assert request.source_type == "opportunity_plan"
        assert request.source_id == plan.plan_id
        assert request.opportunity_plan_id == plan.plan_id

    def test_promote_unplanned_track_builds_plan(self, env):
        track = _unplanned_track(env["run"])
        request, created = env["bridge"].promote(
            env["run"], track.track_id, opportunity_store=env["store"]
        )
        assert created
        assert track.plan_id is not None
        assert request.opportunity_plan_id == track.plan_id
        # The newly built plan was persisted with the run.
        reloaded = env["store"].get_run(env["run"].run_id)
        assert track.plan_id in [p.plan_id for p in reloaded.plans]

    def test_promotion_is_reused_unless_new(self, env):
        track = _planned_track(env["run"])
        first, created_first = env["bridge"].promote(env["run"], track.track_id)
        second, created_second = env["bridge"].promote(env["run"], track.track_id)
        assert created_first and not created_second
        assert first.request_id == second.request_id

    def test_new_supersedes_existing_request(self, env):
        track = _planned_track(env["run"])
        first, _ = env["bridge"].promote(env["run"], track.track_id)
        second, created = env["bridge"].promote(env["run"], track.track_id, new=True)
        assert created
        assert second.request_id != first.request_id
        old = env["bridge"].store.get_request(first.request_id)
        assert old.state == "superseded"

    def test_promote_unknown_source_raises(self, env):
        with pytest.raises(KeyError):
            env["bridge"].promote(env["run"], "otrk-doesnotexist")

    def test_promotion_never_starts_subprocess(self, env, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("promotion must not start a subprocess")

        monkeypatch.setattr(subprocess, "run", explode)
        monkeypatch.setattr(subprocess, "Popen", explode)
        track = _unplanned_track(env["run"])
        request, created = env["bridge"].promote(
            env["run"], track.track_id, opportunity_store=env["store"]
        )
        assert created

    def test_request_persists_and_reloads(self, env):
        track = _planned_track(env["run"])
        request, _ = env["bridge"].promote(env["run"], track.track_id)
        fresh_store = ApprovalStore(env["db"])
        reloaded = fresh_store.get_request(request.request_id)
        assert reloaded is not None
        assert reloaded.to_dict() == request.to_dict()
        # Prefix lookup works too.
        assert fresh_store.get_request(request.request_id[:10]) is not None


class TestApprovalStates:
    def test_green_steps_auto_approved_by_policy(self, env):
        track = _planned_track(env["run"])
        request, _ = env["bridge"].promote(env["run"], track.track_id)
        for step in request.steps:
            if step.risk_level == "green":
                assert step.approval_state == "approved"
                assert not step.approval_required

    def test_green_steps_stay_pending_without_policy(self, env):
        bridge = ApprovalBridge(
            db_path=env["db"], policy=ApprovalPolicy(auto_approve_green=False)
        )
        track = _planned_track(env["run"])
        request, _ = bridge.promote(env["run"], track.track_id, new=True)
        for step in request.steps:
            assert step.approval_state == "pending"

    def test_yellow_steps_require_explicit_approval(self, env):
        # The test-gaps track plans steps like "write tests ..." -> yellow.
        track = _track_named(env["run"], "test gaps")
        request, _ = env["bridge"].promote(
            env["run"], track.track_id, opportunity_store=env["store"]
        )
        yellow = [s for s in request.steps if s.risk_level == "yellow"]
        assert yellow, "expected at least one yellow step in test-gaps plan"
        for step in yellow:
            assert step.approval_required
            assert step.approval_state == "pending"

    def test_explicit_approval_flips_step_and_request(self, env):
        track = _planned_track(env["run"])
        request, _ = env["bridge"].promote(env["run"], track.track_id)
        env["bridge"].approve(request.request_id)
        refreshed = env["bridge"].store.get_request(request.request_id)
        assert refreshed.state == "approved"
        assert all(s.approval_state == "approved" for s in refreshed.steps)

    def test_single_step_approval(self, env):
        track = _track_named(env["run"], "test gaps")
        request, _ = env["bridge"].promote(
            env["run"], track.track_id, opportunity_store=env["store"]
        )
        pending = [s for s in request.steps if s.approval_state == "pending"]
        assert pending, "expected pending yellow steps in test-gaps plan"
        approved = env["bridge"].approve(request.request_id, step_id=pending[0].step_id)
        assert [s.step_id for s in approved] == [pending[0].step_id]
        refreshed = env["bridge"].store.get_request(request.request_id)
        states = {s.step_id: s.approval_state for s in refreshed.steps}
        assert states[pending[0].step_id] == "approved"

    def test_reject_records_decision(self, env):
        track = _planned_track(env["run"])
        request, _ = env["bridge"].promote(env["run"], track.track_id)
        env["bridge"].reject(request.request_id, reason="not now")
        refreshed = env["bridge"].store.get_request(request.request_id)
        assert refreshed.state == "rejected"
        decisions = env["bridge"].store.list_decisions(request.request_id)
        assert any(d.decision == "rejected" and d.reason == "not now" for d in decisions)


def _request_with_step(bridge, env, risk_level, task="hello step"):
    """Build a persisted request with one synthetic step at a given risk."""
    track = _planned_track(env["run"])
    request, _ = bridge.promote(env["run"], track.track_id, new=True)
    from opencobalt.core.approval_bridge import ApprovalStep

    step = ApprovalStep(
        step_id="astp-synthetic1",
        request_id=request.request_id,
        source_type=request.source_type,
        source_id=request.source_id,
        task=task,
        risk_level=risk_level,
        approval_required=risk_level != "green",
        approval_state="pending",
        metadata={"blocked": risk_level == "black"},
    )
    request.steps = [step]
    request.refresh_state()
    bridge.store.save_request(request)
    return request, step


class TestBlackRisk:
    def test_black_step_cannot_be_approved(self, env):
        request, step = _request_with_step(env["bridge"], env, "black")
        with pytest.raises(BlockedStepError):
            env["bridge"].approve(request.request_id, step_id=step.step_id)

    def test_whole_request_approval_skips_black(self, env):
        request, step = _request_with_step(env["bridge"], env, "black")
        approved = env["bridge"].approve(request.request_id)
        assert step.step_id not in [s.step_id for s in approved]

    def test_black_step_never_runs(self, env):
        request, step = _request_with_step(env["bridge"], env, "black")
        engine = ExecutionEngine(store=ExecutionStore(env["db"]))
        reports = env["bridge"].run_steps(
            request.request_id, engine=engine, execute=True, approved=True
        )
        assert reports[0].action == "blocked"
        assert reports[0].step.receipt_id is None


class TestExecutionHandoff:
    def _engine(self, env, tmp_path=None):
        return ExecutionEngine(store=ExecutionStore(env["db"]))

    def test_unapproved_step_refuses_execution(self, env):
        request, step = _request_with_step(env["bridge"], env, "yellow")
        reports = env["bridge"].run_steps(
            request.request_id, engine=self._engine(env), execute=True
        )
        assert reports[0].action == "refused"
        assert "approvals approve" in reports[0].reason
        assert reports[0].step.receipt_id is None

    def test_dry_run_is_default_and_links_receipt(self, env):
        request, step = _request_with_step(env["bridge"], env, "yellow")
        env["bridge"].approve(request.request_id, step_id=step.step_id)
        reports = env["bridge"].run_steps(
            request.request_id, engine=self._engine(env), runtime="noop"
        )
        report = reports[0]
        assert report.action == "dry_run"
        assert report.step.approval_state == "approved"  # not executed yet
        assert report.step.execution_plan_id is not None
        assert report.step.receipt_id is not None
        # The receipt exists in the execution store and points back.
        receipt = ExecutionStore(env["db"]).get_receipt(report.step.receipt_id)
        assert receipt is not None
        assert receipt.plan_id == report.step.execution_plan_id

    def test_execute_runs_and_marks_executed(self, env):
        request, step = _request_with_step(env["bridge"], env, "yellow")
        env["bridge"].approve(request.request_id)
        reports = env["bridge"].run_steps(
            request.request_id, engine=self._engine(env), runtime="noop", execute=True
        )
        report = reports[0]
        assert report.action == "executed"
        assert report.step.approval_state == "executed"
        assert report.step.receipt_id is not None
        refreshed = env["bridge"].store.get_request(request.request_id)
        assert refreshed.state == "executed"

    def test_receipt_links_back_to_step(self, env):
        request, step = _request_with_step(env["bridge"], env, "yellow")
        env["bridge"].approve(request.request_id)
        env["bridge"].run_steps(
            request.request_id, engine=self._engine(env), runtime="noop", execute=True
        )
        refreshed = env["bridge"].store.get_request(request.request_id)
        receipt_id = refreshed.steps[0].receipt_id
        found = env["bridge"].store.find_step_by_receipt(receipt_id)
        assert found is not None
        found_request, found_step = found
        assert found_request.request_id == request.request_id
        assert found_step.step_id == refreshed.steps[0].step_id

    def test_executed_step_skipped_unless_rerun(self, env):
        request, step = _request_with_step(env["bridge"], env, "yellow")
        env["bridge"].approve(request.request_id)
        engine = self._engine(env)
        env["bridge"].run_steps(
            request.request_id, engine=engine, runtime="noop", execute=True
        )
        second = env["bridge"].run_steps(
            request.request_id, engine=engine, runtime="noop", execute=True
        )
        assert second[0].action == "skipped"
        third = env["bridge"].run_steps(
            request.request_id, engine=engine, runtime="noop", execute=True, rerun=True
        )
        assert third[0].action == "executed"

    def test_red_step_requires_yes(self, env):
        request, step = _request_with_step(
            env["bridge"], env, "red", task="rotate the api key"
        )
        env["bridge"].approve(request.request_id, step_id=step.step_id)
        engine = self._engine(env)
        blocked = env["bridge"].run_steps(
            request.request_id, engine=engine, runtime="noop", execute=True
        )
        assert blocked[0].action == "refused"
        assert "approval" in blocked[0].reason.lower()
        allowed = env["bridge"].run_steps(
            request.request_id, engine=engine, runtime="noop",
            execute=True, approved=True,
        )
        assert allowed[0].action == "executed"


class TestSerialization:
    def test_request_round_trip(self, env):
        track = _planned_track(env["run"])
        request, _ = env["bridge"].promote(env["run"], track.track_id)
        data = request.to_dict()
        clone = ApprovalRequest.from_dict(data)
        assert clone.to_dict() == data

    def test_count_pending(self, env):
        track = _track_named(env["run"], "test gaps")
        env["bridge"].promote(env["run"], track.track_id, opportunity_store=env["store"])
        assert env["bridge"].store.count_pending() >= 1
