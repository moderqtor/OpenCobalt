"""Tests for Phase 14 autonomy tables in the ledger."""

from __future__ import annotations

from opencobalt.core.ledger import Ledger


def test_autonomy_run_round_trip(ledger: Ledger) -> None:
    run_id = ledger.create_autonomy_run(
        seed_goal="finish the app",
        profile="max",
        allowed_actions=["local-build"],
        denied_actions=["push"],
    )

    run = ledger.get_autonomy_run(run_id)
    assert run is not None
    assert run["seed_goal"] == "finish the app"
    assert run["profile"] == "max"
    assert run["status"] == "queued"
    assert run["allowed_actions"] == ["local-build"]
    assert run["denied_actions"] == ["push"]


def test_autonomy_tasks_checkpoint_status(ledger: Ledger) -> None:
    run_id = ledger.create_autonomy_run("build auth", profile="balanced")
    task_id = ledger.add_autonomy_task(
        run_id=run_id,
        prompt="write auth tests",
        task_type="tests",
        preferred_tool="codex-cli",
        preferred_subagent="test-gen",
        priority=10,
    )

    ledger.update_autonomy_task(task_id, status="completed", artifact_ids=["a1", "a2"])

    tasks = ledger.list_autonomy_tasks(run_id)
    assert len(tasks) == 1
    assert tasks[0]["status"] == "completed"
    assert tasks[0]["artifact_ids"] == ["a1", "a2"]


def test_usage_observations_round_trip(ledger: Ledger) -> None:
    run_id = ledger.create_autonomy_run("finish feature", profile="balanced")
    ledger.insert_usage_observation(
        run_id=run_id,
        tool="codex-cli",
        event_type="success",
        task_type="tests",
        latency_ms=1200,
        success=True,
        message="tests passed",
    )

    observations = ledger.list_usage_observations(run_id)
    assert len(observations) == 1
    assert observations[0]["tool"] == "codex-cli"
    assert observations[0]["success"] is True
    assert observations[0]["latency_ms"] == 1200
