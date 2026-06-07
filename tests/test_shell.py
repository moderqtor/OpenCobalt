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


def test_dispatch_plain_prompt_calls_overlay(shell: CobaltShell) -> None:
    with patch.object(shell, "_overlay") as mock_overlay:
        shell.dispatch("design the auth module")
    mock_overlay.handle_prompt.assert_called_once_with("design the auth module")


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
    assert "telemetry" in commands
    assert "mission" in commands
    assert "limits" in commands
    assert "policy" in commands


def test_on_exit_does_not_raise(shell: CobaltShell) -> None:
    shell.on_exit()


def test_refine_prompt_passthrough_when_no_ollama(shell: CobaltShell) -> None:
    with patch("shutil.which", return_value=None):
        result = shell._refine_prompt("design the auth module")
    assert result == "design the auth module"


def test_refine_prompt_uses_refined_when_ollama_present(shell: CobaltShell) -> None:
    mock_result = MagicMock()
    mock_result.stdout = "Design a secure authentication module with JWT tokens"
    with (
        patch("shutil.which", return_value="/usr/bin/ollama"),
        patch("subprocess.run", return_value=mock_result),
    ):
        result = shell._refine_prompt("design the auth module")
    assert result == "Design a secure authentication module with JWT tokens"


def test_refine_prompt_falls_back_on_subprocess_error(shell: CobaltShell) -> None:
    with (
        patch("shutil.which", return_value="/usr/bin/ollama"),
        patch("subprocess.run", side_effect=Exception("timeout")),
    ):
        result = shell._refine_prompt("design the auth module")
    assert result == "design the auth module"


def test_ensure_session_branch_skips_when_no_git(shell: CobaltShell) -> None:
    with patch("shutil.which", return_value=None):
        shell._ensure_session_branch()


def test_ensure_session_branch_skips_on_dirty_tree(shell: CobaltShell) -> None:
    dirty_result = MagicMock()
    dirty_result.stdout = "M  some/file.py"
    with (
        patch("shutil.which", return_value="/usr/bin/git"),
        patch("subprocess.run", return_value=dirty_result),
    ):
        shell._ensure_session_branch()


def test_orch_in_slash_commands(shell: CobaltShell) -> None:
    assert "orch" in shell.list_slash_commands()


def test_dispatch_orch_calls_run_orch(shell: CobaltShell) -> None:
    called_with: dict = {}

    def fake_run_orch(expr: str) -> None:
        called_with["expr"] = expr

    shell._run_orch = fake_run_orch  # type: ignore[method-assign]
    shell.dispatch("/orch implement auth with tests")
    assert called_with.get("expr") == "implement auth with tests"


def test_converge_in_slash_commands(tmp_path):
    from opencobalt.shell import CobaltShell
    shell = CobaltShell(
        db_path=tmp_path / "ledger.db",
        bridge_path=tmp_path / "memories.db",
    )
    commands = shell.list_slash_commands()
    assert "converge" in commands


def test_dispatch_converge_empty_prints_usage(tmp_path, capsys):
    from opencobalt.shell import CobaltShell
    shell = CobaltShell(
        db_path=tmp_path / "ledger.db",
        bridge_path=tmp_path / "memories.db",
    )
    shell.dispatch("/converge")
    # Just verify it doesn't raise


def test_plain_prompt_routes_through_overlay(shell: CobaltShell) -> None:
    with patch.object(shell, "_overlay") as mock_overlay:
        shell.dispatch("build auth with tests and docs")

    mock_overlay.handle_prompt.assert_called_once_with("build auth with tests and docs")


def test_dispatch_mission_calls_run_mission(shell: CobaltShell) -> None:
    called_with: dict = {}

    def fake_run_mission(expr: str) -> None:
        called_with["expr"] = expr

    shell._run_mission = fake_run_mission  # type: ignore[method-assign]
    shell.dispatch("/mission --hours 5 make me money")
    assert called_with.get("expr") == "--hours 5 make me money"


def test_dispatch_policy_calls_cli(shell: CobaltShell) -> None:
    with patch("subprocess.run") as mock_run:
        shell.dispatch("/policy show")

    mock_run.assert_called_once_with(["opencobalt", "policy", "show"])


def test_dispatch_council_mode_calls_typed_cli(shell: CobaltShell) -> None:
    with patch("subprocess.run") as mock_run:
        shell.dispatch("/council coordinate handoff to tests")

    mock_run.assert_called_once_with(
        ["opencobalt", "council", "--mode", "coordinate", "handoff to tests"]
    )
