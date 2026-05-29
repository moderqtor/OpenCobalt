"""Tests for the session tracking module."""

from __future__ import annotations

from opencobalt.core.session import SessionManager


def test_session_inactive_by_default(db_path):
    mgr = SessionManager(db_path)
    assert mgr.active() is None
    assert mgr.started_at() is None


def test_session_start_and_active(db_path):
    mgr = SessionManager(db_path)
    mgr.start("my-session")
    assert mgr.active() == "my-session"
    assert mgr.started_at() is not None


def test_session_end_returns_name(db_path):
    mgr = SessionManager(db_path)
    mgr.start("sprint-12")
    name = mgr.end()
    assert name == "sprint-12"


def test_session_end_clears_active(db_path):
    mgr = SessionManager(db_path)
    mgr.start("some-session")
    mgr.end()
    assert mgr.active() is None
    assert mgr.started_at() is None


def test_session_end_without_start_returns_none(db_path):
    mgr = SessionManager(db_path)
    result = mgr.end()
    assert result is None


def test_session_overwrite(db_path):
    mgr = SessionManager(db_path)
    mgr.start("first")
    mgr.start("second")  # overwrites
    assert mgr.active() == "second"


def test_session_start_records_timestamp(db_path):
    mgr = SessionManager(db_path)
    mgr.start("timed-session")
    ts = mgr.started_at()
    assert ts is not None
    assert "T" in ts  # ISO 8601 format
