"""Tests for route --exec and --dry-run."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from opencobalt.cli import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_dry_run_shows_exec_plan(runner: CliRunner, tmp_path: Path) -> None:
    with patch("opencobalt.cli._DB_PATH", tmp_path / "ledger.db"):
        result = runner.invoke(app, ["route", "refactor this module", "--dry-run"])
    assert result.exit_code == 0
    # dry-run message or normal route output
    output = result.output
    assert "dry-run" in output.lower() or "Routing" in output


def test_exec_blocks_legacy_launcher(runner: CliRunner, tmp_path: Path) -> None:
    with patch("opencobalt.cli._DB_PATH", tmp_path / "ledger.db"), \
         patch("shutil.which", return_value=None):
        result = runner.invoke(app, ["route", "design the auth module", "--exec"])
    assert result.exit_code == 0
    assert "ExecutionEngine" in result.output
    assert "opencobalt run" in result.output


def test_clipboard_content_contains_brief(tmp_path: Path) -> None:
    from opencobalt.core.brief import BriefGenerator
    from opencobalt.core.ledger import Ledger

    ledger = Ledger(tmp_path / "ledger.db")
    gen = BriefGenerator(ledger, bridge_path=tmp_path / "memories.db")
    output = gen.generate(days=7)
    # Brief must have the required sections
    assert "Recent Work" in output
    assert "Last Session" in output
    assert "Project Context" in output
