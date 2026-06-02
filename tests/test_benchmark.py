"""Tests for BenchmarkRecord and BenchmarkStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from opencobalt.core.benchmark import BenchmarkRecord, BenchmarkStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _store(tmp_path: Path) -> BenchmarkStore:
    return BenchmarkStore(tmp_path / "bench_test.db")


def _record(
    agent_id: str = "agent-a",
    task_type: str = "review",
    latency_ms: int = 500,
    success: bool = True,
    score: float = 0.9,
) -> BenchmarkRecord:
    return BenchmarkRecord(
        agent_id=agent_id,
        task_id="task-1",
        task_type=task_type,
        latency_ms=latency_ms,
        success=success,
        model_used="claude-sonnet-4-6",
        tier="manager",
        score=score,
    )


# ---------------------------------------------------------------------------
# BenchmarkRecord
# ---------------------------------------------------------------------------

def test_benchmark_record_has_id() -> None:
    r = _record()
    assert r.id
    assert len(r.id) == 36  # UUID format


def test_benchmark_record_has_timestamp() -> None:
    r = _record()
    assert r.timestamp
    assert "T" in r.timestamp  # ISO format


def test_benchmark_record_fields() -> None:
    r = _record(agent_id="my-agent", task_type="summarize", latency_ms=300, success=False)
    assert r.agent_id == "my-agent"
    assert r.task_type == "summarize"
    assert r.latency_ms == 300
    assert r.success is False


# ---------------------------------------------------------------------------
# BenchmarkStore.record
# ---------------------------------------------------------------------------

def test_record_persists(tmp_path: Path) -> None:
    store = _store(tmp_path)
    r = _record()
    store.record(r)
    stats = store.get_agent_stats(r.agent_id)
    assert stats is not None
    assert stats["total"] == 1


def test_record_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    r = _record()
    store.record(r)
    store.record(r)  # same id -- INSERT OR IGNORE
    stats = store.get_agent_stats(r.agent_id)
    assert stats["total"] == 1


def test_init_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "idem.db"
    BenchmarkStore(db)
    BenchmarkStore(db)  # second init must not raise


# ---------------------------------------------------------------------------
# BenchmarkStore.get_agent_stats
# ---------------------------------------------------------------------------

def test_get_agent_stats_none_when_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.get_agent_stats("ghost-agent") is None


def test_get_agent_stats_returns_correct_win_rate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(_record(success=True))
    store.record(BenchmarkRecord(
        agent_id="agent-a", task_id="t2", task_type="review",
        latency_ms=600, success=False, model_used="m", tier="worker", score=0.5,
    ))
    stats = store.get_agent_stats("agent-a")
    assert stats is not None
    assert stats["total"] == 2
    assert stats["wins"] == 1
    assert stats["win_rate"] == pytest.approx(0.5)


def test_get_agent_stats_latency_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(BenchmarkRecord(
        agent_id="agent-b", task_id="t1", task_type="tag",
        latency_ms=200, success=True, model_used="m", tier="worker", score=1.0,
    ))
    store.record(BenchmarkRecord(
        agent_id="agent-b", task_id="t2", task_type="tag",
        latency_ms=400, success=True, model_used="m", tier="worker", score=1.0,
    ))
    stats = store.get_agent_stats("agent-b")
    assert stats["min_latency_ms"] == 200
    assert stats["max_latency_ms"] == 400
    assert stats["avg_latency_ms"] == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# BenchmarkStore.get_leaderboard
# ---------------------------------------------------------------------------

def test_leaderboard_empty_when_no_records(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.get_leaderboard() == []


def test_leaderboard_ranked_by_composite_score(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # agent-fast: 100% win rate, low latency -> high composite
    store.record(BenchmarkRecord(
        agent_id="agent-fast", task_id="t1", task_type="review",
        latency_ms=100, success=True, model_used="m", tier="worker", score=1.0,
    ))
    # agent-slow: 100% win rate, high latency -> lower speed_score
    store.record(BenchmarkRecord(
        agent_id="agent-slow", task_id="t2", task_type="review",
        latency_ms=5000, success=True, model_used="m", tier="worker", score=1.0,
    ))
    lb = store.get_leaderboard()
    assert len(lb) == 2
    assert lb[0]["agent_id"] == "agent-fast"
    assert lb[0]["composite_score"] > lb[1]["composite_score"]


def test_leaderboard_respects_n_limit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for i in range(5):
        store.record(BenchmarkRecord(
            agent_id=f"agent-{i}", task_id=f"t{i}", task_type="review",
            latency_ms=500, success=True, model_used="m", tier="worker", score=1.0,
        ))
    lb = store.get_leaderboard(n=3)
    assert len(lb) == 3


def test_leaderboard_entry_has_required_keys(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(_record())
    lb = store.get_leaderboard()
    entry = lb[0]
    assert "agent_id" in entry
    assert "total" in entry
    assert "win_rate" in entry
    assert "avg_latency_ms" in entry
    assert "composite_score" in entry


# ---------------------------------------------------------------------------
# BenchmarkStore.get_best_for_task_type
# ---------------------------------------------------------------------------

def test_get_best_for_task_type_none_when_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.get_best_for_task_type("unknown-type") is None


def test_get_best_for_task_type_returns_winner(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # agent-a: 100% wins, fast
    for _ in range(3):
        store.record(BenchmarkRecord(
            agent_id="agent-a", task_id=f"t-{_}", task_type="summarize",
            latency_ms=200, success=True, model_used="m", tier="worker", score=1.0,
        ))
    # agent-b: 0% wins, slow
    store.record(BenchmarkRecord(
        agent_id="agent-b", task_id="tb1", task_type="summarize",
        latency_ms=3000, success=False, model_used="m", tier="worker", score=0.0,
    ))
    best = store.get_best_for_task_type("summarize")
    assert best == "agent-a"


def test_get_best_for_task_type_filters_by_type(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(BenchmarkRecord(
        agent_id="agent-review", task_id="r1", task_type="review",
        latency_ms=100, success=True, model_used="m", tier="worker", score=1.0,
    ))
    store.record(BenchmarkRecord(
        agent_id="agent-tag", task_id="t1", task_type="tag",
        latency_ms=100, success=True, model_used="m", tier="worker", score=1.0,
    ))
    assert store.get_best_for_task_type("review") == "agent-review"
    assert store.get_best_for_task_type("tag") == "agent-tag"
    assert store.get_best_for_task_type("unknown") is None
