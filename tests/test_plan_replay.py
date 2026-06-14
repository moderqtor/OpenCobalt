"""Tests for execution plan replay.

No live agent calls; execution uses the noop adapter (/bin/echo) only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opencobalt.execution import ExecutionEngine, ExecutionStore, ProcessRunner


def _engine(tmp_path: Path) -> ExecutionEngine:
    return ExecutionEngine(
        store=ExecutionStore(tmp_path / "ledger.db"),
        runner=ProcessRunner(artifact_dir=tmp_path / "artifacts"),
        events_path=tmp_path / "events.jsonl",
    )


def _stored_plan(engine: ExecutionEngine, task: str = "say hello"):
    outcome = engine.run_task(task, runtime="noop")
    return outcome.plan


class TestReplayDryRun:
    def test_replay_creates_new_plan_and_receipt(self, tmp_path):
        engine = _engine(tmp_path)
        original = _stored_plan(engine)
        outcome = engine.replay_plan(original.plan_id)

        assert outcome.plan.plan_id != original.plan_id
        assert outcome.plan.task == original.task
        assert outcome.receipt.route_reason == f"replay of plan {original.plan_id}"
        assert outcome.result is None
        assert outcome.plan.dry_run is True

    def test_replay_reuses_stored_command_plan(self, tmp_path):
        engine = _engine(tmp_path)
        original = _stored_plan(engine, "say hello")
        outcome = engine.replay_plan(original.plan_id)
        assert outcome.plan.steps[0].command_argv == original.steps[0].command_argv
        assert outcome.receipt.command_plan == original.steps[0].command_argv
        assert outcome.receipt.adapter_id == "noop"
        assert outcome.receipt.normalized_invocation is not None
        assert outcome.receipt.normalized_receipt is not None
        assert outcome.receipt.normalized_receipt.status == "skipped"

    def test_replay_is_persisted(self, tmp_path):
        engine = _engine(tmp_path)
        original = _stored_plan(engine)
        outcome = engine.replay_plan(original.plan_id)
        assert engine.store.get_plan(outcome.plan.plan_id) is not None
        assert engine.store.get_receipt(outcome.receipt.receipt_id) is not None

    def test_replay_emits_replay_event(self, tmp_path):
        engine = _engine(tmp_path)
        original = _stored_plan(engine)
        outcome = engine.replay_plan(original.plan_id)
        types = [e["event_type"] for e in outcome.events]
        assert "plan.replayed" in types
        assert "receipt.created" in types

    def test_unknown_plan_raises(self, tmp_path):
        engine = _engine(tmp_path)
        with pytest.raises(KeyError):
            engine.replay_plan("no-such-plan")


class TestReplayExecution:
    def test_replay_executes_stored_command(self, tmp_path):
        engine = _engine(tmp_path)
        original = _stored_plan(engine, "say hello")
        outcome = engine.replay_plan(original.plan_id, execute=True)

        assert outcome.result is not None
        assert outcome.result.status == "succeeded"
        assert "say hello" in outcome.result.stdout_preview
        assert outcome.receipt.artifact_ids

    def test_replay_verifies_receipt_after_execution(self, tmp_path):
        engine = _engine(tmp_path)
        original = _stored_plan(engine)
        outcome = engine.replay_plan(original.plan_id, execute=True)
        assert outcome.receipt.verification_status == "verified"

    def test_timeout_override_applies(self, tmp_path):
        engine = _engine(tmp_path)
        original = _stored_plan(engine)
        outcome = engine.replay_plan(original.plan_id, timeout_seconds=7)
        assert outcome.plan.steps[0].timeout_seconds == 7


class TestReplayPolicy:
    def test_red_replay_requires_approval(self, tmp_path):
        engine = _engine(tmp_path)
        original = engine.run_task("rotate the deploy credential", runtime="noop").plan
        assert original.risk_level == "red"

        blocked = engine.replay_plan(original.plan_id, execute=True)
        assert blocked.policy.allowed is False
        assert blocked.result is None

        approved = engine.replay_plan(original.plan_id, execute=True, approved=True)
        assert approved.policy.allowed is True

    def test_black_replay_stays_blocked(self, tmp_path):
        engine = _engine(tmp_path)
        original = engine.run_task("rm -rf the build directory", runtime="noop").plan
        assert original.risk_level == "black"

        outcome = engine.replay_plan(original.plan_id, execute=True, approved=True)
        assert outcome.policy.allowed is False
        assert outcome.result is None

    def test_black_replay_dry_run_allowed(self, tmp_path):
        engine = _engine(tmp_path)
        original = engine.run_task("rm -rf the build directory", runtime="noop").plan
        outcome = engine.replay_plan(original.plan_id)
        assert outcome.policy.allowed is True
        assert outcome.result is None
