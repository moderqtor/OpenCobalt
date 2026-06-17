"""Tests for durable auto orchestration mission attachment."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.core.approval_bridge import ApprovalStore, BlockedStepError
from opencobalt.core.auto_orchestrator import AutoOrchestrator, AutoPlan, AutoRouteStep
from opencobalt.core.mission_engine import MissionEngine, MissionStore
from opencobalt.execution.store import ExecutionStore
from opencobalt.shell import CobaltShell

runner = CliRunner()


def _invoke(*args: str, **kwargs):
    env = {**kwargs.pop("env", {}), "NO_COLOR": "1", "COLUMNS": "200"}
    kwargs.setdefault("color", False)
    return runner.invoke(app, list(args), env=env, **kwargs)


def _first(pattern: str, output: str) -> str:
    match = re.search(pattern, output)
    assert match, f"no match for {pattern} in output: {output}"
    return match.group(1)


def test_auto_create_mission_persists_plan_without_subprocesses(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db = tmp_path / "ledger.db"

    def explode(*args, **kwargs):
        raise AssertionError("auto mission bridge must not spawn subprocesses")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)

    record = AutoOrchestrator().create_mission(
        "improve OpenCobalt safely and explain the plan",
        db_path=db,
        root=tmp_path,
    )

    store = MissionStore(db)
    mission = store.get_mission(record.mission_id)
    assert mission is not None
    assert mission.goal == "improve OpenCobalt safely and explain the plan"
    assert mission.mission_type == "auto"
    assert mission.auto_plan_id == record.plan.auto_plan_id
    assert mission.auto_plan_hash == record.plan.auto_plan_hash
    assert mission.auto_intent == "repo_improvement"
    assert mission.autonomy_envelope == "dry_run"
    assert mission.cognitive_budget == "high"
    assert mission.auto_next_action == record.plan.next_recommended_action
    assert mission.run_id is None
    assert mission.approval_request_id is None
    assert mission.last_receipt_id is None

    steps = store.list_steps(mission.mission_id)
    assert len(steps) == len(record.plan.internal_route_steps)
    assert [step.auto_step_order for step in steps] == list(range(1, len(steps) + 1))
    assert any(step.auto_primitive == "opportunity_discovery" for step in steps)
    assert all(step.auto_step_why for step in steps)
    assert all(step.approval_request_id is None for step in steps)
    assert all(step.approval_step_id is None for step in steps)
    assert not ExecutionStore(db).list_receipts()

    events = store.list_mission_events(mission.mission_id)
    assert any(event["event_type"] == "mission.auto_plan_attached" for event in events)


def test_auto_create_mission_records_execution_engine_expectations(
    tmp_path: Path,
) -> None:
    record = AutoOrchestrator().create_mission(
        "run a codex dry-run smoke for the adapter",
        db_path=tmp_path / "ledger.db",
        root=tmp_path,
    )

    steps = MissionStore(tmp_path / "ledger.db").list_steps(record.mission_id)
    execution_steps = [step for step in steps if step.uses_execution_engine]
    assert execution_steps
    assert all(step.expected_receipt for step in execution_steps)
    assert all(step.requires_approval is False for step in execution_steps)
    assert all("ExecutionEngine" in step.auto_step_why for step in execution_steps)


def test_auto_mission_advance_stops_without_promoting_execution(
    tmp_path: Path,
) -> None:
    db = tmp_path / "ledger.db"
    record = AutoOrchestrator().create_mission(
        "improve OpenCobalt safely and explain the plan",
        db_path=db,
        root=tmp_path,
    )

    report = MissionEngine(root=tmp_path, db_path=db).advance(record.mission_id)

    assert report.action == "noop"
    assert "auto mission" in report.detail
    assert "nothing executes" in report.detail
    assert not ExecutionStore(db).list_receipts()


def test_auto_cli_create_mission_and_show_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = _invoke(
        "auto",
        "improve OpenCobalt safely and explain the plan",
        "--create-mission",
    )
    assert result.exit_code == 0, result.output
    assert "Auto orchestration plan" in result.output
    assert "Mission created" in result.output
    assert "What was persisted" in result.output
    assert "no subprocesses started" in result.output
    mission_id = _first(r"(mis-[0-9a-f]{6,})", result.output)

    show = _invoke("missions", "show", mission_id)
    assert show.exit_code == 0, show.output
    assert "Auto plan" in show.output
    assert "repo_improvement" in show.output
    assert "dry_run" in show.output
    assert "high" in show.output
    assert "opportunity_discovery" in show.output


def test_auto_cli_default_remains_plan_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = _invoke("auto", "improve OpenCobalt safely and explain the plan")
    assert result.exit_code == 0, result.output
    assert "planned only" in result.output
    assert "Mission created" not in result.output
    assert not (tmp_path / ".opencobalt" / "ledger.db").exists()


def test_auto_create_mission_remains_mission_only_until_promoted(
    tmp_path: Path,
) -> None:
    db = tmp_path / "ledger.db"

    record = AutoOrchestrator().create_mission(
        "improve OpenCobalt safely and explain the plan",
        db_path=db,
        root=tmp_path,
    )

    assert MissionStore(db).get_mission(record.mission_id).approval_request_id is None
    assert ApprovalStore(db).list_requests() == []
    assert ExecutionStore(db).list_receipts() == []


def test_auto_route_promotion_creates_pending_approval_request_without_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db = tmp_path / "ledger.db"
    record = AutoOrchestrator().create_mission(
        "improve OpenCobalt safely and explain the plan",
        db_path=db,
        root=tmp_path,
    )

    def explode(*args, **kwargs):
        raise AssertionError("auto route promotion must not spawn subprocesses")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(subprocess, "Popen", explode)

    report = MissionEngine(root=tmp_path, db_path=db).promote_auto_route(
        record.mission_id
    )

    assert report.action == "promoted"
    assert report.approval_request_id.startswith("areq-")
    assert report.promoted_steps
    assert report.unpromoted_steps
    assert any(
        step.auto_promotion_classification == "informational"
        for step in report.unpromoted_steps
    )
    assert any(
        step.auto_promotion_classification == "approval_candidate"
        for step in report.promoted_steps
    )
    assert any(
        step.auto_promotion_classification == "verification_candidate"
        for step in report.promoted_steps
    )

    mission = MissionStore(db).get_mission(record.mission_id)
    assert mission is not None
    assert mission.approval_request_id == report.approval_request_id
    assert mission.auto_plan_id == record.plan.auto_plan_id
    assert mission.auto_plan_hash == record.plan.auto_plan_hash
    assert mission.autonomy_envelope == record.plan.selected_envelope
    assert mission.cognitive_budget == record.plan.selected_cognitive_budget

    request = ApprovalStore(db).get_request(report.approval_request_id)
    assert request is not None
    assert request.source_type == "auto_route"
    assert request.source_id == mission.mission_id
    assert request.state == "pending"
    assert request.metadata["mission_id"] == mission.mission_id
    assert request.metadata["auto_plan_id"] == record.plan.auto_plan_id
    assert request.metadata["auto_plan_hash"] == record.plan.auto_plan_hash
    assert request.metadata["envelope"] == record.plan.selected_envelope
    assert request.metadata["cognitive_budget"] == record.plan.selected_cognitive_budget
    assert all(step.approval_state == "pending" for step in request.steps)
    assert all(step.execution_plan_id is None for step in request.steps)
    assert all(step.receipt_id is None for step in request.steps)
    assert all(step.metadata["route_step_why"] for step in request.steps)
    assert all(step.metadata["expected_receipt_description"] for step in request.steps)

    promoted = [step for step in MissionStore(db).list_steps(mission.mission_id) if step.approval_step_id]
    assert len(promoted) == len(request.steps)
    assert all(step.approval_request_id == request.request_id for step in promoted)
    assert all(step.approval_state == "pending" for step in promoted)
    assert all(step.receipt_id is None for step in promoted)
    assert ExecutionStore(db).list_receipts() == []

    events = MissionStore(db).list_mission_events(mission.mission_id)
    assert any(event["event_type"] == "mission.auto_route_promoted" for event in events)


def test_auto_route_promotion_blocks_outward_authority_placeholders(
    tmp_path: Path,
) -> None:
    db = tmp_path / "ledger.db"
    plan = AutoPlan(
        auto_plan_id="aplan-testblocked",
        auto_plan_hash="f" * 64,
        goal="push and deploy this branch",
        intent="repo_improvement",
        selected_envelope="dry_run",
        selected_cognitive_budget="high",
        internal_route_steps=[
            AutoRouteStep(
                order=1,
                primitive="mission_start",
                command_hint="git push origin main && deploy production",
                why="Remote push and deploy are outward authority boundaries.",
                approval_required=True,
            )
        ],
        required_approvals=["human approval before any non-dry-run execution"],
        expected_receipts=["No receipt is created by planning alone"],
        next_recommended_action="do not push or deploy",
        did_actions=["planned only; no subprocesses started"],
    )
    mission, _steps = MissionEngine(root=tmp_path, db_path=db).create_auto_mission(plan)

    report = MissionEngine(root=tmp_path, db_path=db).promote_auto_route(
        mission.mission_id
    )

    assert report.blocked_steps
    blocked_step = report.blocked_steps[0]
    assert blocked_step.auto_promotion_classification == "blocked_authority"
    assert blocked_step.risk_level == "black"
    assert {"push", "deploy"} <= set(blocked_step.blocked_authority)

    request = ApprovalStore(db).get_request(report.approval_request_id)
    assert request is not None
    assert request.steps[0].risk_level == "black"
    assert request.steps[0].metadata["promotion_classification"] == "blocked_authority"
    assert {"push", "deploy"} <= set(request.steps[0].metadata["blocked_authority"])

    with pytest.raises(BlockedStepError):
        MissionEngine(root=tmp_path, db_path=db).approve_step(blocked_step.step_id)

    assert ExecutionStore(db).list_receipts() == []


def test_auto_cli_promote_flag_persists_mission_and_approval_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = _invoke(
        "auto",
        "improve OpenCobalt safely and explain the plan",
        "--create-mission",
        "--promote",
    )

    assert result.exit_code == 0, result.output
    assert "Mission created" in result.output
    assert "Auto route promoted" in result.output
    assert "no approvals granted" in result.output
    mission_id = _first(r"(mis-[0-9a-f]{6,})", result.output)
    request_id = _first(r"(areq-[0-9a-f]{6,})", result.output)

    mission = MissionStore(tmp_path / ".opencobalt" / "ledger.db").get_mission(mission_id)
    assert mission is not None
    assert mission.approval_request_id == request_id
    assert ApprovalStore(tmp_path / ".opencobalt" / "ledger.db").get_request(request_id)
    assert ExecutionStore(tmp_path / ".opencobalt" / "ledger.db").list_receipts() == []


def test_missions_promote_auto_command_and_displays_expose_promoted_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    created = _invoke(
        "auto",
        "improve OpenCobalt safely and explain the plan",
        "--create-mission",
    )
    mission_id = _first(r"(mis-[0-9a-f]{6,})", created.output)

    promoted = _invoke("missions", "promote-auto", mission_id)

    assert promoted.exit_code == 0, promoted.output
    assert "Auto route promoted" in promoted.output
    request_id = _first(r"(areq-[0-9a-f]{6,})", promoted.output)
    assert "approval requests are pending" in promoted.output

    shown = _invoke("missions", "show", mission_id)
    assert shown.exit_code == 0, shown.output
    assert "Auto route promotion" in shown.output
    assert request_id[:13] in shown.output
    assert "approval_candidate" in shown.output
    assert "verification_candidate" in shown.output
    assert "unpromoted" in shown.output
    assert "approvals show" in shown.output

    why = _invoke("why", mission_id)
    assert why.exit_code == 0, why.output
    assert "approval request" in why.output
    assert "promoted_to" in why.output
    assert "approval_state=pending" in why.output
    assert ExecutionStore(tmp_path / ".opencobalt" / "ledger.db").list_receipts() == []


def test_shell_auto_create_mission_promote_uses_same_bridge(
    tmp_path: Path,
    capsys,
) -> None:
    shell = CobaltShell(
        db_path=tmp_path / "ledger.db",
        bridge_path=tmp_path / "memories.db",
    )

    shell._run_auto("improve OpenCobalt safely --create-mission --promote")

    captured = capsys.readouterr()
    assert "Auto route promoted" in captured.out
    mission = MissionStore(tmp_path / "ledger.db").latest_mission()
    assert mission is not None
    assert mission.approval_request_id
    request = ApprovalStore(tmp_path / "ledger.db").get_request(
        mission.approval_request_id
    )
    assert request is not None
    assert request.state == "pending"
    assert all(step.approval_state == "pending" for step in request.steps)
    assert ExecutionStore(tmp_path / "ledger.db").list_receipts() == []


def test_auto_why_surfaces_auto_plan_linkage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    created = _invoke(
        "auto",
        "run a codex dry-run smoke for the adapter",
        "--create-mission",
    )
    mission_id = _first(r"(mis-[0-9a-f]{6,})", created.output)

    why = _invoke("why", mission_id)
    assert why.exit_code == 0, why.output
    assert "auto_plan" in why.output
    assert "runtime_adapter_work" in why.output
    assert "dry_run" in why.output
    assert "uses_execution_engine=True" in why.output
    assert "expected_receipt=True" in why.output


def test_shell_auto_create_mission_uses_same_planner(
    tmp_path: Path,
    capsys,
) -> None:
    shell = CobaltShell(
        db_path=tmp_path / "ledger.db",
        bridge_path=tmp_path / "memories.db",
    )

    shell._run_auto("improve OpenCobalt safely --create-mission")

    captured = capsys.readouterr()
    assert "Mission created" in captured.out
    mission = MissionStore(tmp_path / "ledger.db").latest_mission()
    assert mission is not None
    assert mission.auto_intent == "repo_improvement"
    assert mission.autonomy_envelope == "dry_run"
