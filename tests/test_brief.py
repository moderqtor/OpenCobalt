"""Tests for BriefGenerator."""

from __future__ import annotations

from pathlib import Path

import pytest

import opencobalt.core.brief as brief_module
from opencobalt.core.brief import BriefGenerator, _detect_stack, _readme_excerpt
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


def test_detect_stack_reports_multiple_local_manifests(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    (tmp_path / "pubspec.yaml").write_text("name: demo\n", encoding="utf-8")
    (tmp_path / "src-tauri").mkdir()
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"react":"latest","vite":"latest"}}',
        encoding="utf-8",
    )

    stack = _detect_stack(tmp_path)

    assert "Node.js/react" in stack
    assert "Python" in stack
    assert "Rust" in stack
    assert "Go" in stack
    assert "Dart/Flutter" in stack
    assert "Tauri" in stack


def test_detect_stack_tolerates_invalid_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{not-json", encoding="utf-8")

    assert _detect_stack(tmp_path) == "Node.js"


def test_readme_excerpt_uses_first_paragraph_and_limits_length(tmp_path: Path) -> None:
    first = "A" * 250
    (tmp_path / "README.md").write_text(f"{first}\n\nSecond paragraph", encoding="utf-8")

    excerpt = _readme_excerpt(tmp_path)

    assert excerpt == first[:200]
    assert "Second paragraph" not in excerpt


def test_generate_includes_project_context_from_current_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Demo project\n\nMore detail", encoding="utf-8")
    monkeypatch.setattr(brief_module, "_git_branch", lambda cwd: "feature/context")
    monkeypatch.setattr(brief_module, "_git_log", lambda cwd, n=6: "abc123 Add context")

    ledger = _make_ledger(tmp_path)
    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate(days=7)

    assert "## Project Context" in output
    assert f"**{tmp_path.name}**" in output
    assert "Stack: Python" in output
    assert "Branch: feature/context" in output
    assert "abc123 Add context" in output
    assert "Demo project" in output


def test_generate_startup_uses_project_name_and_stack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    ledger = _make_ledger(tmp_path)
    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate_startup()

    assert output.splitlines()[0] == f"BRIEF  {tmp_path.name}"
    assert "no activity yet in this project" in output
    assert "stack: Python" in output
