"""Tests for profile-aware usage optimization."""

from __future__ import annotations

from opencobalt.core.benchmark import BenchmarkRecord, BenchmarkStore
from opencobalt.core.ledger import Ledger
from opencobalt.core.usage_optimizer import UsageOptimizer


def test_optimizer_prefers_router_winner_in_balanced_mode(ledger: Ledger) -> None:
    optimizer = UsageOptimizer(ledger)

    choice = optimizer.choose_tool(
        task_type="impl",
        profile="balanced",
        router_scores={"claude-code": 12, "codex-cli": 8, "ollama": 2},
    )

    assert choice.tool == "claude-code"
    assert choice.score > 0
    assert "router" in choice.reasons


def test_optimizer_penalizes_recent_rate_limits(ledger: Ledger) -> None:
    run_id = ledger.create_autonomy_run("finish feature", profile="max")
    ledger.insert_usage_observation(
        run_id=run_id,
        tool="claude-code",
        event_type="rate_limit",
        task_type="impl",
        latency_ms=None,
        success=False,
        message="usage limit reached",
    )
    optimizer = UsageOptimizer(ledger)

    choice = optimizer.choose_tool(
        task_type="impl",
        profile="max",
        router_scores={"claude-code": 20, "codex-cli": 18},
        run_id=run_id,
    )

    assert choice.tool == "codex-cli"
    assert "rate-limit" in choice.reasons


def test_optimizer_profile_cheap_boosts_worker_tools(ledger: Ledger) -> None:
    optimizer = UsageOptimizer(ledger)

    choice = optimizer.choose_tool(
        task_type="summarize",
        profile="cheap",
        router_scores={"codex-cli": 10, "ollama": 8},
    )

    assert choice.tool == "ollama"
    assert "cheap-profile" in choice.reasons


def test_optimizer_uses_benchmark_winner_when_scores_are_close(tmp_path, ledger: Ledger) -> None:
    benchmark = BenchmarkStore(tmp_path / "bench.db")
    benchmark.record(BenchmarkRecord(
        agent_id="codex-cli",
        task_id="task-1",
        task_type="tests",
        latency_ms=100,
        success=True,
        model_used="codex",
        tier="manager",
        score=1.0,
    ))
    optimizer = UsageOptimizer(ledger, benchmark_store=benchmark)

    choice = optimizer.choose_tool(
        task_type="tests",
        profile="balanced",
        router_scores={"claude-code": 12, "codex-cli": 11},
    )

    assert choice.tool == "codex-cli"
    assert "benchmark" in choice.reasons
