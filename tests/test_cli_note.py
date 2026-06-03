"""Tests for the `opencobalt note` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.memory_bridge import MemoryBridge

runner = CliRunner()


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


def _bridge(tmp_path: Path) -> MemoryBridge:
    return MemoryBridge(db_path=tmp_path / ".opencobalt" / "memories.db")


class TestNoteCommand:
    def test_note_stores_in_bridge(self, tmp_path, monkeypatch):
        """Note content is stored and retrievable via bridge.recent()."""
        result = _invoke(tmp_path, monkeypatch, "note", "hello world note")
        assert result.exit_code == 0, _debug(result)

        bridge = _bridge(tmp_path)
        recent = bridge.recent(limit=10)
        contents = [r["content"] for r in recent]
        assert "hello world note" in contents

    def test_note_with_tags(self, tmp_path, monkeypatch):
        """Tags are stored in metadata under the 'tags' key."""
        result = _invoke(tmp_path, monkeypatch, "note", "tagged note", "--tags", "alpha,beta")
        assert result.exit_code == 0, _debug(result)

        bridge = _bridge(tmp_path)
        recent = bridge.recent(limit=10)
        assert recent, "no entries in bridge after note"
        meta = json.loads(recent[0]["metadata"])
        assert "alpha" in meta.get("tags", [])
        assert "beta" in meta.get("tags", [])

    def test_note_with_agent(self, tmp_path, monkeypatch):
        """--agent sets the agent_id on the stored record."""
        result = _invoke(tmp_path, monkeypatch, "note", "agent note", "--agent", "my-agent")
        assert result.exit_code == 0, _debug(result)

        bridge = _bridge(tmp_path)
        recent = bridge.recent(limit=10)
        assert recent, "no entries in bridge after note"
        assert recent[0]["agent_id"] == "my-agent"

    def test_note_default_agent_is_user(self, tmp_path, monkeypatch):
        """Default agent_id is 'user' when --agent is not specified."""
        _invoke(tmp_path, monkeypatch, "note", "default agent note")
        bridge = _bridge(tmp_path)
        recent = bridge.recent(limit=10)
        assert recent
        assert recent[0]["agent_id"] == "user"

    def test_note_metadata_type_is_note(self, tmp_path, monkeypatch):
        """Metadata type field is set to 'note'."""
        _invoke(tmp_path, monkeypatch, "note", "type check")
        bridge = _bridge(tmp_path)
        recent = bridge.recent(limit=10)
        meta = json.loads(recent[0]["metadata"])
        assert meta.get("type") == "note"

    def test_note_prints_confirmation(self, tmp_path, monkeypatch):
        """Command prints the 'Noted.' confirmation line."""
        result = _invoke(tmp_path, monkeypatch, "note", "confirm me")
        assert "Noted." in result.output, _debug(result)

    def test_note_prints_content_snippet(self, tmp_path, monkeypatch):
        """Command echoes the content in the output."""
        result = _invoke(tmp_path, monkeypatch, "note", "unique-content-xyz")
        assert "unique-content-xyz" in result.output, _debug(result)
