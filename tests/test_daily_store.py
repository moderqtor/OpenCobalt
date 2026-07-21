"""Tests for DailyStore and entity persistence."""

import pytest

from opencobalt.core.clock import FrozenClock
from opencobalt.core.daily_store import DailyStore


@pytest.fixture
def test_clock():
    return FrozenClock("2026-07-21T10:00:00+00:00")


@pytest.fixture
def daily_store(tmp_path, test_clock):
    db_path = tmp_path / "test_ledger.db"
    return DailyStore(db_path, clock=test_clock)


def test_create_and_list_captures(daily_store):
    c1 = daily_store.create_capture("Finish advocacy paper outline")
    assert c1.id.startswith("cpt-")
    assert c1.raw_text == "Finish advocacy paper outline"
    assert c1.status == "pending"

    captures = daily_store.list_captures()
    assert len(captures) == 1
    assert captures[0].id == c1.id

    daily_store.update_capture_status(c1.id, "triaged")
    assert len(daily_store.list_captures(status="pending")) == 0


def test_create_and_update_commitment(daily_store):
    cmt = daily_store.create_commitment(
        title="Email Tuition Exchange",
        due_at="2026-07-22T17:00:00+00:00",
        impact_level=4,
    )
    assert cmt.id.startswith("cmt-")
    assert cmt.title == "Email Tuition Exchange"
    assert cmt.status == "inbox"

    updated = daily_store.update_commitment_status(cmt.id, "ready")
    assert updated.status == "ready"

    events = daily_store.list_events_for_commitment(cmt.id)
    assert len(events) == 2  # created, state_changed
    assert events[0].event_type == "created"
    assert events[1].from_status == "inbox"
    assert events[1].to_status == "ready"


def test_focus_session_flow(daily_store, test_clock):
    cmt = daily_store.create_commitment("Write unit tests", status="ready")
    sess = daily_store.start_focus_session(commitment_id=cmt.id, notes="Focus on coverage")
    assert sess.id.startswith("fcs-")
    assert sess.outcome == "in_progress"

    active_cmt = daily_store.get_commitment(cmt.id)
    assert active_cmt.status == "active"

    test_clock.advance_minutes(45)
    ended = daily_store.end_focus_session(sess.id, outcome="completed", notes="All green")
    assert ended.duration_minutes == 45
    assert ended.outcome == "completed"

    completed_cmt = daily_store.get_commitment(cmt.id)
    assert completed_cmt.status == "completed"


def test_daily_review_persistence(daily_store):
    rev = daily_store.get_or_create_daily_review("2026-07-21")
    assert rev.date_stamp == "2026-07-21"

    updated = daily_store.save_daily_review(
        "2026-07-21",
        morning_plan={"focus_items": ["cmt-1"]},
        evening_review={"completed": 1},
    )
    assert "cmt-1" in updated.morning_plan_json
    assert "completed" in updated.evening_review_json
