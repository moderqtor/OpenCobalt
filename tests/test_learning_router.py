"""Tests for LearningRouter."""

from __future__ import annotations

from pathlib import Path

import pytest

from opencobalt.core.learning_router import LearningRouter
from opencobalt.core.ledger import Ledger


@pytest.fixture()
def router(tmp_path: Path) -> LearningRouter:
    return LearningRouter(Ledger(tmp_path / "ledger.db"))


def test_route_returns_decision(router: LearningRouter) -> None:
    decision = router.route("design the auth module")
    assert decision.recommended_tool in (
        "claude-code",
        "codex-cli",
        "google-antigravity",
        "cursor",
        "ollama",
    )
    assert decision.score > 0


def test_record_outcome_stores_to_ledger(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    router = LearningRouter(ledger)
    router.record_outcome("task-123", "claude-code", "committed")
    outcomes = ledger.list_outcomes(tool="claude-code")
    assert len(outcomes) == 1
    assert outcomes[0]["outcome"] == "committed"


def test_get_weights_returns_dict(router: LearningRouter) -> None:
    weights = router.get_weights()
    assert isinstance(weights, dict)


def test_committed_outcome_increases_weight(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    router = LearningRouter(ledger)
    for index in range(5):
        router.record_outcome(f"task-{index}", "claude-code", "committed")
    weights = router.get_weights()
    assert weights.get("claude-code", 0.0) > 0.0


def test_reverted_outcome_decreases_weight(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    router = LearningRouter(ledger)
    for index in range(5):
        router.record_outcome(f"task-{index}", "claude-code", "reverted")
    weights = router.get_weights()
    assert weights.get("claude-code", 0.0) < 0.0


def test_weight_capped_at_fifteen_percent(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    router = LearningRouter(ledger)
    for index in range(100):
        router.record_outcome(f"t{index}", "claude-code", "committed")
    weights = router.get_weights()
    assert abs(weights.get("claude-code", 0.0)) <= 0.15
