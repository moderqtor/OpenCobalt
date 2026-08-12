"""End-to-end integration and dogfooding test suite for OpenCobalt Daily Operator.

Tests the full 9-step loop:
capture -> clarify -> prioritize -> choose next action -> focus -> complete/defer -> record outcome -> review -> continue/why
"""

from typer.testing import CliRunner

from opencobalt.core.clock import FrozenClock
from opencobalt.core.daily_operator import DailyOperatorService

runner = CliRunner()


def test_full_daily_operator_dogfood_scenario(tmp_path, monkeypatch):
    db_file = tmp_path / "dogfood_ledger.db"
    monkeypatch.setattr("opencobalt.core.config.get_db_path", lambda: db_file)

    clock = FrozenClock("2026-07-21T08:00:00+00:00")
    service = DailyOperatorService(db_file, clock=clock)

    # 1. Capture multiple items (assignments, admin obligations, multi-step tasks)
    c1 = service.capture("Finish expanded advocacy paper outline", source="cli")
    c2 = service.capture("Email Tuition Exchange about missing award", source="cli")
    c3 = service.capture("Refactor OpenCobalt daily operator CLI tests", source="cli")
    c4 = service.capture("Buy coffee beans", source="cli")

    assert len(service.get_inbox()) == 4

    # 2. Clarify items into commitments with priority attributes
    cmt1 = service.clarify_capture(
        c1.id,
        title="Finish expanded advocacy paper outline",
        impact_level=5,
        estimated_minutes=60,
        due_at="2026-07-21T18:00:00+00:00",
    )
    cmt2 = service.clarify_capture(
        c2.id,
        title="Email Tuition Exchange about missing award",
        impact_level=4,
        estimated_minutes=15,
        due_at="2026-07-22T12:00:00+00:00",
    )
    cmt3 = service.clarify_capture(
        c3.id,
        title="Refactor OpenCobalt daily operator CLI tests",
        impact_level=3,
        estimated_minutes=45,
    )
    # Discard c4
    service.clarify_capture(c4.id, actionable=False)

    assert len(service.get_inbox()) == 0

    # 3. Check today dashboard and next recommendation
    dashboard = service.get_today_dashboard()
    assert dashboard["next_action"]["commitment"]["id"] == cmt1.id
    assert len(dashboard["later_today"]) == 2

    next_rec = service.get_next_recommendation()
    assert next_rec["commitment"]["id"] == cmt1.id

    # 4. Start focus session on top item (cmt1)
    service.focus_start(cmt1.id, notes="Working on section 1")
    assert service.focus_status()["commitment"]["id"] == cmt1.id

    # 5. Simulate interruption (phone call / urgent email)
    c_interrupt = service.capture("Urgent call with advisor")
    cmt_interrupt = service.clarify_capture(c_interrupt.id, title="Urgent call with advisor", impact_level=5, due_at="2026-07-21T09:00:00+00:00")

    # Start focus on urgent item (auto-interrupts fcs1)
    service.focus_start(cmt_interrupt.id, notes="Taking call")
    assert service.focus_status()["commitment"]["id"] == cmt_interrupt.id

    # Finish urgent item
    service.done(cmt_interrupt.id, outcome_summary="Call completed and notes recorded")

    # 6. Defer cmt2 and mark cmt3 as waiting
    service.defer(cmt2.id, until_iso="2026-07-25T00:00:00Z", reason="Waiting for office hours")
    service.waiting(cmt3.id, for_ref="Colin review", reason="Submitted PR for review")

    # Resume cmt1 focus and complete it
    service.focus_start(cmt1.id, notes="Resuming section 2")
    clock.advance_minutes(50)
    done_res = service.done(cmt1.id, outcome_summary="Completed advocacy paper outline", follow_up_title="Submit outline to professor")

    assert done_res["commitment"]["status"] == "completed"
    assert done_res["follow_up"]["title"] == "Submit outline to professor"

    # 7. Execute Daily Review
    review_res = service.review_day("2026-07-21")
    assert review_res["scorecard"]["completed_count"] == 2
    assert review_res["scorecard"]["deferred_count"] == 1
    assert review_res["scorecard"]["waiting_count"] == 1

    # 8. Provenance Lineage Verification via why
    why_res = service.why(cmt1.id)
    assert why_res["daily_metadata"]["type"] == "commitment"
    assert why_res["daily_metadata"]["commitment"]["id"] == cmt1.id
    assert len(why_res["daily_metadata"]["events"]) >= 2
