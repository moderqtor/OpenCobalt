"""Tests for DailyPriorityEngine score calculation and explanation."""

import pytest

from opencobalt.core.clock import FrozenClock
from opencobalt.core.daily_priority import DailyPriorityEngine
from opencobalt.core.daily_store import CommitmentRecord


@pytest.fixture
def test_clock():
    return FrozenClock("2026-07-21T12:00:00+00:00")


@pytest.fixture
def priority_engine(test_clock):
    return DailyPriorityEngine(clock=test_clock)


def test_base_priority_calculation(priority_engine):
    cmt = CommitmentRecord(id="cmt-1", title="Basic task", impact_level=3)
    exp = priority_engine.evaluate(cmt)
    # base 100 + impact level 3 (100) = 200
    assert exp.calculated_score == 200
    assert exp.components["base_score"] == 100
    assert exp.components["impact_score"] == 100
    assert len(exp.rationale) >= 2


def test_urgency_scoring(priority_engine):
    # Due in 6 hours: urgency_score = 300 * (1 - 6/24) = 225
    cmt = CommitmentRecord(
        id="cmt-urgent",
        title="Urgent task",
        due_at="2026-07-21T18:00:00+00:00",
        impact_level=4,  # 180
    )
    exp = priority_engine.evaluate(cmt)
    assert exp.components["urgency_score"] == 225
    assert exp.calculated_score == 100 + 225 + 180  # 505


def test_overdue_scoring(priority_engine):
    # Overdue by 2 hours: min(400, 300 + 20) = 320
    cmt = CommitmentRecord(
        id="cmt-overdue",
        title="Overdue task",
        due_at="2026-07-21T10:00:00+00:00",
        impact_level=5,  # 250
    )
    exp = priority_engine.evaluate(cmt)
    assert exp.components["urgency_score"] == 320
    assert exp.calculated_score == 100 + 320 + 250  # 670


def test_penalty_scoring(priority_engine):
    cmt_blocked = CommitmentRecord(id="cmt-b", title="Blocked task", status="blocked")
    exp_b = priority_engine.evaluate(cmt_blocked)
    assert exp_b.components["penalty_score"] == 300
    assert exp_b.calculated_score == max(0, 100 + 100 - 300)  # 0


def test_deterministic_sorting(priority_engine):
    c1 = CommitmentRecord(id="cmt-low", title="Low task", impact_level=1)
    c2 = CommitmentRecord(id="cmt-high", title="High task", impact_level=5)
    sorted_items = priority_engine.sort_commitments([c1, c2])
    assert sorted_items[0][0].id == "cmt-high"
    assert sorted_items[1][0].id == "cmt-low"
