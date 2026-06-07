"""Tests for the durable long-run autonomy engine."""

from __future__ import annotations

from opencobalt.core.autonomy_engine import AutonomyEngine
from opencobalt.core.ledger import Ledger


def test_engine_creates_run_and_initial_tasks(ledger: Ledger) -> None:
    engine = AutonomyEngine(ledger=ledger)

    run = engine.start(
        seed_goal="build auth with tests and docs",
        profile="aggressive",
        hours=2,
        allowed_actions=["local-build"],
    )

    assert run["profile"] == "aggressive"
    assert run["status"] == "running"
    tasks = ledger.list_autonomy_tasks(run["id"])
    assert len(tasks) >= 2
    assert {task["task_type"] for task in tasks} >= {"impl", "tests"}


def test_engine_resume_returns_next_unfinished_task(ledger: Ledger) -> None:
    engine = AutonomyEngine(ledger=ledger)
    run = engine.start("build auth with tests", profile="balanced")
    tasks = ledger.list_autonomy_tasks(run["id"])
    ledger.update_autonomy_task(tasks[0]["id"], status="completed")

    resumed = engine.resume(run["id"])

    assert resumed["id"] == run["id"]
    assert all(task["status"] != "completed" for task in resumed["next_tasks"])


def test_engine_records_checkpoint_without_running_external_tools(ledger: Ledger) -> None:
    engine = AutonomyEngine(ledger=ledger)
    run = engine.start("summarize this log", profile="cheap")
    task = ledger.list_autonomy_tasks(run["id"])[0]

    engine.checkpoint_task(run["id"], task["id"], status="completed", artifact_ids=["artifact-1"])

    saved = ledger.list_autonomy_tasks(run["id"])[0]
    assert saved["status"] == "completed"
    assert saved["artifact_ids"] == ["artifact-1"]
