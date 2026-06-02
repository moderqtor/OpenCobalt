"""Tests for ObservabilitySession SQLite-backed session tracking."""

from __future__ import annotations

from pathlib import Path

from opencobalt.observability import ObservabilitySession


def _obs(tmp_path: Path) -> ObservabilitySession:
    return ObservabilitySession(db_path=tmp_path / "observability.db")


def test_start_session_returns_uuid(tmp_path):
    obs = _obs(tmp_path)
    sid = obs.start_session("summarizer", "summarize file", "llama3")
    assert len(sid) == 36
    assert sid.count("-") == 4


def test_end_session_success(tmp_path):
    obs = _obs(tmp_path)
    sid = obs.start_session("tagger", "tag notes", "llama3")
    obs.end_session(sid, success=True, cost=0.001)
    report = obs.get_session_report(sid)
    assert report is not None
    assert report["success"] is True
    assert report["cost_usd"] == 0.001


def test_end_session_failure(tmp_path):
    obs = _obs(tmp_path)
    sid = obs.start_session("code-reviewer", "review module", "claude")
    obs.end_session(sid, success=False)
    report = obs.get_session_report(sid)
    assert report["success"] is False


def test_record_tool_call(tmp_path):
    obs = _obs(tmp_path)
    sid = obs.start_session("a1", "task", "m1")
    obs.record_tool_call(sid, "file-reader", input_tokens=100, output_tokens=200, latency_ms=50)
    obs.end_session(sid, success=True)
    report = obs.get_session_report(sid)
    assert len(report["tool_calls"]) == 1
    call = report["tool_calls"][0]
    assert call["tool_name"] == "file-reader"
    assert call["input_tokens"] == 100
    assert call["latency_ms"] == 50


def test_multiple_tool_calls(tmp_path):
    obs = _obs(tmp_path)
    sid = obs.start_session("a1", "task", "m1")
    obs.record_tool_call(sid, "file-reader", latency_ms=30)
    obs.record_tool_call(sid, "diff-writer", latency_ms=20)
    obs.end_session(sid, success=True)
    report = obs.get_session_report(sid)
    assert len(report["tool_calls"]) == 2


def test_get_session_report_not_found(tmp_path):
    obs = _obs(tmp_path)
    assert obs.get_session_report("nonexistent-uuid") is None


def test_count_sessions(tmp_path):
    obs = _obs(tmp_path)
    assert obs.count_sessions() == 0
    obs.start_session("a1", "t1", "m1")
    obs.start_session("a2", "t2", "m2")
    assert obs.count_sessions() == 2


def test_recent_sessions(tmp_path):
    obs = _obs(tmp_path)
    for i in range(5):
        obs.start_session(f"agent-{i}", f"task {i}", "model")
    recent = obs.recent_sessions(limit=3)
    assert len(recent) == 3


def test_summary_stats_empty(tmp_path):
    obs = _obs(tmp_path)
    stats = obs.summary_stats()
    assert stats["total"] == 0
    assert stats["success_rate"] == 0.0


def test_summary_stats_with_data(tmp_path):
    obs = _obs(tmp_path)
    s1 = obs.start_session("a", "t", "m")
    obs.end_session(s1, success=True, cost=0.01)
    s2 = obs.start_session("a", "t", "m")
    obs.end_session(s2, success=False, cost=0.02)
    stats = obs.summary_stats()
    assert stats["total"] == 2
    assert stats["success_rate"] == 0.5
    assert abs(stats["total_cost_usd"] - 0.03) < 1e-9


def test_session_lifecycle(tmp_path):
    """Full lifecycle: start -> tool calls -> end -> report."""
    obs = _obs(tmp_path)
    sid = obs.start_session("context-builder", "compile docs", "llama3")
    obs.record_tool_call(sid, "file-reader", input_tokens=500, output_tokens=0, latency_ms=80)
    obs.end_session(sid, success=True, cost=0.0)
    report = obs.get_session_report(sid)
    assert report["agent_id"] == "context-builder"
    assert report["task"] == "compile docs"
    assert report["ended_at"] is not None
    assert len(report["tool_calls"]) == 1
