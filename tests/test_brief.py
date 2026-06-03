"""Tests for BriefGenerator."""

from __future__ import annotations

from pathlib import Path

import pytest

from opencobalt.core.brief import BriefGenerator
from opencobalt.core.ledger import Ledger
from opencobalt.core.models import RouteDecision


def _make_ledger(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "ledger.db")


def test_generates_with_empty_ledger(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate(days=7)
    assert "# OpenCobalt brief" in output
    assert "Recent Work" in output
    assert "Last Session" in output
    assert "No routing activity" in output or "No sessions" in output


def test_includes_recent_routes(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    d = RouteDecision(
        task="implement the auth module",
        recommended_tool="claude-code",
        score=86,
        reasoning="Matched keywords: implement. Tier: executive.",
        tier="executive",
        scores={"claude-code": 86},
    )
    ledger.insert_route_decision(d)

    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate(days=7)
    assert "implement the auth module" in output
    assert "claude-code" in output


def test_includes_notes(tmp_path: Path) -> None:
    import json
    import sqlite3
    from datetime import datetime, timezone

    bridge_path = tmp_path / "memories.db"
    conn = sqlite3.connect(bridge_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, content TEXT NOT NULL,
            agent_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}'
        )
    """)
    now = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO memories VALUES (?,?,?,?,?,?)",
        ("test-id", now, "SQLite is the source of truth", "user", "", json.dumps({"type": "note"})),
    )
    conn.commit()
    conn.close()

    ledger = _make_ledger(tmp_path)
    gen = BriefGenerator(ledger, bridge_path=bridge_path)
    output = gen.generate(days=7)
    assert "SQLite is the source of truth" in output


def test_copy_flag_runs_without_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--copy flag should not raise even when pbcopy isn't available."""
    calls = []

    def fake_run(cmd, input=None, check=False):  # noqa: A002
        calls.append(cmd)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    ledger = _make_ledger(tmp_path)
    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate(days=7)
    # Just verifying generate() returns non-empty string -- clipboard tested via cli
    assert len(output) > 0


def test_token_count_under_limit(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    # Seed with several routes
    for i in range(20):
        d = RouteDecision(
            task=f"task number {i} to test token limits",
            recommended_tool="claude-code",
            score=70,
            reasoning="test",
            tier="executive",
            scores={"claude-code": 70},
        )
        ledger.insert_route_decision(d)

    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate(days=7)
    word_count = len(output.split())
    # 600 words max (spec says under 600 words)
    assert word_count < 600, f"Brief too long: {word_count} words"


def test_generate_startup_is_compact(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate_startup()
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) <= 6
    assert "BRIEF" in output or "brief" in output.lower()


def test_generate_startup_with_routes(tmp_path: Path) -> None:
    ledger = _make_ledger(tmp_path)
    d = RouteDecision(
        task="implement JWT rotation",
        recommended_tool="claude-code",
        score=94,
        reasoning="test",
        tier="executive",
        scores={"claude-code": 94},
    )
    ledger.insert_route_decision(d)
    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate_startup()
    assert "claude-code" in output or "JWT" in output
