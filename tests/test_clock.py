"""Tests for Clock abstraction."""

from datetime import datetime, timezone

from opencobalt.core.clock import FrozenClock, SystemClock


def test_system_clock_returns_utc_datetime():
    clock = SystemClock()
    now = clock.now()
    assert isinstance(now, datetime)
    assert now.tzinfo == timezone.utc
    assert isinstance(clock.now_iso(), str)


def test_frozen_clock_time_travel():
    initial = "2026-07-21T12:00:00+00:00"
    clock = FrozenClock(initial)
    assert clock.now_iso() == "2026-07-21T12:00:00+00:00"

    clock.advance_minutes(30)
    assert clock.now_iso() == "2026-07-21T12:30:00+00:00"

    clock.advance_days(1)
    assert clock.now_iso() == "2026-07-22T12:30:00+00:00"

    clock.set_time("2026-08-01T00:00:00Z")
    assert clock.now().month == 8
