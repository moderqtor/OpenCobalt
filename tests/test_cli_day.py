"""Tests for the `opencobalt day` CLI command."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.core.ledger import Ledger
from opencobalt.core.models import RouteDecision
from opencobalt.memory_bridge import MemoryBridge

runner = CliRunner()

_TODAY = datetime.now(tz=timezone.utc).date().isoformat()


def _invoke(tmp_path: Path, monkeypatch, *args: str):
    monkeypatch.chdir(tmp_path)
    return runner.invoke(app, list(args))


def _debug(result) -> str:
    exc = ""
    if result.exception:
        import traceback
        exc = "".join(
            traceback.format_exception(
                type(result.exception), result.exception, result.exception.__traceback__
            )
        )
    return f"\n--- output ---\n{result.output}\n--- exception ---\n{exc}"


def _ledger(tmp_path: Path) -> Ledger:
    db = tmp_path / ".opencobalt" / "ledger.db"
    return Ledger(db)


def _bridge(tmp_path: Path) -> MemoryBridge:
    return MemoryBridge(db_path=tmp_path / ".opencobalt" / "memories.db")


class TestDayCommand:
    def test_day_no_activity(self, tmp_path, monkeypatch):
        """Empty ledger and bridge yields 'No activity logged' message."""
        result = _invoke(tmp_path, monkeypatch, "day")
        assert result.exit_code == 0, _debug(result)
        assert "No activity logged" in result.output, _debug(result)

    def test_day_shows_routes(self, tmp_path, monkeypatch):
        """Route decisions for today appear in day output."""
        ledger = _ledger(tmp_path)
        decision = RouteDecision(
            task="test routing task",
            recommended_tool="claude-code",
            score=10,
            reasoning="test",
            tier="executive",
        )
        ledger.insert_route_decision(decision)

        result = _invoke(tmp_path, monkeypatch, "day")
        assert result.exit_code == 0, _debug(result)
        assert "ROUTES TODAY" in result.output, _debug(result)
        assert "test routing task" in result.output, _debug(result)

    def test_day_shows_notes(self, tmp_path, monkeypatch):
        """Notes stored for today appear in day output."""
        bridge = _bridge(tmp_path)
        bridge.add("my day note", agent_id="user", metadata={"type": "note", "tags": []})

        result = _invoke(tmp_path, monkeypatch, "day")
        assert result.exit_code == 0, _debug(result)
        assert "NOTES TODAY" in result.output, _debug(result)
        assert "my day note" in result.output, _debug(result)

    def test_day_date_filter(self, tmp_path, monkeypatch):
        """Route decisions on a different date do not appear for today."""
        decision = RouteDecision(
            task="yesterday task",
            recommended_tool="ollama",
            score=5,
            reasoning="test",
            tier="worker",
        )
        # Manually insert with a past date -- initialize the schema first
        import json
        import sqlite3
        _ledger(tmp_path)  # creates the .opencobalt dir and schema
        db_path = tmp_path / ".opencobalt" / "ledger.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT OR IGNORE INTO route_decisions VALUES (?,?,?,?,?,?,?,?)",
            (
                decision.id,
                "2020-01-01T00:00:00+00:00",
                decision.task,
                decision.recommended_tool,
                decision.score,
                decision.reasoning,
                decision.tier,
                json.dumps({}),
            ),
        )
        conn.commit()
        conn.close()

        result = _invoke(tmp_path, monkeypatch, "day")
        # Should show no activity for today since nothing is dated today
        assert "No activity logged" in result.output, _debug(result)

    def test_day_custom_date(self, tmp_path, monkeypatch):
        """--date flag works and filters by the given date."""
        result = _invoke(tmp_path, monkeypatch, "day", "--date", "2020-01-01")
        assert result.exit_code == 0, _debug(result)
        assert "No activity logged for 2020-01-01" in result.output, _debug(result)

    def test_day_invalid_date(self, tmp_path, monkeypatch):
        """Invalid --date exits non-zero."""
        result = _invoke(tmp_path, monkeypatch, "day", "--date", "not-a-date")
        assert result.exit_code != 0, _debug(result)

    def test_day_routes_count_in_header(self, tmp_path, monkeypatch):
        """ROUTES TODAY (N) header shows correct count."""
        ledger = _ledger(tmp_path)
        for i in range(3):
            decision = RouteDecision(
                task=f"task {i}",
                recommended_tool="ollama",
                score=5,
                reasoning="test",
                tier="worker",
            )
            ledger.insert_route_decision(decision)

        result = _invoke(tmp_path, monkeypatch, "day")
        assert "ROUTES TODAY (3)" in result.output, _debug(result)
