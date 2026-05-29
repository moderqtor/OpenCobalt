"""Tests for CostTracker in opencobalt.core.cost."""

from pathlib import Path

import pytest

from opencobalt.core.cost import MODEL_REGISTRY, CostTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tracker(tmp_path: Path) -> CostTracker:
    return CostTracker(tmp_path / "cost_test.db")


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------

def test_estimate_cost_known_model(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    # Use claude-sonnet-4-6: 0.003/1k input, 0.015/1k output
    entry = MODEL_REGISTRY["claude-sonnet-4-6"]
    input_tokens = 2000
    output_tokens = 500
    expected = (
        input_tokens / 1000.0 * entry["cost_per_1k_input"]
        + output_tokens / 1000.0 * entry["cost_per_1k_output"]
    )
    result = tracker.estimate_cost("claude-sonnet-4-6", input_tokens, output_tokens)
    assert result == pytest.approx(expected)


def test_estimate_cost_unknown_model_returns_zero(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    result = tracker.estimate_cost("no-such-model", 1000, 1000)
    assert result == pytest.approx(0.0)


def test_estimate_cost_ollama_is_zero(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    result = tracker.estimate_cost("ollama", 10000, 10000)
    assert result == pytest.approx(0.0)


def test_estimate_cost_zero_tokens(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    result = tracker.estimate_cost("gpt-4o", 0, 0)
    assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# record_run and monthly_spend accumulation
# ---------------------------------------------------------------------------

def test_record_run_returns_cost_record(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    record = tracker.record_run("gpt-4o", 1000, 500, "standard")
    assert record.model_id == "gpt-4o"
    assert record.input_tokens == 1000
    assert record.output_tokens == 500
    assert record.routing_mode == "standard"
    assert record.cost_usd >= 0.0
    assert record.id  # non-empty UUID


def test_monthly_spend_starts_at_zero(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    assert tracker.monthly_spend() == pytest.approx(0.0)


def test_monthly_spend_accumulates_across_record_run(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    entry = MODEL_REGISTRY["claude-sonnet-4-6"]
    tokens_in, tokens_out = 1000, 1000

    expected_single = (
        tokens_in / 1000.0 * entry["cost_per_1k_input"]
        + tokens_out / 1000.0 * entry["cost_per_1k_output"]
    )

    tracker.record_run("claude-sonnet-4-6", tokens_in, tokens_out, "standard")
    tracker.record_run("claude-sonnet-4-6", tokens_in, tokens_out, "standard")
    tracker.record_run("claude-sonnet-4-6", tokens_in, tokens_out, "standard")

    assert tracker.monthly_spend() == pytest.approx(expected_single * 3)


# ---------------------------------------------------------------------------
# Budget cap enforcement
# ---------------------------------------------------------------------------

def test_is_over_budget_false_by_default(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    assert tracker.is_over_budget() is False


def test_is_over_budget_true_when_spend_exceeds_cap(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    # claude-opus-4 at 0.075/1k output: 70k output tokens ~= $5.25 > $5.00 default cap
    tracker.record_run("claude-opus-4", 0, 70_000, "frontier")
    assert tracker.is_over_budget() is True


def test_budget_remaining_positive_before_spend(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    assert tracker.budget_remaining() == pytest.approx(tracker.monthly_cap())


def test_budget_remaining_decreases_after_spend(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    record = tracker.record_run("gpt-4o", 1000, 500, "standard")
    remaining = tracker.budget_remaining()
    assert remaining == pytest.approx(tracker.monthly_cap() - record.cost_usd)


def test_default_monthly_cap(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    assert tracker.monthly_cap() == pytest.approx(5.00)


def test_default_per_run_cap(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    assert tracker.per_run_cap() == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Routing mode
# ---------------------------------------------------------------------------

def test_default_routing_mode(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    assert tracker.get_routing_mode() == "standard"


def test_set_routing_mode_cheap(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    tracker.set_routing_mode("cheap")
    assert tracker.get_routing_mode() == "cheap"


def test_set_routing_mode_frontier(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    tracker.set_routing_mode("frontier")
    assert tracker.get_routing_mode() == "frontier"


def test_set_routing_mode_standard(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    tracker.set_routing_mode("cheap")
    tracker.set_routing_mode("standard")
    assert tracker.get_routing_mode() == "standard"


def test_set_routing_mode_invalid_raises(tmp_path: Path) -> None:
    tracker = _tracker(tmp_path)
    with pytest.raises(ValueError, match="Unknown routing mode"):
        tracker.set_routing_mode("turbo")


def test_set_routing_mode_update_overwrites(tmp_path: Path) -> None:
    """Calling set_routing_mode twice must overwrite, not silently keep the old value."""
    tracker = _tracker(tmp_path)
    tracker.set_routing_mode("cheap")
    tracker.set_routing_mode("frontier")
    assert tracker.get_routing_mode() == "frontier"


# ---------------------------------------------------------------------------
# DB isolation
# ---------------------------------------------------------------------------

def test_separate_trackers_same_db_share_state(tmp_path: Path) -> None:
    db = tmp_path / "shared.db"
    t1 = CostTracker(db)
    t1.record_run("ollama", 100, 100, "cheap")
    t2 = CostTracker(db)
    assert t2.monthly_spend() == pytest.approx(0.0)  # ollama costs 0


def test_init_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "idem.db"
    CostTracker(db)
    CostTracker(db)  # second init must not raise


def test_model_registry_contains_required_models() -> None:
    required = {"claude-opus-4", "claude-sonnet-4-6", "gpt-4o", "gemini-pro", "ollama"}
    assert required.issubset(set(MODEL_REGISTRY.keys()))
