"""CLI tests for opencobalt missions (Mission State Machine v1).

Every test chdirs into tmp_path so the ledger and event files land in a
throwaway directory. Execution uses the noop adapter only.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.core.mission_engine import Mission, MissionStore
from opencobalt.core.opportunity_engine import (
    OpportunityGoal,
    OpportunityPlan,
    OpportunityRun,
    OpportunityTrack,
)
from opencobalt.core.opportunity_store import OpportunityStore

runner = CliRunner()


def _invoke(*args: str, **kwargs):
    # Wide COLUMNS keeps rich tables from truncating ids under CliRunner.
    env = {**kwargs.pop("env", {}), "NO_COLOR": "1", "COLUMNS": "200"}
    kwargs.setdefault("color", False)
    return runner.invoke(app, list(args), env=env, **kwargs)


def _first(pattern: str, output: str) -> str:
    match = re.search(pattern, output)
    assert match, f"no match for {pattern} in output: {output}"
    return match.group(1)


def _seed_yellow_mission(tmp_path: Path) -> str:
    """Persist a mission at plan_proposed whose plan has one yellow step,
    so the explicit-approval path is deterministic. Returns mission_id."""
    db = tmp_path / ".opencobalt" / "ledger.db"
    goal = OpportunityGoal(
        goal_id="goal-000000000001", text="cli test goal", goal_class="strategy"
    )
    run = OpportunityRun(run_id="orun-000000000001", goal=goal)
    track = OpportunityTrack(
        track_id="otrk-000000000001",
        goal_id=goal.goal_id,
        name="cli track",
        track_type="strategy",
        status="planned",
        plan_id="oplan-000000000001",
    )
    run.tracks.append(track)
    run.plans.append(
        OpportunityPlan(
            plan_id="oplan-000000000001",
            track_id=track.track_id,
            goal_id=goal.goal_id,
            delegation={},
            steps=[
                {
                    "description": "edit the config file safely",
                    "risk_level": "yellow",
                    "approval_required": False,
                }
            ],
            risk_level="yellow",
            approval_state="pending",
        )
    )
    OpportunityStore(db).save_run(run)
    mission = Mission(
        mission_id="mis-000000000001",
        goal=goal.text,
        status="plan_proposed",
        run_id=run.run_id,
        selected_track_id=track.track_id,
        active_plan_id="oplan-000000000001",
    )
    MissionStore(db).save_mission(mission)
    return mission.mission_id


class TestStartListShow:
    def test_start_creates_mission_without_executing(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke(
            "missions", "start", "improve code quality and test coverage"
        )
        assert result.exit_code == 0, result.output
        assert "Mission started" in result.output
        mission_id = _first(r"(mis-[0-9a-f]{6,})", result.output)
        assert "missions advance" in result.output

        listed = _invoke("missions", "list")
        assert listed.exit_code == 0
        assert mission_id[:14] in listed.output
        assert "opportunities_generated" in listed.output

    def test_show_displays_mission_state(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        started = _invoke(
            "missions", "start", "improve code quality and test coverage"
        )
        mission_id = _first(r"(mis-[0-9a-f]{6,})", started.output)
        result = _invoke("missions", "show", mission_id)
        assert result.exit_code == 0
        assert mission_id in result.output
        assert "opportunities_generated" in result.output

    def test_show_unknown_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("missions", "show", "mis-missing")
        assert result.exit_code == 1

    def test_list_empty_hint(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("missions", "list")
        assert result.exit_code == 0
        assert "No missions yet" in result.output

    def test_invalid_risk_budget_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("missions", "start", "anything", "--max-risk", "black")
        assert result.exit_code == 1


class TestAdvanceApproveRun:
    def test_full_supervised_loop_via_cli(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mission_id = _seed_yellow_mission(tmp_path)

        promoted = _invoke("missions", "advance", mission_id)
        assert promoted.exit_code == 0, promoted.output
        assert "awaiting_approval" in promoted.output
        step_id = _first(r"(mstp-[0-9a-f]{6,})", promoted.output)

        # Advancing again stops at the approval boundary.
        blocked = _invoke("missions", "advance", mission_id)
        assert blocked.exit_code == 0
        assert "blocked_on_approval" in blocked.output

        approved = _invoke("missions", "approve-step", step_id)
        assert approved.exit_code == 0, approved.output
        assert "Step approved" in approved.output

        # Approval alone never executes: run-step defaults to dry-run.
        dry = _invoke("missions", "run-step", step_id, "--runtime", "noop")
        assert dry.exit_code == 0, dry.output
        assert "Dry-run only" in dry.output

        ran = _invoke(
            "missions", "run-step", step_id, "--runtime", "noop", "--execute"
        )
        assert ran.exit_code == 0, ran.output
        assert "executed" in ran.output
        assert "Receipt:" in ran.output
        receipt_id = _first(r"Receipt:\s+(\S+)", ran.output)

        verified = _invoke("missions", "advance", mission_id)
        assert verified.exit_code == 0
        assert "awaiting_feedback" in verified.output

        outcome = _invoke("missions", "outcome", mission_id, "useful")
        assert outcome.exit_code == 0, outcome.output
        assert "completed" in outcome.output

        # The receipt is visible through the standard receipts surface.
        receipts = _invoke("receipts", "list")
        assert receipt_id[:8] in receipts.output

    def test_run_step_refuses_unapproved(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mission_id = _seed_yellow_mission(tmp_path)
        promoted = _invoke("missions", "advance", mission_id)
        step_id = _first(r"(mstp-[0-9a-f]{6,})", promoted.output)

        refused = _invoke(
            "missions", "run-step", step_id, "--runtime", "noop", "--execute"
        )
        assert refused.exit_code == 2
        assert "not approved" in refused.output


class TestWhy:
    def test_missions_why_renders_full_story(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mission_id = _seed_yellow_mission(tmp_path)
        promoted = _invoke("missions", "advance", mission_id)
        step_id = _first(r"(mstp-[0-9a-f]{6,})", promoted.output)
        _invoke("missions", "approve-step", step_id)
        _invoke("missions", "run-step", step_id, "--runtime", "noop", "--execute")
        _invoke("missions", "advance", mission_id)
        _invoke("missions", "outcome", mission_id, "useful")

        result = _invoke("missions", "why", mission_id)
        assert result.exit_code == 0, result.output
        assert "Why mission" in result.output
        for marker in ("goal", "track", "approval", "receipt", "outcome"):
            assert marker in result.output, f"missing {marker}: {result.output}"
        assert "Mission events" in result.output

    def test_top_level_why_resolves_mission_ids(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mission_id = _seed_yellow_mission(tmp_path)
        promoted = _invoke("missions", "advance", mission_id)
        step_id = _first(r"(mstp-[0-9a-f]{6,})", promoted.output)

        whole = _invoke("why", mission_id)
        assert whole.exit_code == 0, whole.output
        assert "kind: mission" in whole.output

        step_trace = _invoke("why", step_id)
        assert step_trace.exit_code == 0, step_trace.output
        assert "kind: mission_step" in step_trace.output
