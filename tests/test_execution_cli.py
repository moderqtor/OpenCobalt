"""CLI tests for opencobalt run / receipts / artifacts.

Follows the isolation strategy from test_cli.py: every test chdirs into
tmp_path so ledger and artifact files land in a throwaway directory.
No live agent runtimes are invoked; execution paths use the noop adapter
or a mocked subprocess.
"""

from __future__ import annotations

import re
import subprocess

from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.execution import ExecutionStore, WorkReceipt

runner = CliRunner()


def _invoke(*args: str, **kwargs) -> object:
    env = {**kwargs.pop("env", {}), "NO_COLOR": "1"}
    kwargs.setdefault("color", False)
    return runner.invoke(app, list(args), env=env, **kwargs)


def _receipt_id(output: str) -> str:
    match = re.search(r"Receipt:\s+([0-9a-f-]{36})", output)
    assert match, f"no receipt id in output: {output}"
    return match.group(1)


def _cursor_agent_help() -> str:
    return """
Usage: cursor agent [options] [prompt...]

Options:
  -p, --print                  Print responses to console (for scripts or non-interactive use).
  --output-format <format>     Output format (only works with --print): text | json | stream-json
  --mode <mode>                Start in the given execution mode. plan: read-only/planning.
  --model <model>              Model to use.
  --sandbox <mode>             Explicitly enable or disable sandbox mode.
  --cloud                      Start in cloud mode.
  --api-key <key>              API key for authentication (can also use CURSOR_API_KEY env var)
"""


def _claude_help() -> str:
    return """
Usage: claude [options] [command] [prompt]

Claude Code - starts an interactive session by default, use -p/--print for
non-interactive output

Options:
  --allow-dangerously-skip-permissions  Enable bypassing all permission checks as an option.
  --dangerously-skip-permissions        Bypass all permission checks.
  --mcp-config <configs...>             Load MCP servers from JSON files or strings.
  --strict-mcp-config                   Only use MCP servers from --mcp-config.
  --no-chrome                           Disable Claude in Chrome integration
  --no-session-persistence              Disable session persistence.
  --output-format <format>              Output format (only works with --print): text, json, stream-json
  --permission-mode <mode>              Permission mode choices: acceptEdits, auto, bypassPermissions, default, dontAsk, plan
  -p, --print                           Print response and exit.
  --safe-mode                           Start with customizations disabled.
"""


def _codex_help() -> str:
    return """
Codex CLI

Usage: codex [OPTIONS] [PROMPT]
       codex [OPTIONS] <COMMAND> [ARGS]

Commands:
  exec            Run Codex non-interactively [aliases: e]
  review          Run a code review non-interactively
  login           Manage login
  logout          Remove stored authentication credentials
  mcp             Manage external MCP servers for Codex
  app-server      [experimental] Run the app server or related tooling
  remote-control  [experimental] Manage the app-server daemon with remote control enabled
  apply           Apply the latest diff produced by Codex agent
  cloud           [EXPERIMENTAL] Browse tasks from Codex Cloud and apply changes locally

Options:
  -s, --sandbox <SANDBOX_MODE>          [possible values: read-only, workspace-write, danger-full-access]
      --dangerously-bypass-approvals-and-sandbox
      --dangerously-bypass-hook-trust
  -a, --ask-for-approval <APPROVAL_POLICY>
          Possible values: untrusted, on-failure, on-request, never
      --search
"""


def _codex_exec_help() -> str:
    return """
Run Codex non-interactively

Usage: codex exec [OPTIONS] [PROMPT]

Options:
  -s, --sandbox <SANDBOX_MODE>          [possible values: read-only, workspace-write, danger-full-access]
      --dangerously-bypass-approvals-and-sandbox
      --dangerously-bypass-hook-trust
      --ephemeral
      --ignore-user-config
      --color <COLOR>                  [possible values: always, never, auto]
      --json                           Print events to stdout as JSONL
"""


class TestRunCommand:
    def test_dry_run_produces_plan_without_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        def explode(*args, **kwargs):
            raise AssertionError("dry-run must not start a subprocess")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        result = _invoke("run", "hello", "--runtime", "noop")
        assert result.exit_code == 0
        assert "dry-run" in result.output
        assert "Receipt:" in result.output

    def test_dry_run_with_antigravity_runtime_mocked(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.execution.adapters import AntigravityAdapter

        caps = {
            "non_interactive_print": {"supported": True, "source": "runtime_discovered"},
        }
        monkeypatch.setattr(
            AntigravityAdapter, "capabilities", lambda self: caps
        )
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: "/usr/local/bin/agy" if command == "agy" else None,
        )
        result = _invoke("run", "hello", "--runtime", "google-antigravity", "--dry-run")
        assert result.exit_code == 0
        assert "agy --print hello" in result.output
        assert "--dangerously-skip-permissions" not in result.output

    def test_execute_runs_with_mocked_process(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        def fake_run(argv, **kwargs):
            kwargs["stdout"].write("mocked output")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        result = _invoke("run", "hello", "--runtime", "noop", "--execute")
        assert result.exit_code == 0
        assert "succeeded" in result.output
        assert "mocked output" in result.output
        assert "verified" in result.output

    def test_red_task_blocked_without_yes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("run", "rotate the api key", "--runtime", "noop", "--execute")
        assert result.exit_code == 2
        assert "Blocked" in result.output

    def test_red_task_executes_with_yes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        def fake_run(argv, **kwargs):
            kwargs["stdout"].write("done")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        result = _invoke(
            "run", "rotate the api key", "--runtime", "noop", "--execute", "--yes"
        )
        assert result.exit_code == 0
        assert "succeeded" in result.output

    def test_cli_redacts_sensitive_task_command_and_output(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        def fake_run(argv, **kwargs):
            kwargs["stdout"].write("OPENAI_API_KEY=sk-testsecret123456789\n")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        result = _invoke(
            "run",
            "rotate api key sk-testsecret123456789",
            "--runtime",
            "noop",
            "--execute",
            "--yes",
        )
        assert result.exit_code == 0
        assert "sk-testsecret123456789" not in result.output
        assert "<redacted>" in result.output

    def test_unknown_runtime_exits_nonzero(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("run", "hello", "--runtime", "skynet")
        assert result.exit_code == 1
        assert "unknown runtime" in result.output


class TestReceiptsCommands:
    def test_list_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("receipts", "list")
        assert result.exit_code == 0
        assert "No receipts" in result.output

    def test_list_after_dry_run(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _invoke("run", "hello", "--runtime", "noop")
        result = _invoke("receipts", "list")
        assert result.exit_code == 0
        assert "noop" in result.output
        assert "unverified" in result.output

    def test_inspect_shows_command_plan(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run_result = _invoke("run", "hello", "--runtime", "noop")
        receipt_id = _receipt_id(run_result.output)
        result = _invoke("receipts", "inspect", receipt_id)
        assert result.exit_code == 0
        assert "echo hello" in result.output
        assert "noop" in result.output

    def test_inspect_shows_normalized_adapter_fields(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run_result = _invoke("run", "hello", "--runtime", "noop", "--execute")
        receipt_id = _receipt_id(run_result.output)
        result = _invoke("receipts", "inspect", receipt_id)
        assert result.exit_code == 0
        assert "Adapter id:" in result.output
        assert "Capability snapshot:" in result.output
        assert "Invocation hash:" in result.output
        assert "Verifiability:" in result.output
        assert "Artifact hashes:" in result.output

    def test_inspect_redacts_secret_task_and_command(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        secret = "sk-testsecret123456789"
        run_result = _invoke(
            "run",
            f"rotate api key {secret}",
            "--runtime",
            "noop",
            "--execute",
            "--yes",
        )
        receipt_id = _receipt_id(run_result.output)
        result = _invoke("receipts", "inspect", receipt_id)
        assert result.exit_code == 0
        assert secret not in result.output
        assert "<redacted>" in result.output

    def test_inspect_handles_legacy_flat_capability_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        store = ExecutionStore(tmp_path / ".opencobalt" / "ledger.db")
        receipt = WorkReceipt(
            plan_id="legacy-plan",
            task="legacy",
            selected_runtime="noop",
            capabilities_snapshot={"echo_only": {"supported": True, "source": "static"}},
            command_plan=["echo", "legacy"],
        )
        store.save_receipt(receipt)
        result = _invoke("receipts", "inspect", receipt.receipt_id)
        assert result.exit_code == 0, result.output
        assert "Adapter id:" in result.output
        assert "legacy-compatible" in result.output

    def test_inspect_unknown_receipt_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("receipts", "inspect", "ffffffff-0000-0000-0000-000000000000")
        assert result.exit_code == 1

    def test_verify_executed_receipt(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run_result = _invoke("run", "hello", "--runtime", "noop", "--execute")
        receipt_id = _receipt_id(run_result.output)
        result = _invoke("receipts", "verify", receipt_id)
        assert result.exit_code == 0
        assert "verified" in result.output


class TestAdapterCommands:
    def test_adapters_list_shows_normalized_runtime_contract(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("adapters", "list")
        assert result.exit_code == 0, result.output
        assert "claude-code" in result.output
        assert "codex-cli" in result.output
        assert "cursor" in result.output
        assert "noop" in result.output
        assert "google-antigravity" in result.output
        assert "Verifiability" in result.output

    def test_adapters_inspect_shows_capability_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("adapters", "inspect", "noop")
        assert result.exit_code == 0, result.output
        assert "Adapter" in result.output
        assert "snapshot hash" in result.output
        assert "echo_only" in result.output

    def test_adapters_inspect_cursor_shows_capability_limits(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        fake_cursor = tmp_path / "cursor"
        fake_cursor.write_text("#!/bin/sh\nexit 0\n")
        fake_cursor.chmod(0o755)

        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_cursor) if command == "cursor" else None,
        )
        monkeypatch.setattr(
            "opencobalt.execution.adapters.subprocess.run",
            lambda *args, **kwargs: subprocess.CompletedProcess(
                args[0], 0, stdout=_cursor_agent_help(), stderr=""
            ),
        )

        result = _invoke("adapters", "inspect", "cursor")

        assert result.exit_code == 0, result.output
        assert "Adapter cursor" in result.output
        assert str(fake_cursor) in result.output.replace("\n", "")
        assert "Available: yes" in result.output
        assert "Requires network: yes" in result.output
        assert "Requires credentials: yes" in result.output
        assert "Artifact support:" in result.output
        assert "stdout, stderr" in result.output
        assert "non_interactive_print" in result.output
        assert "read_only_plan_mode" in result.output
        assert "cloud mode is not enabled" in result.output

    def test_adapters_inspect_claude_shows_partial_runtime_limits(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        fake_claude = tmp_path / "claude"
        fake_claude.write_text("#!/bin/sh\nexit 0\n")
        fake_claude.chmod(0o755)

        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_claude) if command == "claude" else None,
        )
        monkeypatch.setattr(
            "opencobalt.execution.adapters.subprocess.run",
            lambda args, **kwargs: subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    "2.1.176 (Claude Code)"
                    if "--version" in args
                    else _claude_help()
                ),
                stderr="",
            ),
        )

        result = _invoke("adapters", "inspect", "claude-code")

        assert result.exit_code == 0, result.output
        assert "Adapter claude-code" in result.output
        assert str(fake_claude) in result.output.replace("\n", "")
        assert "Available: yes" in result.output
        assert "Capability level: partial" in result.output
        assert "Requires network: yes" in result.output
        assert "Requires credentials: yes" in result.output
        assert "Artifact support:" in result.output
        assert "stdout, stderr" in result.output
        assert "non_interactive_print" in result.output
        assert "plan_permission_mode" in result.output
        assert "dangerous permission bypass modes are not used" in result.output

    def test_adapters_inspect_codex_shows_partial_runtime_limits(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        fake_codex = tmp_path / "codex"
        fake_codex.write_text("#!/bin/sh\nexit 0\n")
        fake_codex.chmod(0o755)

        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_codex) if command == "codex" else None,
        )

        def fake_help(args, **kwargs):
            if "--version" in args:
                stdout = "codex-cli 0.139.0"
            elif "exec" in args and "--help" in args:
                stdout = _codex_exec_help()
            else:
                stdout = _codex_help()
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

        monkeypatch.setattr("opencobalt.execution.adapters.subprocess.run", fake_help)

        result = _invoke("adapters", "inspect", "codex-cli")

        assert result.exit_code == 0, result.output
        assert "Adapter codex-cli" in result.output
        assert str(fake_codex) in result.output.replace("\n", "")
        assert "Available: yes" in result.output
        assert "Capability level: partial" in result.output
        assert "Requires network: yes" in result.output
        assert "Requires credentials: yes" in result.output
        assert "Artifact support:" in result.output
        assert "stdout, stderr" in result.output
        assert "exec_subcommand" in result.output
        assert "read_only_sandbox" in result.output
        assert "approval_never" in result.output
        assert "json_events" in result.output
        assert "dangerous permission bypass modes are not used" in result.output

    def test_integrations_check_claude_does_not_overclaim_runtime_support(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "opencobalt.integrations.claude_code_integration.shutil.which",
            lambda command: "/usr/local/bin/claude" if command == "claude" else None,
        )

        result = _invoke("integrations", "check")

        assert result.exit_code == 0, result.output
        assert "claude-code" in result.output
        flat_output = re.sub(r"\s+", " ", result.output)
        assert "runtime evidence: opencobalt adapters inspect claude-code" in flat_output
        assert "receipt-backed execution ready" not in result.output

    def test_integrations_check_codex_does_not_overclaim_runtime_support(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "opencobalt.integrations.codex_cli_integration.shutil.which",
            lambda command: "/usr/local/bin/codex" if command == "codex" else None,
        )

        result = _invoke("integrations", "check")

        assert result.exit_code == 0, result.output
        assert "codex-cli" in result.output
        flat_output = re.sub(r"\s+", " ", result.output)
        assert "runtime evidence: opencobalt adapters inspect codex-cli" in flat_output
        assert "receipt-backed execution ready" not in result.output

    def test_run_help_lists_receipt_backed_runtimes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = _invoke("run", "--help")

        assert result.exit_code == 0, result.output
        assert "claude-code" in result.output
        assert "codex-cli" in result.output


class TestArtifactsCommands:
    def test_attach_and_verify(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        report = tmp_path / "report.md"
        report.write_text("# Findings\n")
        attach = _invoke(
            "artifacts", "attach", str(report), "--type", "report", "--source", "manual"
        )
        assert attach.exit_code == 0
        match = re.search(r"Artifact attached:\s+([0-9a-f-]{36})", attach.output)
        assert match
        artifact_id = match.group(1)

        verify_ok = _invoke("artifacts", "verify", artifact_id)
        assert verify_ok.exit_code == 0
        assert "verified" in verify_ok.output

        report.write_text("# Tampered\n")
        verify_bad = _invoke("artifacts", "verify", artifact_id)
        assert verify_bad.exit_code == 1
        assert "failed" in verify_bad.output

    def test_attach_missing_file_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("artifacts", "attach", str(tmp_path / "nope.txt"))
        assert result.exit_code == 1

    def test_verify_unknown_artifact_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("artifacts", "verify", "ffffffff-0000-0000-0000-000000000000")
        assert result.exit_code == 1

    def test_list_filters_by_type(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        f1 = tmp_path / "a.diff"
        f1.write_text("diff content")
        f2 = tmp_path / "b.log"
        f2.write_text("log content")
        _invoke("artifacts", "attach", str(f1), "--type", "diff")
        _invoke("artifacts", "attach", str(f2), "--type", "log")
        result = _invoke("artifacts", "list", "--type", "diff")
        assert result.exit_code == 0
        assert "1 artifact(s)" in result.output
        assert "diff" in result.output
