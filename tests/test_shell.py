"""Tests for CobaltShell dispatch logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from opencobalt.shell import CobaltShell


@pytest.fixture()
def shell(tmp_path: Path) -> CobaltShell:
    return CobaltShell(
        db_path=tmp_path / ".opencobalt" / "ledger.db",
        bridge_path=tmp_path / ".opencobalt" / "memories.db",
    )


def test_dispatch_slash_status(shell: CobaltShell, capsys) -> None:
    with patch.object(shell, "_run_command") as mock_cmd:
        shell.dispatch("/status")
    mock_cmd.assert_called_once_with("status", [])


def test_dispatch_slash_with_args(shell: CobaltShell) -> None:
    with patch.object(shell, "_run_command") as mock_cmd:
        shell.dispatch("/route design the auth module")
    mock_cmd.assert_called_once_with("route", ["design the auth module"])


def test_dispatch_plain_prompt_calls_router(shell: CobaltShell) -> None:
    with (
        patch.object(shell._learning_router, "route") as mock_route,
        patch.object(shell, "_open_tool") as mock_open,
        patch.object(shell, "_queue_background_council"),
    ):
        mock_route.return_value = MagicMock(
            recommended_tool="claude-code",
            score=86,
            tier="executive",
            reasoning="test",
            task="design auth",
            id="test-id",
            scores={"claude-code": 86},
        )
        shell.dispatch("design the auth module")
    mock_route.assert_called_once_with("design the auth module")
    mock_open.assert_called_once()


def test_dispatch_slash_palette(shell: CobaltShell, capsys) -> None:
    shell.dispatch("/")
    captured = capsys.readouterr()
    assert "/route" in captured.out or "route" in captured.out


def test_render_status_returns_string(shell: CobaltShell) -> None:
    status = shell.render_status()
    assert isinstance(status, str)
    assert len(status) > 0


def test_slash_commands_list(shell: CobaltShell) -> None:
    commands = shell.list_slash_commands()
    assert "route" in commands
    assert "brief" in commands
    assert "verify" in commands
