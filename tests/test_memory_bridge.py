"""Tests for MemoryBridge SQLite-backed memory store."""

from __future__ import annotations

from pathlib import Path

from opencobalt.memory_bridge import MemoryBridge


def _bridge(tmp_path: Path) -> MemoryBridge:
    return MemoryBridge(db_path=tmp_path / "memories.db")


def test_add_and_search_round_trip(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.add("SQLite is the source of truth", agent_id="test-agent")
    results = bridge.search("SQLite", agent_id="test-agent")
    assert len(results) == 1
    assert "SQLite" in results[0]["content"]


def test_search_multi_term(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.add("router uses keyword scoring", agent_id="a1")
    bridge.add("ledger stores events", agent_id="a1")
    results = bridge.search("keyword scoring", agent_id="a1")
    assert len(results) == 1
    assert "keyword" in results[0]["content"]


def test_search_no_results(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.add("unrelated content", agent_id="a1")
    results = bridge.search("xyznonexistent", agent_id="a1")
    assert results == []


def test_search_empty_query(tmp_path):
    bridge = _bridge(tmp_path)
    results = bridge.search("", agent_id="a1")
    assert results == []


def test_add_returns_uuid(tmp_path):
    bridge = _bridge(tmp_path)
    mem_id = bridge.add("hello", agent_id="a1")
    assert len(mem_id) == 36
    assert mem_id.count("-") == 4


def test_get_session_memories(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.add("task started", agent_id="a1", session_id="sess-1")
    bridge.add("task completed", agent_id="a1", session_id="sess-1")
    bridge.add("other session", agent_id="a1", session_id="sess-2")
    mems = bridge.get_session_memories("sess-1")
    assert len(mems) == 2
    contents = {m["content"] for m in mems}
    assert "task started" in contents
    assert "task completed" in contents


def test_get_session_memories_empty(tmp_path):
    bridge = _bridge(tmp_path)
    assert bridge.get_session_memories("nonexistent") == []


def test_add_session_summary(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.add_session_summary("sess-abc", "session completed successfully", agent_id="summarizer")
    mems = bridge.get_session_memories("sess-abc")
    assert len(mems) == 1
    assert mems[0]["content"] == "session completed successfully"
    import json
    meta = json.loads(mems[0]["metadata"])
    assert meta.get("type") == "session_summary"


def test_count(tmp_path):
    bridge = _bridge(tmp_path)
    assert bridge.count() == 0
    bridge.add("one", agent_id="a")
    bridge.add("two", agent_id="a")
    assert bridge.count() == 2


def test_recent(tmp_path):
    bridge = _bridge(tmp_path)
    for i in range(5):
        bridge.add(f"memory {i}", agent_id="a")
    recent = bridge.recent(limit=3)
    assert len(recent) == 3


def test_search_filtered_by_agent(tmp_path):
    bridge = _bridge(tmp_path)
    bridge.add("shared topic routing", agent_id="agent-x")
    bridge.add("shared topic routing", agent_id="agent-y")
    results = bridge.search("routing", agent_id="agent-x")
    assert len(results) == 1
    assert results[0]["agent_id"] == "agent-x"


def test_graceful_noop_no_mem0(tmp_path, monkeypatch):
    """Bridge works without mem0 installed (which is expected -- mem0 is optional)."""
    import opencobalt.memory_bridge as mb

    original = mb._MEM0_AVAILABLE
    monkeypatch.setattr(mb, "_MEM0_AVAILABLE", False)
    bridge = _bridge(tmp_path)
    bridge.add("test", agent_id="a")
    results = bridge.search("test", agent_id="a")
    assert len(results) == 1
    mb._MEM0_AVAILABLE = original
