"""Tests for the bounded evaluator loop. No external calls."""

from __future__ import annotations

import pytest

from opencobalt.core.evaluator_loop import (
    EVENT_CANDIDATE_EVALUATED,
    EVENT_LOOP_FINISHED,
    HARD_ITERATION_CAP,
    EvaluatorLoop,
)
from opencobalt.execution.store import ExecutionStore


class TestBounds:
    def test_max_iterations_enforced(self) -> None:
        calls = {"n": 0}

        def evaluate(payload):
            calls["n"] += 1
            return 0.0

        loop = EvaluatorLoop(propose=lambda: 1, evaluate=evaluate, max_iterations=5)
        outcome = loop.run("bounded")
        assert outcome.iterations == 5
        assert calls["n"] == 5
        assert outcome.stopped_reason == "max_iterations"

    def test_hard_cap_rejected(self) -> None:
        with pytest.raises(ValueError):
            EvaluatorLoop(
                propose=lambda: 1, evaluate=lambda p: 0.0,
                max_iterations=HARD_ITERATION_CAP + 1,
            )

    def test_invalid_timeout_rejected(self) -> None:
        with pytest.raises(ValueError):
            EvaluatorLoop(propose=lambda: 1, evaluate=lambda p: 0.0, timeout_seconds=0)

    def test_timeout_stops_loop(self, monkeypatch) -> None:
        import opencobalt.core.evaluator_loop as mod

        clock = {"t": 0.0}

        def fake_monotonic():
            clock["t"] += 100.0
            return clock["t"]

        monkeypatch.setattr(mod.time, "monotonic", fake_monotonic)
        loop = EvaluatorLoop(
            propose=lambda: 1, evaluate=lambda p: 0.0,
            max_iterations=50, timeout_seconds=10.0,
        )
        outcome = loop.run("timed")
        assert outcome.stopped_reason == "timeout"
        assert outcome.iterations < 50


class TestSearch:
    def test_keeps_best_candidate_with_mutation(self) -> None:
        loop = EvaluatorLoop(
            propose=lambda: 1,
            evaluate=lambda p: float(p),
            mutate=lambda best, score: best + 1,
            max_iterations=4,
        )
        outcome = loop.run("hill-climb")
        assert outcome.best is not None
        assert outcome.best.payload == 4
        assert outcome.best.score == 4.0
        assert [c.payload for c in outcome.history] == [1, 2, 3, 4]

    def test_target_score_converges_early(self) -> None:
        loop = EvaluatorLoop(
            propose=lambda: 1,
            evaluate=lambda p: float(p),
            mutate=lambda best, score: best + 1,
            max_iterations=100,
            target_score=3.0,
        )
        outcome = loop.run("converge")
        assert outcome.stopped_reason == "converged"
        assert outcome.iterations == 3

    def test_events_emitted(self) -> None:
        loop = EvaluatorLoop(propose=lambda: 1, evaluate=lambda p: 1.0, max_iterations=2)
        outcome = loop.run("events")
        types = [e["event_type"] for e in outcome.events]
        assert types.count(EVENT_CANDIDATE_EVALUATED) == 2
        assert types[-1] == EVENT_LOOP_FINISHED


class TestReceipts:
    def test_receipt_and_artifact_written(self, tmp_path) -> None:
        store = ExecutionStore(tmp_path / "ledger.db")
        loop = EvaluatorLoop(
            propose=lambda: 1,
            evaluate=lambda p: float(p),
            mutate=lambda best, score: best + 1,
            max_iterations=3,
            store=store,
            artifact_dir=tmp_path / "evaluator",
        )
        outcome = loop.run("receipted")
        assert outcome.receipt_id is not None
        receipt = store.get_receipt(outcome.receipt_id)
        assert receipt is not None
        assert receipt.selected_runtime == "local-evaluator"
        assert receipt.artifact_ids
        artifact = store.get_artifact(receipt.artifact_ids[0])
        assert artifact is not None and artifact.sha256
        # history artifact is replayable JSON on disk
        assert (tmp_path / "evaluator" / f"{outcome.loop_id}.json").exists()

    def test_no_store_means_no_receipt(self) -> None:
        loop = EvaluatorLoop(propose=lambda: 1, evaluate=lambda p: 0.0, max_iterations=1)
        outcome = loop.run("plain")
        assert outcome.receipt_id is None
