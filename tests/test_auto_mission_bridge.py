"""Tests for durable auto orchestration mission attachment."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.core.auto_orchestrator import AutoOrchestrator
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
