"""Unit tests for DailyOperatorService."""

import pytest

from opencobalt.core.clock import FrozenClock
from opencobalt.core.daily_operator import DailyOperatorService


@pytest.fixture
def test_clock():
    return FrozenClock("2026-07-21T09:00:00+00:00")


@pytest.fixture
def operator_service(tmp_path, test_clock):
    db_path = tmp_path / "test_ledger.db"
    return DailyOperatorService(db_path, clock=test_clock)


def test_capture_and_inbox_flow(operator_service):
    c1 = operator_service.capture("Finish advocacy paper outline")
    assert c1.id.startswith("cpt-")
    assert c1.raw_text == "Finish advocacy paper outline"

    inbox = operator_service.get_inbox()
    assert len(inbox) == 1
    assert inbox[0].id == c1.id


def test_clarify_capture_creates_commitment(operator_service):
    c1 = operator_service.capture("Email Tuition Exchange")
    cmt = operator_service.clarify_capture(
        c1.id,
        title="Email Tuition Exchange about missing award",
        impact_level=4,
        due_at="2026-07-22T17:00:00+00:00",
    )
    assert cmt.id.startswith("cmt-")
    assert cmt.title == "Email Tuition Exchange about missing award"
    assert cmt.status == "ready"
    assert len(operator_service.get_inbox()) == 0


def test_today_dashboard_and_next_recommendation(operator_service, test_clock):
    c1 = operator_service.capture("Task 1")
    cmt1 = operator_service.clarify_capture(c1.id, title="Urgent Task", impact_level=5, due_at="2026-07-21T12:00:00+00:00")
    c2 = operator_service.capture("Task 2")
    operator_service.clarify_capture(c2.id, title="Normal Task", impact_level=2)

    dashboard = operator_service.get_today_dashboard()
    assert dashboard["date_stamp"] == "2026-07-21"
    assert dashboard["next_action"]["commitment"]["id"] == cmt1.id
    assert len(dashboard["later_today"]) == 1

    next_rec = operator_service.get_next_recommendation()
    assert next_rec["commitment"]["id"] == cmt1.id
    assert "Urgent Task" in next_rec["commitment"]["title"]


def test_focus_and_done_workflow(operator_service, test_clock):
    c1 = operator_service.capture("Write report")
    cmt = operator_service.clarify_capture(c1.id, title="Write report")

    sess = operator_service.focus_start(cmt.id, notes="Drafting intro")
    assert sess.commitment_id == cmt.id

    status = operator_service.focus_status()
    assert status["commitment"]["id"] == cmt.id

    test_clock.advance_minutes(30)
    done_res = operator_service.done(cmt.id, outcome_summary="Report drafted successfully", follow_up_title="Send for review")

    assert done_res["commitment"]["status"] == "completed"
    assert done_res["follow_up"]["title"] == "Send for review"
    assert operator_service.focus_status() is None


def test_defer_and_waiting(operator_service):
    c1 = operator_service.capture("Waiting item")
    cmt = operator_service.clarify_capture(c1.id, title="Waiting for logs")

    def_cmt = operator_service.defer(cmt.id, until_iso="2026-07-25T00:00:00Z", reason="On vacation")
    assert def_cmt.status == "deferred"

    wait_cmt = operator_service.waiting(cmt.id, for_ref="Colin approval")
    assert wait_cmt.status == "waiting"
    assert wait_cmt.waiting_on_ref == "Colin approval"


def test_review_day_and_search(operator_service):
    c1 = operator_service.capture("Searchable research topic")
    cmt = operator_service.clarify_capture(c1.id, title="Searchable research topic")
    operator_service.done(cmt.id, outcome_summary="Done")

    review = operator_service.review_day("2026-07-21")
    assert review["scorecard"]["completed_count"] == 1

    search_res = operator_service.search("research topic")
    assert len(search_res["commitments"]) == 1
