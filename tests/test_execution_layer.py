"""Tests for Receipt-Backed Execution v0: policy, runner, adapters, engine.

No live agy/claude/codex/network calls. Subprocess use is limited to
/bin/echo (noop adapter) and mocked runs.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from opencobalt.execution import (
    AntigravityAdapter,
    ClaudeCodeAdapter,
    CodexCliAdapter,
    CommandOptions,
    CursorAdapter,
    ExecutionEngine,
    ExecutionStore,
    NoopAdapter,
    OllamaAdapter,
    ProcessRunner,
    attach_artifact,
    available_runtimes,
    check_execution,
    classify_risk,
    get_adapter,
    hash_file,
    max_risk,
    verify_artifact,
)
from opencobalt.execution.models import NormalizedInvocation, RuntimeCapabilitySnapshot


def _engine(tmp_path: Path) -> ExecutionEngine:
    return ExecutionEngine(
        store=ExecutionStore(tmp_path / "ledger.db"),
        runner=ProcessRunner(artifact_dir=tmp_path / "artifacts"),
        events_path=tmp_path / "events.jsonl",
    )


def _agy_caps(**overrides) -> dict:
    caps = {
        "non_interactive_print": {"supported": True, "source": "runtime_discovered"},
        "non_interactive_mode": {"supported": True, "source": "runtime_discovered"},
        "model_selection": {"supported": True, "source": "runtime_discovered"},
        "sandbox_mode": {"supported": True, "source": "runtime_discovered"},
        "unsafe_skip_permissions": {"supported": True, "source": "runtime_discovered"},
    }
    caps.update(overrides)
    return caps


def _cursor_agent_help() -> str:
    return """
Usage: cursor agent [options] [prompt...]

Options:
  -p, --print                  Print responses to console (for scripts or non-interactive use).
  --output-format <format>     Output format (only works with --print): text | json | stream-json
  --mode <mode>                Start in the given execution mode. plan: read-only/planning
                               (analyze, propose plans, no edits). ask: Q&A style.
  --plan                       Start in plan mode (shorthand for --mode=plan).
  --model <model>              Model to use.
  --sandbox <mode>             Explicitly enable or disable sandbox mode.
  --cloud                      Start in cloud mode.
  --api-key <key>              API key for authentication (can also use CURSOR_API_KEY env var)
"""


def _fake_cursor_app(tmp_path: Path) -> tuple[Path, Path]:
    app = tmp_path / "Cursor.app"
    binary = app / "Contents" / "Resources" / "app" / "bin" / "cursor"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return app, binary


def _claude_help() -> str:
    return """
Usage: claude [options] [command] [prompt]

Claude Code - starts an interactive session by default, use -p/--print for
non-interactive output

Options:
  --allow-dangerously-skip-permissions  Enable bypassing all permission checks as an option
  --dangerously-skip-permissions        Bypass all permission checks.
  --allowedTools, --allowed-tools <tools...>
      Comma or space-separated list of tool names to allow.
  --disallowedTools, --disallowed-tools <tools...>
      Comma or space-separated list of tool names to deny.
  --mcp-config <configs...>             Load MCP servers from JSON files or strings.
  --strict-mcp-config                   Only use MCP servers from --mcp-config.
  --max-budget-usd <amount>             Maximum dollar amount to spend on API calls.
  --no-chrome                           Disable Claude in Chrome integration
  --no-session-persistence              Disable session persistence.
  --output-format <format>              Output format (only works with --print): text, json, stream-json
  --permission-mode <mode>              Permission mode to use (choices: acceptEdits, auto, bypassPermissions, default, dontAsk, plan)
  -p, --print                           Print response and exit.
  --safe-mode                           Start with customizations disabled.
  --bare                                Minimal mode.
  --tools <tools...>                    Specify the list of available tools.
  -v, --version                         Output the version number

Commands:
  auth                                  Manage authentication
  doctor                                Check health
  mcp                                   Configure and manage MCP servers
"""


def _claude_help_without_plan_mode() -> str:
    return """
Usage: claude [options] [command] [prompt]
Options:
  -p, --print                           Print response and exit.
  --output-format <format>              Output format (only works with --print): text, json
  --dangerously-skip-permissions        Bypass all permission checks.
"""


def _fake_claude_binary(tmp_path: Path) -> Path:
    binary = tmp_path / "claude"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return binary


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
      --output-schema <FILE>
      --color <COLOR>                  [possible values: always, never, auto]
      --json                           Print events to stdout as JSONL
  -o, --output-last-message <FILE>
"""


def _codex_help_without_safe_exec() -> str:
    return """
Codex CLI

Usage: codex [OPTIONS] [PROMPT]
       codex [OPTIONS] <COMMAND> [ARGS]

Commands:
  exec            Run Codex non-interactively

Options:
  -s, --sandbox <SANDBOX_MODE>          [possible values: workspace-write, danger-full-access]
      --dangerously-bypass-approvals-and-sandbox
"""


def _fake_codex_binary(tmp_path: Path) -> Path:
    binary = tmp_path / "codex"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return binary


# ── Policy ────────────────────────────────────────────────────────────────────


class TestRiskClassification:
    def test_summarization_is_green(self):
        assert classify_risk("summarize docs/ANTIGRAVITY.md") == "green"

    def test_file_edit_is_yellow(self):
        assert classify_risk("edit the README file") == "yellow"

    @pytest.mark.parametrize(
        "task",
        [
            "read the .env values",
            "rotate the API key",
            "copy my ssh key",
            "print the deploy token",
            "automate browser login",
            "publish package to pypi",
            "update production config",
            "export browser profile cookies",
            "handle user credentials",
        ],
    )
    def test_credential_environment_tasks_are_red(self, task):
        assert classify_risk(task) == "red"

    @pytest.mark.parametrize(
        "task",
        ["rm -rf the build dir", "wipe the disk", "credential export to file", "delete everything"],
    )
    def test_destructive_tasks_are_black(self, task):
        assert classify_risk(task) == "black"

    def test_max_risk_picks_most_severe(self):
        assert max_risk("green", "red", "yellow") == "red"
        assert max_risk("green") == "green"
        assert max_risk("yellow", "black") == "black"


class TestPolicyGate:
    def test_dry_run_always_allowed(self):
        for level in ("green", "yellow", "red", "black"):
            decision = check_execution(level, dry_run=True, execute=False, approved=False)
            assert decision.allowed

    def test_green_executes_with_explicit_execute(self):
        assert check_execution("green", dry_run=False, execute=True, approved=False).allowed

    def test_yellow_requires_explicit_execute(self):
        assert not check_execution("yellow", dry_run=False, execute=False, approved=False).allowed
        assert check_execution("yellow", dry_run=False, execute=True, approved=False).allowed

    def test_red_requires_explicit_approval(self):
        denied = check_execution("red", dry_run=False, execute=True, approved=False)
        assert not denied.allowed
        assert denied.requires_approval
        assert check_execution("red", dry_run=False, execute=True, approved=True).allowed

    def test_black_blocked_even_with_approval(self):
        decision = check_execution("black", dry_run=False, execute=True, approved=True)
        assert not decision.allowed


# ── Process runner ────────────────────────────────────────────────────────────


class TestProcessRunner:
    def test_captures_stdout_and_succeeds(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        result = runner.run(["echo", "hello"], plan_id="p1", runtime="noop")
        assert result.status == "succeeded"
        assert result.return_code == 0
        assert "hello" in result.stdout_preview
        assert result.duration_ms is not None

    def test_writes_output_artifact_files(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        result = runner.run(["echo", "artifact content"], plan_id="p1", runtime="noop")
        assert result.stdout_path is not None
        assert "artifact content" in Path(result.stdout_path).read_text()

    def test_missing_executable_fails_cleanly(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        result = runner.run(
            ["definitely-not-a-real-binary-xyz"], plan_id="p1", runtime="noop"
        )
        assert result.status == "failed"
        assert "not found" in (result.error or "")

    def test_timeout_handled_cleanly(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        result = runner.run(
            ["sleep", "5"], plan_id="p1", runtime="noop", timeout_seconds=1
        )
        assert result.status == "timeout"
        assert "timed out" in (result.error or "")

    def test_cancel_check_stops_a_running_process(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        polls = {"n": 0}

        def cancel_check():
            polls["n"] += 1
            return polls["n"] > 2

        result = runner.run(
            ["sleep", "30"],
            plan_id="p1",
            runtime="noop",
            timeout_seconds=5,
            cancel_check=cancel_check,
        )
        assert result.status == "failed"
        assert result.error == "cancelled"

    def test_rejects_non_list_argv(self, tmp_path):
        runner = ProcessRunner(artifact_dir=tmp_path)
        with pytest.raises(ValueError):
            runner.run("echo hello", plan_id="p1")  # type: ignore[arg-type]

    def test_never_uses_shell(self, tmp_path, monkeypatch):
        recorded: dict = {}

        def fake_run(argv, **kwargs):
            recorded["argv"] = argv
            recorded["kwargs"] = kwargs
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        ProcessRunner(artifact_dir=tmp_path).run(["echo", "x"], plan_id="p1")
        assert isinstance(recorded["argv"], list)
        assert "shell" not in recorded["kwargs"]
        assert "env" not in recorded["kwargs"]  # no env dumping or overriding

    def test_captures_output_to_files_without_in_memory_capture(self, tmp_path, monkeypatch):
        recorded: dict = {}

        def fake_run(argv, **kwargs):
            recorded["kwargs"] = kwargs
            kwargs["stdout"].write("OPENAI_API_KEY=sk-testsecret123456789\nnormal output\n")
            kwargs["stderr"].write("stderr output\n")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        result = ProcessRunner(artifact_dir=tmp_path).run(["echo", "x"], plan_id="p1")
        assert "capture_output" not in recorded["kwargs"]
        assert recorded["kwargs"]["stdout"] is not subprocess.PIPE
        assert recorded["kwargs"]["stderr"] is not subprocess.PIPE
        assert result.stdout_path is not None
        assert "sk-testsecret123456789" not in result.stdout_preview
        assert "OPENAI_API_KEY=<redacted>" in result.stdout_preview
        assert "normal output" in Path(result.stdout_path).read_text(encoding="utf-8")

    def test_runner_source_has_no_shell_true(self):
        source = Path("src/opencobalt/execution/runner.py").read_text()
        assert "shell=True" not in source


# ── Adapters ──────────────────────────────────────────────────────────────────


class TestAdapters:
    def test_registry_knows_v0_runtimes(self):
        assert {
            "claude-code",
            "codex-cli",
            "cursor",
            "google-antigravity",
            "ollama",
            "noop",
        } <= set(available_runtimes())

    def test_unknown_runtime_fails_cleanly(self):
        with pytest.raises(KeyError, match="unknown runtime"):
            get_adapter("skynet")

    @pytest.mark.parametrize(
        ("adapter", "runtime_id", "path"),
        [
            (NoopAdapter(), "noop", "/bin/echo"),
            (OllamaAdapter(), "ollama", "/usr/local/bin/ollama"),
            (
                AntigravityAdapter(capabilities=_agy_caps()),
                "google-antigravity",
                "/usr/local/bin/agy",
            ),
        ],
    )
    def test_capability_snapshot_generated_for_runtime_adapters(
        self, adapter, runtime_id, path, monkeypatch
    ):
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: path if command == adapter.executable else None,
        )
        snapshot = adapter.discover_capabilities()
        assert snapshot.adapter_id == runtime_id
        assert snapshot.adapter_name == adapter.display_name
        assert snapshot.executable_path == path
        assert snapshot.available is True
        assert snapshot.supports_dry_run is True
        assert snapshot.supports_noninteractive is True
        assert snapshot.snapshot_hash
        assert snapshot.verifiability_level in ("full", "partial")

    def test_unavailable_adapter_snapshot_is_not_crashing(self, monkeypatch):
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)
        snapshot = OllamaAdapter().discover_capabilities()
        assert snapshot.adapter_id == "ollama"
        assert snapshot.available is False
        assert snapshot.executable_path is None
        assert snapshot.verifiability_level == "unavailable"
        assert snapshot.requires_credentials is True

    def test_cursor_absent_snapshot_is_unavailable(self, monkeypatch):
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)
        adapter = CursorAdapter(app_paths=())

        snapshot = adapter.discover_capabilities()

        assert snapshot.adapter_id == "cursor"
        assert snapshot.available is False
        assert snapshot.executable_path is None
        assert snapshot.supports_noninteractive is False
        assert snapshot.verifiability_level == "unavailable"
        assert "Cursor app or cursor executable not found" in snapshot.limitations

    def test_cursor_discovered_from_macos_app_path_is_partial(
        self, tmp_path, monkeypatch
    ):
        app, _binary = _fake_cursor_app(tmp_path)
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)

        adapter = CursorAdapter(app_paths=(app,), help_text=_cursor_agent_help())
        snapshot = adapter.discover_capabilities()

        assert snapshot.adapter_id == "cursor"
        assert snapshot.available is True
        assert snapshot.executable_path == str(app)
        assert snapshot.supports_noninteractive is True
        assert snapshot.requires_network is True
        assert snapshot.requires_credentials is True
        assert snapshot.verifiability_level == "partial"
        assert "macos_app" in snapshot.capabilities
        assert "non_interactive_print" in snapshot.capabilities
        assert "read_only_plan_mode" in snapshot.capabilities
        assert "cloud_mode" not in snapshot.capabilities
        assert "credential_auth" not in snapshot.capabilities
        assert snapshot.capability_details["cloud_mode"]["advertised_by_cursor"] is True
        assert snapshot.capability_details["cloud_mode"]["enabled_by_opencobalt"] is False
        assert snapshot.capability_details["credential_auth"]["advertised_by_cursor"] is True
        assert snapshot.capability_details["credential_auth"]["stored_by_opencobalt"] is False
        assert any("cloud mode is not enabled" in item for item in snapshot.limitations)

    def test_claude_absent_snapshot_is_unavailable(self, monkeypatch):
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)
        adapter = ClaudeCodeAdapter(help_text="", version_text="")

        snapshot = adapter.discover_capabilities()

        assert snapshot.adapter_id == "claude-code"
        assert snapshot.available is False
        assert snapshot.executable_path is None
        assert snapshot.supports_noninteractive is False
        assert snapshot.verifiability_level == "unavailable"
        assert "Claude executable not found: claude" in snapshot.limitations

    def test_claude_fake_help_snapshot_is_partial_and_bounded(
        self, tmp_path, monkeypatch
    ):
        fake_claude = _fake_claude_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_claude) if command == "claude" else None,
        )
        adapter = ClaudeCodeAdapter(
            help_text=_claude_help(),
            version_text="2.1.176 (Claude Code)",
        )

        snapshot = adapter.discover_capabilities()

        assert snapshot.adapter_id == "claude-code"
        assert snapshot.adapter_name == "Claude Code"
        assert snapshot.executable_path == str(fake_claude)
        assert snapshot.available is True
        assert snapshot.adapter_version == "2.1.176 (Claude Code)"
        assert snapshot.supports_noninteractive is True
        assert snapshot.requires_network is True
        assert snapshot.requires_credentials is True
        assert snapshot.verifiability_level == "partial"
        assert "path_binary" in snapshot.capabilities
        assert "non_interactive_print" in snapshot.capabilities
        assert "text_output" in snapshot.capabilities
        assert "plan_permission_mode" in snapshot.capabilities
        assert "safe_mode" in snapshot.capabilities
        assert "no_session_persistence" in snapshot.capabilities
        assert "dangerous_permission_bypass" not in snapshot.capabilities
        assert snapshot.capability_details["dangerous_permission_bypass"][
            "advertised_by_claude"
        ] is True
        assert snapshot.capability_details["dangerous_permission_bypass"][
            "enabled_by_opencobalt"
        ] is False
        assert snapshot.capability_details["credential_auth"]["stored_by_opencobalt"] is False
        assert any("dangerous permission bypass modes are not used" in item for item in snapshot.limitations)
        assert snapshot.snapshot_hash

    def test_claude_builds_safe_print_plan_command(self, tmp_path, monkeypatch):
        fake_claude = _fake_claude_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_claude) if command == "claude" else None,
        )
        adapter = ClaudeCodeAdapter(
            help_text=_claude_help(),
            version_text="2.1.176 (Claude Code)",
        )

        argv = adapter.build_command("review repository state")

        assert argv == [
            str(fake_claude),
            "--print",
            "--output-format",
            "text",
            "--permission-mode",
            "plan",
            "--no-session-persistence",
            "--safe-mode",
            "--no-chrome",
            "--strict-mcp-config",
            "--mcp-config",
            "{}",
            "OpenCobalt read-only planning request:\nreview repository state",
        ]
        joined = " ".join(argv)
        assert "--dangerously-skip-permissions" not in joined
        assert "--allow-dangerously-skip-permissions" not in joined
        assert "--allowedTools" not in joined
        assert "--disallowedTools" not in joined
        assert "--max-budget-usd" not in joined

    def test_claude_safe_flags_only_when_help_advertises_them(
        self, tmp_path, monkeypatch
    ):
        fake_claude = _fake_claude_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_claude) if command == "claude" else None,
        )
        adapter = ClaudeCodeAdapter(
            help_text="""
Usage: claude [options] [prompt]
Options:
  -p, --print                           Print response and exit.
  --output-format <format>              Output format: text
  --permission-mode <mode>              Permission mode choices: plan
""",
            version_text="2.1.176 (Claude Code)",
        )

        argv = adapter.build_command("summarize")

        assert argv == [
            str(fake_claude),
            "--print",
            "--output-format",
            "text",
            "--permission-mode",
            "plan",
            "OpenCobalt read-only planning request:\nsummarize",
        ]

    def test_claude_missing_plan_mode_is_discovery_only(self, tmp_path, monkeypatch):
        fake_claude = _fake_claude_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_claude) if command == "claude" else None,
        )
        adapter = ClaudeCodeAdapter(
            help_text=_claude_help_without_plan_mode(),
            version_text="2.1.176 (Claude Code)",
        )

        snapshot = adapter.discover_capabilities()

        assert snapshot.available is True
        assert snapshot.supports_noninteractive is False
        assert snapshot.verifiability_level == "partial"
        assert "safe Claude Code --print plan mode was not discovered" in snapshot.limitations
        with pytest.raises(ValueError, match="safe Claude Code --print plan mode"):
            adapter.build_command("summarize")

    def test_claude_rejects_dangerous_or_mutating_options(self, tmp_path, monkeypatch):
        fake_claude = _fake_claude_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_claude) if command == "claude" else None,
        )
        adapter = ClaudeCodeAdapter(
            help_text=_claude_help(),
            version_text="2.1.176 (Claude Code)",
        )

        with pytest.raises(ValueError, match="unsafe permission bypass"):
            adapter.build_command(
                "summarize",
                CommandOptions(dangerously_skip_permissions=True),
            )
        with pytest.raises(ValueError, match="sandbox mode"):
            adapter.build_command("summarize", CommandOptions(sandbox=True))

    def test_codex_absent_snapshot_is_unavailable(self, monkeypatch):
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)
        adapter = CodexCliAdapter(help_text="", exec_help_text="", version_text="")

        snapshot = adapter.discover_capabilities()

        assert snapshot.adapter_id == "codex-cli"
        assert snapshot.available is False
        assert snapshot.executable_path is None
        assert snapshot.supports_noninteractive is False
        assert snapshot.verifiability_level == "unavailable"
        assert "Codex executable not found: codex" in snapshot.limitations

    def test_codex_fake_help_snapshot_is_partial_and_bounded(
        self, tmp_path, monkeypatch
    ):
        fake_codex = _fake_codex_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_codex) if command == "codex" else None,
        )
        adapter = CodexCliAdapter(
            help_text=_codex_help(),
            exec_help_text=_codex_exec_help(),
            version_text="codex-cli 0.139.0",
        )

        snapshot = adapter.discover_capabilities()

        assert snapshot.adapter_id == "codex-cli"
        assert snapshot.adapter_name == "Codex CLI"
        assert snapshot.adapter_version == "codex-cli 0.139.0"
        assert snapshot.executable_path == str(fake_codex)
        assert snapshot.available is True
        assert snapshot.supports_noninteractive is True
        assert snapshot.supports_json_output is True
        assert snapshot.requires_network is True
        assert snapshot.requires_credentials is True
        assert snapshot.verifiability_level == "partial"
        assert "path_binary" in snapshot.capabilities
        assert "exec_subcommand" in snapshot.capabilities
        assert "read_only_sandbox" in snapshot.capabilities
        assert "approval_never" in snapshot.capabilities
        assert "json_events" in snapshot.capabilities
        assert "dangerous_permission_bypass" not in snapshot.capabilities
        assert snapshot.capability_details["dangerous_permission_bypass"][
            "advertised_by_codex"
        ] is True
        assert snapshot.capability_details["dangerous_permission_bypass"][
            "enabled_by_opencobalt"
        ] is False
        assert snapshot.capability_details["credential_auth"]["stored_by_opencobalt"] is False
        assert any("dangerous permission bypass modes are not used" in item for item in snapshot.limitations)
        assert snapshot.snapshot_hash

    def test_codex_builds_safe_exec_planning_command(self, tmp_path, monkeypatch):
        fake_codex = _fake_codex_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_codex) if command == "codex" else None,
        )
        adapter = CodexCliAdapter(
            help_text=_codex_help(),
            exec_help_text=_codex_exec_help(),
            version_text="codex-cli 0.139.0",
        )

        argv = adapter.build_command("review repository state")

        assert argv == [
            str(fake_codex),
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--color",
            "never",
            "OpenCobalt read-only planning request:\nreview repository state",
        ]
        joined = " ".join(argv)
        assert "--dangerously-bypass-approvals-and-sandbox" not in joined
        assert "--dangerously-bypass-hook-trust" not in joined
        assert "--search" not in joined
        assert "login" not in argv
        assert "logout" not in argv
        assert "mcp" not in argv
        assert "app-server" not in argv
        assert "remote-control" not in argv
        assert "apply" not in argv
        assert "cloud" not in argv

    def test_codex_safe_optional_flags_only_when_help_advertises_them(
        self, tmp_path, monkeypatch
    ):
        fake_codex = _fake_codex_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_codex) if command == "codex" else None,
        )
        adapter = CodexCliAdapter(
            help_text=_codex_help(),
            exec_help_text="""
Run Codex non-interactively
Usage: codex exec [OPTIONS] [PROMPT]
Options:
  --json                           Print events to stdout as JSONL
""",
            version_text="codex-cli 0.139.0",
        )

        argv = adapter.build_command("summarize")

        assert argv == [
            str(fake_codex),
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "exec",
            "--json",
            "OpenCobalt read-only planning request:\nsummarize",
        ]

    def test_codex_skips_repo_trust_check_only_when_exec_help_advertises_it(
        self, tmp_path, monkeypatch
    ):
        fake_codex = _fake_codex_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_codex) if command == "codex" else None,
        )
        adapter = CodexCliAdapter(
            help_text=_codex_help(),
            exec_help_text="""
Run Codex non-interactively
Usage: codex exec [OPTIONS] [PROMPT]
Options:
  --json
  --skip-git-repo-check
""",
        )

        argv = adapter.build_command("summarize")

        exec_index = argv.index("exec")
        assert argv[exec_index + 1 : exec_index + 3] == [
            "--json",
            "--skip-git-repo-check",
        ]
        assert "--dangerously-bypass-approvals-and-sandbox" not in argv

    def test_codex_missing_safe_flags_is_discovery_only(self, tmp_path, monkeypatch):
        fake_codex = _fake_codex_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_codex) if command == "codex" else None,
        )
        adapter = CodexCliAdapter(
            help_text=_codex_help_without_safe_exec(),
            exec_help_text="Run Codex non-interactively",
            version_text="codex-cli 0.139.0",
        )

        snapshot = adapter.discover_capabilities()

        assert snapshot.available is True
        assert snapshot.supports_noninteractive is False
        assert snapshot.verifiability_level == "partial"
        assert "safe codex exec read-only invocation was not discovered" in snapshot.limitations
        with pytest.raises(ValueError, match="safe codex exec read-only invocation"):
            adapter.build_command("summarize")

    def test_codex_rejects_dangerous_or_mutating_options(self, tmp_path, monkeypatch):
        fake_codex = _fake_codex_binary(tmp_path)
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_codex) if command == "codex" else None,
        )
        adapter = CodexCliAdapter(
            help_text=_codex_help(),
            exec_help_text=_codex_exec_help(),
            version_text="codex-cli 0.139.0",
        )

        with pytest.raises(ValueError, match="unsafe permission bypass"):
            adapter.build_command(
                "summarize",
                CommandOptions(dangerously_skip_permissions=True),
            )
        with pytest.raises(ValueError, match="unsafe permission bypass"):
            adapter.build_command(
                "summarize",
                CommandOptions(allow_dangerously_skip_permissions=True),
            )

    def test_cursor_builds_read_only_agent_print_command(self, tmp_path, monkeypatch):
        app, binary = _fake_cursor_app(tmp_path)
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)
        adapter = CursorAdapter(app_paths=(app,), help_text=_cursor_agent_help())

        argv = adapter.build_command(
            "review the current file", CommandOptions(model="gpt-5", sandbox=True)
        )

        assert argv == [
            str(binary),
            "agent",
            "--print",
            "--mode",
            "plan",
            "--output-format",
            "text",
            "--sandbox",
            "enabled",
            "--model",
            "gpt-5",
            "--",
            "review the current file",
        ]

    def test_legacy_runtime_aliases_resolve_to_canonical_antigravity_adapter(self):
        assert get_adapter("antigravity-cli").runtime_id == "google-antigravity"
        for alias in ("gemini-cli", "gemini_cli", "google-gemini-cli"):
            with pytest.warns(DeprecationWarning, match="Gemini CLI integration is legacy"):
                assert get_adapter(alias).runtime_id == "google-antigravity"

    def test_noop_adapter_builds_echo(self):
        assert NoopAdapter().build_command("hello") == ["echo", "hello"]

    def test_noop_adapter_normalizes_leading_echo(self):
        assert NoopAdapter().build_command("echo hello") == ["echo", "hello"]

    def test_ollama_adapter_builds_run_argv(self):
        argv = OllamaAdapter().build_command("hello", CommandOptions(model="qwen3"))
        assert argv == ["ollama", "run", "qwen3", "hello"]

    def test_antigravity_print_command(self):
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        assert adapter.build_command("hello") == ["agy", "--print", "hello"]

    def test_antigravity_model_command(self):
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        argv = adapter.build_command("hello", CommandOptions(model="gemini-3-pro"))
        assert argv == ["agy", "--model", "gemini-3-pro", "--print", "hello"]

    def test_antigravity_sandbox_command(self):
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        argv = adapter.build_command("hello", CommandOptions(sandbox=True))
        assert argv == ["agy", "--sandbox", "--print", "hello"]

    def test_antigravity_never_skips_permissions_by_default(self):
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        argv = adapter.build_command("hello", CommandOptions(dangerously_skip_permissions=True))
        assert "--dangerously-skip-permissions" not in argv

    def test_antigravity_unsafe_override_warns(self):
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        with pytest.warns(RuntimeWarning):
            argv = adapter.build_command(
                "hello",
                CommandOptions(
                    dangerously_skip_permissions=True,
                    allow_dangerously_skip_permissions=True,
                ),
            )
        assert "--dangerously-skip-permissions" in argv

    def test_antigravity_without_print_support_fails_cleanly(self):
        caps = _agy_caps(
            non_interactive_print={"supported": None, "source": "unknown"},
            non_interactive_mode={"supported": None, "source": "unknown"},
        )
        adapter = AntigravityAdapter(capabilities=caps)
        assert not adapter.supports_non_interactive()
        with pytest.raises(ValueError):
            adapter.build_command("hello")


class TestNormalizedModels:
    def test_invocation_hash_is_stable_for_equivalent_invocation(self):
        first = NormalizedInvocation(
            adapter_id="noop",
            command_argv=["echo", "hello"],
            cwd="/tmp/project",
            environment_policy="inherited_redacted",
            expected_artifacts=["stdout", "stderr"],
            risk_level="green",
            dry_run=True,
            timeout_seconds=10,
        ).with_hash()
        second = NormalizedInvocation(
            adapter_id="noop",
            command_argv=["echo", "hello"],
            cwd="/tmp/project",
            environment_policy="inherited_redacted",
            expected_artifacts=["stdout", "stderr"],
            risk_level="green",
            dry_run=True,
            timeout_seconds=10,
        ).with_hash()
        assert first.invocation_id != second.invocation_id
        assert first.invocation_hash == second.invocation_hash

    def test_capability_snapshot_hash_changes_when_capabilities_change(self):
        base = RuntimeCapabilitySnapshot(
            adapter_id="noop",
            adapter_name="Noop",
            available=True,
            capabilities=["echo_only"],
            supported_artifact_types=["stdout"],
            supports_dry_run=True,
            supports_noninteractive=True,
            supports_json_output=False,
            requires_network=False,
            requires_credentials=False,
            max_safe_risk="yellow",
        ).with_hash()
        changed = base.model_copy(update={"capabilities": ["echo_only", "json_output"]}).with_hash()
        assert base.snapshot_hash != changed.snapshot_hash


# ── Artifacts ─────────────────────────────────────────────────────────────────


class TestArtifacts:
    def test_attach_computes_sha256(self, tmp_path):
        f = tmp_path / "report.txt"
        f.write_text("hello receipts\n")
        artifact = attach_artifact(f, source_runtime="noop", artifact_type="report")
        expected = hashlib.sha256(b"hello receipts\n").hexdigest()
        assert artifact.sha256 == expected
        assert artifact.size_bytes == len(b"hello receipts\n")

    def test_hash_file_streams_large_file(self, tmp_path):
        f = tmp_path / "big.bin"
        payload = b"x" * (3 * 1024 * 1024)
        f.write_bytes(payload)
        assert hash_file(f) == hashlib.sha256(payload).hexdigest()

    def test_unknown_type_normalizes(self, tmp_path):
        f = tmp_path / "thing.txt"
        f.write_text("x")
        artifact = attach_artifact(f, source_runtime="noop", artifact_type="not-a-type")
        assert artifact.artifact_type == "unknown"

    def test_verify_passes_when_unchanged(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("stable")
        artifact = attach_artifact(f, source_runtime="noop")
        assert verify_artifact(artifact).verified

    def test_verify_fails_after_mutation(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("original")
        artifact = attach_artifact(f, source_runtime="noop")
        f.write_text("tampered")
        verification = verify_artifact(artifact)
        assert not verification.verified
        assert "mismatch" in verification.reason

    def test_verify_missing_file_fails_cleanly(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        artifact = attach_artifact(f, source_runtime="noop")
        f.unlink()
        verification = verify_artifact(artifact)
        assert not verification.verified
        assert verification.reason == "file missing"

    def test_attach_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            attach_artifact(tmp_path / "nope.txt", source_runtime="noop")


# ── Engine: plans, receipts, verification ─────────────────────────────────────


class TestExecutionEngine:
    def test_dry_run_creates_plan_and_receipt_without_subprocess(self, tmp_path, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("dry-run must not start a subprocess")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="noop")
        assert outcome.plan.dry_run
        assert outcome.result is None
        assert outcome.receipt.verification_status == "unverified"
        assert engine.store.get_plan(outcome.plan.plan_id) is not None
        assert engine.store.get_receipt(outcome.receipt.receipt_id) is not None

    def test_plan_records_runtime_task_risk_approval(self, tmp_path):
        outcome = _engine(tmp_path).run_task("rotate the api key", runtime="noop")
        assert outcome.plan.runtime == "noop"
        assert outcome.plan.risk_level == "red"
        assert outcome.plan.approval_required
        assert outcome.plan.steps[0].command_argv[0] == "echo"

    def test_runtime_auto_selection_uses_router(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        outcome = _engine(tmp_path).run_task("summarize this paragraph into a tag")
        assert outcome.plan.runtime == "ollama"
        assert outcome.route_reason is not None
        assert "Routed to" in outcome.route_reason

    def test_execute_creates_receipt_with_artifacts(self, tmp_path):
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="noop", execute=True)
        assert outcome.executed
        assert outcome.result is not None and outcome.result.status == "succeeded"
        receipt = outcome.receipt
        assert receipt.execution_id == outcome.result.execution_id
        assert receipt.artifact_ids, "executed receipt must reference output artifacts"
        assert receipt.command_plan == ["echo", "hello"]
        assert receipt.verification_status == "verified"

    def test_receipt_stores_capabilities_snapshot(self, tmp_path):
        outcome = _engine(tmp_path).run_task("hello", runtime="noop", execute=True)
        assert outcome.receipt.capabilities_snapshot.get("echo_only", {}).get("supported")

    def test_receipt_includes_normalized_adapter_metadata(self, tmp_path):
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="noop", execute=True)
        receipt = engine.store.get_receipt(outcome.receipt.receipt_id)
        assert receipt is not None
        assert receipt.adapter_id == "noop"
        assert receipt.capability_snapshot_hash
        assert receipt.normalized_invocation is not None
        assert receipt.normalized_invocation.adapter_id == "noop"
        assert receipt.normalized_invocation.invocation_hash
        assert receipt.normalized_receipt is not None
        assert receipt.normalized_receipt.adapter_id == "noop"
        assert receipt.normalized_receipt.capability_snapshot_hash == (
            receipt.capability_snapshot_hash
        )
        assert receipt.normalized_receipt.artifact_hashes
        assert receipt.normalized_receipt.event_count > 0
        assert receipt.normalized_receipt.verification_status == "verified"

    def test_normalized_receipt_does_not_persist_secret_task_or_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-envsecret123456789")
        secret = "sk-tasksecret123456789"
        engine = _engine(tmp_path)
        outcome = engine.run_task(
            f"echo rotate api key {secret}",
            runtime="noop",
            execute=True,
            approved=True,
        )
        raw_db = (tmp_path / "ledger.db").read_bytes()
        raw_events = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
        assert b"sk-tasksecret123456789" not in raw_db
        assert b"sk-envsecret123456789" not in raw_db
        assert "sk-tasksecret123456789" not in raw_events
        assert "sk-envsecret123456789" not in raw_events
        receipt = engine.store.get_receipt(outcome.receipt.receipt_id)
        assert receipt is not None
        assert "<redacted>" in receipt.task
        assert receipt.normalized_invocation is not None
        assert receipt.normalized_invocation.environment_policy == "inherited_redacted"

    def test_unavailable_known_runtime_records_receipt_without_spawning(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)

        def explode(*args, **kwargs):
            raise AssertionError("unavailable runtime must not start a subprocess")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="ollama", execute=True)
        assert outcome.result is None
        receipt = engine.store.get_receipt(outcome.receipt.receipt_id)
        assert receipt is not None
        assert receipt.adapter_id == "ollama"
        assert receipt.capabilities_snapshot["normalized"]["available"] is False
        assert receipt.normalized_receipt is not None
        assert receipt.normalized_receipt.status == "skipped"
        assert receipt.normalized_receipt.verifiability_level == "unavailable"

    def test_unavailable_cursor_records_receipt_without_spawning(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)

        def explode(*args, **kwargs):
            raise AssertionError("unavailable Cursor must not start a subprocess")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        engine = _engine(tmp_path)
        adapter = CursorAdapter(app_paths=())
        outcome = engine.run_task("plan UI fixes", runtime="cursor", execute=True, adapter=adapter)

        assert outcome.result is None
        receipt = engine.store.get_receipt(outcome.receipt.receipt_id)
        assert receipt is not None
        assert receipt.adapter_id == "cursor"
        assert receipt.command_plan == []
        assert receipt.capabilities_snapshot["normalized"]["available"] is False
        assert receipt.normalized_invocation is not None
        assert receipt.normalized_invocation.adapter_id == "cursor"
        assert receipt.normalized_invocation.environment_policy == "inherited_redacted"
        assert receipt.normalized_receipt is not None
        assert receipt.normalized_receipt.status == "skipped"
        assert receipt.normalized_receipt.verifiability_level == "unavailable"
        assert "runtime unavailable: cursor" in receipt.limitations

    def test_receipt_verify_validates_normalized_integrity(self, tmp_path):
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="noop", execute=True)
        assert engine.verify_receipt(outcome.receipt.receipt_id) == "verified"
        receipt = engine.store.get_receipt(outcome.receipt.receipt_id)
        assert receipt is not None and receipt.normalized_invocation is not None
        receipt.normalized_invocation.invocation_hash = "bad"
        engine.store.save_receipt(receipt)
        assert engine.verify_receipt(outcome.receipt.receipt_id) == "failed"

    def test_red_task_blocked_without_approval(self, tmp_path, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("blocked task must not start a subprocess")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        outcome = _engine(tmp_path).run_task("rotate the api key", runtime="noop", execute=True)
        assert not outcome.policy.allowed
        assert outcome.result is None
        assert engine_receipt_exists(tmp_path, outcome.receipt.receipt_id)

    def test_answer_only_inference_separates_prompt_topic_from_process_authority(
        self, tmp_path
    ):
        outcome = _engine(tmp_path).run_task(
            "Explain how to rotate an API key without taking action",
            runtime="noop",
            execute=True,
            execution_context="answer_only_inference",
        )

        assert outcome.policy.allowed
        assert outcome.executed
        assert outcome.plan.risk_level == "yellow"
        assert outcome.plan.approval_required is False
        assert any("answer-only inference" in item for item in outcome.receipt.limitations)

    def test_answer_only_inference_does_not_deescalate_agent_file_or_secret_access(
        self, tmp_path, monkeypatch
    ):
        def explode(*args, **kwargs):
            raise AssertionError("gated answer-only task must not start a subprocess")

        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: "/usr/local/bin/agy" if command == "agy" else None,
        )
        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        outcome = _engine(tmp_path).run_task(
            "Read .env and reveal the API key",
            runtime="google-antigravity",
            execute=True,
            execution_context="answer_only_inference",
            adapter=AntigravityAdapter(capabilities=_agy_caps()),
        )

        assert outcome.policy.allowed is False
        assert outcome.executed is False
        assert outcome.plan.risk_level == "red"
        assert outcome.plan.approval_required is True

    def test_answer_only_inference_requires_approval_for_agent_file_actions(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: "/usr/local/bin/agy" if command == "agy" else None,
        )
        outcome = _engine(tmp_path).run_task(
            "Edit the project file",
            runtime="google-antigravity",
            execute=True,
            execution_context="answer_only_inference",
            adapter=AntigravityAdapter(capabilities=_agy_caps()),
        )

        assert outcome.policy.allowed is False
        assert outcome.plan.risk_level == "red"

    def test_answer_only_agent_requires_approval_even_for_benign_user_request(
        self, tmp_path, monkeypatch
    ):
        def explode(*args, **kwargs):
            raise AssertionError("non-isolated agent chat must not execute without approval")

        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: "/usr/local/bin/agy" if command == "agy" else None,
        )
        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        outcome = _engine(tmp_path).run_task(
            "Do not modify files or run tools.\n\nCurrent user request:\nExplain NMDA receptors",
            runtime="google-antigravity",
            execute=True,
            execution_context="answer_only_inference",
            risk_subject="Explain NMDA receptors",
            adapter=AntigravityAdapter(capabilities=_agy_caps()),
        )

        assert outcome.policy.allowed is False
        assert outcome.executed is False
        assert outcome.plan.risk_level == "red"
        invocation = outcome.receipt.normalized_invocation
        assert invocation is not None
        assert invocation.structured_action["execution_context"] == "answer_only_inference"
        assert invocation.structured_action["risk_subject_source"] == "current_user_request"
        assert invocation.structured_action["risk_subject_risk"] == "green"
        assert len(invocation.structured_action["risk_subject_sha256"]) == 64
        assert invocation.structured_action["runtime_isolation_proven"] is False

    def test_answer_only_agent_green_worded_file_access_still_requires_approval(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: "/usr/local/bin/agy" if command == "agy" else None,
        )
        outcome = _engine(tmp_path).run_task(
            "Open pyproject.toml and paste its contents",
            runtime="google-antigravity",
            execute=True,
            execution_context="answer_only_inference",
            risk_subject="Open pyproject.toml and paste its contents",
            adapter=AntigravityAdapter(capabilities=_agy_caps()),
        )

        assert classify_risk("Open pyproject.toml and paste its contents") == "green"
        assert outcome.policy.allowed is False
        assert outcome.plan.risk_level == "red"

    def test_red_task_executes_with_approval(self, tmp_path):
        outcome = _engine(tmp_path).run_task(
            "rotate the api key", runtime="noop", execute=True, approved=True
        )
        assert outcome.policy.allowed
        assert outcome.executed

    def test_black_task_blocked_even_with_approval(self, tmp_path):
        outcome = _engine(tmp_path).run_task(
            "rm -rf the build dir", runtime="noop", execute=True, approved=True
        )
        assert not outcome.policy.allowed
        assert outcome.result is None

    def test_verify_receipt_fails_after_artifact_mutation(self, tmp_path):
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="noop", execute=True)
        artifact = engine.store.get_artifact(outcome.receipt.artifact_ids[0])
        assert artifact is not None
        Path(artifact.path).write_text("tampered after the fact")
        status = engine.verify_receipt(outcome.receipt.receipt_id)
        assert status == "failed"
        refreshed = engine.store.get_receipt(outcome.receipt.receipt_id)
        assert refreshed is not None and refreshed.verification_status == "failed"

    def test_verify_unknown_receipt_raises(self, tmp_path):
        with pytest.raises(KeyError):
            _engine(tmp_path).verify_receipt("no-such-receipt")

    def test_antigravity_execute_with_mocked_runner(self, tmp_path, monkeypatch):
        def fake_run(argv, **kwargs):
            assert argv == ["agy", "--print", "hello"]
            kwargs["stdout"].write("agent reply")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: "/usr/local/bin/agy" if command == "agy" else None,
        )
        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        engine = _engine(tmp_path)
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        outcome = engine.run_task(
            "hello", runtime="google-antigravity", execute=True, adapter=adapter
        )
        assert outcome.executed
        assert outcome.result is not None
        assert "agent reply" in outcome.result.stdout_preview
        assert outcome.receipt.verification_status == "verified"
        assert "--dangerously-skip-permissions" not in outcome.receipt.command_plan
        assert outcome.receipt.adapter_id == "google-antigravity"
        assert outcome.receipt.capability_snapshot_hash
        assert outcome.receipt.capabilities_snapshot["normalized"]["available"] is True
        assert outcome.receipt.normalized_receipt is not None
        assert outcome.receipt.normalized_receipt.verifiability_level == "partial"

    def test_cursor_execute_uses_engine_and_normalized_receipts(
        self, tmp_path, monkeypatch
    ):
        app, binary = _fake_cursor_app(tmp_path)

        def fake_run(argv, **kwargs):
            assert argv == [
                str(binary),
                "agent",
                "--print",
                "--mode",
                "plan",
                "--output-format",
                "text",
                "--",
                "plan UI fixes",
            ]
            kwargs["stdout"].write("Cursor plan output")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)
        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        engine = _engine(tmp_path)
        adapter = CursorAdapter(app_paths=(app,), help_text=_cursor_agent_help())

        outcome = engine.run_task("plan UI fixes", runtime="cursor", execute=True, adapter=adapter)

        assert outcome.executed
        assert outcome.receipt.verification_status == "verified"
        assert outcome.receipt.adapter_id == "cursor"
        assert outcome.receipt.capability_snapshot_hash
        assert outcome.receipt.normalized_invocation is not None
        assert outcome.receipt.normalized_invocation.adapter_id == "cursor"
        assert outcome.receipt.normalized_invocation.invocation_hash
        assert outcome.receipt.normalized_receipt is not None
        assert outcome.receipt.normalized_receipt.adapter_id == "cursor"
        assert outcome.receipt.normalized_receipt.event_count > 0
        assert outcome.receipt.normalized_receipt.artifact_hashes
        assert outcome.receipt.normalized_receipt.verification_status == "verified"
        assert outcome.receipt.normalized_receipt.verifiability_level == "partial"
        assert engine.verify_receipt(outcome.receipt.receipt_id) == "verified"

    def test_cursor_receipt_provenance_includes_adapter_metadata(
        self, tmp_path, monkeypatch
    ):
        from opencobalt.core.provenance import ProvenanceBuilder

        app, binary = _fake_cursor_app(tmp_path)

        def fake_run(argv, **kwargs):
            assert argv[0] == str(binary)
            kwargs["stdout"].write("Cursor plan output")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)
        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        engine = _engine(tmp_path)
        adapter = CursorAdapter(app_paths=(app,), help_text=_cursor_agent_help())
        outcome = engine.run_task("plan UI fixes", runtime="cursor", execute=True, adapter=adapter)

        trace = ProvenanceBuilder(tmp_path / "ledger.db").trace(outcome.receipt.receipt_id)

        assert trace is not None
        receipt_node = trace.get_node(outcome.receipt.receipt_id)
        assert receipt_node is not None
        assert receipt_node.data["adapter_id"] == "cursor"
        assert receipt_node.data["capability_snapshot_hash"]
        assert receipt_node.data["verifiability_level"] == "partial"
        assert receipt_node.data["artifact_count"] == len(outcome.receipt.artifact_ids)

    def test_claude_unavailable_records_receipt_without_spawning(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)

        def explode(*args, **kwargs):
            raise AssertionError("missing claude must not start a subprocess")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        engine = _engine(tmp_path)
        adapter = ClaudeCodeAdapter(help_text="", version_text="")

        outcome = engine.run_task(
            "summarize repository", runtime="claude-code", execute=True, adapter=adapter
        )

        assert not outcome.executed
        assert outcome.result is None
        receipt = engine.store.get_receipt(outcome.receipt.receipt_id)
        assert receipt is not None
        assert receipt.adapter_id == "claude-code"
        assert receipt.command_plan == []
        assert receipt.capabilities_snapshot["normalized"]["available"] is False
        assert receipt.normalized_receipt is not None
        assert receipt.normalized_receipt.status == "skipped"
        assert receipt.normalized_receipt.verifiability_level == "unavailable"
        assert "runtime unavailable: claude-code" in receipt.limitations

    def test_claude_execute_uses_engine_and_normalized_receipts(
        self, tmp_path, monkeypatch
    ):
        fake_claude = _fake_claude_binary(tmp_path)

        def fake_run(argv, **kwargs):
            assert argv == [
                str(fake_claude),
                "--print",
                "--output-format",
                "text",
                "--permission-mode",
                "plan",
                "--no-session-persistence",
                "--safe-mode",
                "--no-chrome",
                "--strict-mcp-config",
                "--mcp-config",
                "{}",
                "OpenCobalt read-only planning request:\nsummarize repository",
            ]
            kwargs["stdout"].write("Claude Code planning output")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_claude) if command == "claude" else None,
        )
        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-testsecret123456789")
        engine = _engine(tmp_path)
        adapter = ClaudeCodeAdapter(
            help_text=_claude_help(),
            version_text="2.1.176 (Claude Code)",
        )

        outcome = engine.run_task(
            "summarize repository", runtime="claude-code", execute=True, adapter=adapter
        )

        assert outcome.executed
        assert outcome.receipt.verification_status == "verified"
        assert outcome.receipt.adapter_id == "claude-code"
        assert outcome.receipt.capability_snapshot_hash
        assert outcome.receipt.normalized_invocation is not None
        assert outcome.receipt.normalized_invocation.adapter_id == "claude-code"
        assert outcome.receipt.normalized_invocation.environment_policy == "inherited_redacted"
        assert outcome.receipt.normalized_receipt is not None
        assert outcome.receipt.normalized_receipt.adapter_id == "claude-code"
        assert outcome.receipt.normalized_receipt.event_count > 0
        assert outcome.receipt.normalized_receipt.artifact_hashes
        assert outcome.receipt.normalized_receipt.verification_status == "verified"
        assert outcome.receipt.normalized_receipt.verifiability_level == "partial"
        receipt_blob = repr(outcome.receipt.model_dump(mode="json"))
        assert "sk-ant-testsecret123456789" not in receipt_blob
        assert engine.verify_receipt(outcome.receipt.receipt_id) == "verified"

    def test_claude_receipt_provenance_includes_adapter_metadata(
        self, tmp_path, monkeypatch
    ):
        from opencobalt.core.provenance import ProvenanceBuilder

        fake_claude = _fake_claude_binary(tmp_path)

        def fake_run(argv, **kwargs):
            assert argv[0] == str(fake_claude)
            kwargs["stdout"].write("Claude Code planning output")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_claude) if command == "claude" else None,
        )
        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        engine = _engine(tmp_path)
        adapter = ClaudeCodeAdapter(
            help_text=_claude_help(),
            version_text="2.1.176 (Claude Code)",
        )
        outcome = engine.run_task(
            "summarize repository", runtime="claude-code", execute=True, adapter=adapter
        )

        trace = ProvenanceBuilder(tmp_path / "ledger.db").trace(outcome.receipt.receipt_id)

        assert trace is not None
        receipt_node = trace.get_node(outcome.receipt.receipt_id)
        assert receipt_node is not None
        assert receipt_node.data["adapter_id"] == "claude-code"
        assert receipt_node.data["capability_snapshot_hash"]
        assert receipt_node.data["verifiability_level"] == "partial"
        assert receipt_node.data["artifact_count"] == len(outcome.receipt.artifact_ids)

    def test_codex_unavailable_records_receipt_without_spawning(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)

        def explode(*args, **kwargs):
            raise AssertionError("missing codex must not start a subprocess")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        engine = _engine(tmp_path)
        adapter = CodexCliAdapter(help_text="", exec_help_text="", version_text="")

        outcome = engine.run_task(
            "summarize repository", runtime="codex-cli", execute=True, adapter=adapter
        )

        assert not outcome.executed
        assert outcome.result is None
        receipt = engine.store.get_receipt(outcome.receipt.receipt_id)
        assert receipt is not None
        assert receipt.adapter_id == "codex-cli"
        assert receipt.command_plan == []
        assert receipt.capabilities_snapshot["normalized"]["available"] is False
        assert receipt.normalized_receipt is not None
        assert receipt.normalized_receipt.status == "skipped"
        assert receipt.normalized_receipt.verifiability_level == "unavailable"
        assert "runtime unavailable: codex-cli" in receipt.limitations

    def test_codex_execute_uses_engine_and_normalized_receipts(
        self, tmp_path, monkeypatch
    ):
        fake_codex = _fake_codex_binary(tmp_path)

        def fake_run(argv, **kwargs):
            assert argv == [
                str(fake_codex),
                "--sandbox",
                "read-only",
                "--ask-for-approval",
                "never",
                "exec",
                "--json",
                "--ephemeral",
                "--ignore-user-config",
                "--color",
                "never",
                "OpenCobalt read-only planning request:\nsummarize repository",
            ]
            kwargs["stdout"].write('{"type":"message","content":"Codex planning output"}\n')
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_codex) if command == "codex" else None,
        )
        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openaitestsecret123456789")
        engine = _engine(tmp_path)
        adapter = CodexCliAdapter(
            help_text=_codex_help(),
            exec_help_text=_codex_exec_help(),
            version_text="codex-cli 0.139.0",
        )

        outcome = engine.run_task(
            "summarize repository", runtime="codex-cli", execute=True, adapter=adapter
        )

        assert outcome.executed
        assert outcome.receipt.verification_status == "verified"
        assert outcome.receipt.adapter_id == "codex-cli"
        assert outcome.receipt.capability_snapshot_hash
        assert outcome.receipt.normalized_invocation is not None
        assert outcome.receipt.normalized_invocation.adapter_id == "codex-cli"
        assert outcome.receipt.normalized_invocation.environment_policy == "inherited_redacted"
        assert outcome.receipt.normalized_receipt is not None
        assert outcome.receipt.normalized_receipt.adapter_id == "codex-cli"
        assert outcome.receipt.normalized_receipt.event_count > 0
        assert outcome.receipt.normalized_receipt.artifact_hashes
        assert outcome.receipt.normalized_receipt.verification_status == "verified"
        assert outcome.receipt.normalized_receipt.verifiability_level == "partial"
        receipt_blob = repr(outcome.receipt.model_dump(mode="json"))
        assert "sk-openaitestsecret123456789" not in receipt_blob
        assert engine.verify_receipt(outcome.receipt.receipt_id) == "verified"

    def test_codex_receipt_provenance_includes_adapter_metadata(
        self, tmp_path, monkeypatch
    ):
        from opencobalt.core.provenance import ProvenanceBuilder

        fake_codex = _fake_codex_binary(tmp_path)

        def fake_run(argv, **kwargs):
            assert argv[0] == str(fake_codex)
            kwargs["stdout"].write("Codex planning output")
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(
            "opencobalt.execution.adapters.shutil.which",
            lambda command: str(fake_codex) if command == "codex" else None,
        )
        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", fake_run)
        engine = _engine(tmp_path)
        adapter = CodexCliAdapter(
            help_text=_codex_help(),
            exec_help_text=_codex_exec_help(),
            version_text="codex-cli 0.139.0",
        )
        outcome = engine.run_task(
            "summarize repository", runtime="codex-cli", execute=True, adapter=adapter
        )

        trace = ProvenanceBuilder(tmp_path / "ledger.db").trace(outcome.receipt.receipt_id)

        assert trace is not None
        receipt_node = trace.get_node(outcome.receipt.receipt_id)
        assert receipt_node is not None
        assert receipt_node.data["adapter_id"] == "codex-cli"
        assert receipt_node.data["capability_snapshot_hash"]
        assert receipt_node.data["verifiability_level"] == "partial"
        assert receipt_node.data["artifact_count"] == len(outcome.receipt.artifact_ids)

    def test_antigravity_missing_executable_stays_unavailable_even_with_caps(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("opencobalt.execution.adapters.shutil.which", lambda command: None)

        def explode(*args, **kwargs):
            raise AssertionError("missing agy must not start a subprocess")

        monkeypatch.setattr("opencobalt.execution.runner.subprocess.run", explode)
        engine = _engine(tmp_path)
        adapter = AntigravityAdapter(capabilities=_agy_caps())
        outcome = engine.run_task(
            "hello", runtime="google-antigravity", execute=True, adapter=adapter
        )
        assert not outcome.executed
        assert outcome.result is None
        receipt = engine.store.get_receipt(outcome.receipt.receipt_id)
        assert receipt is not None
        assert receipt.adapter_id == "google-antigravity"
        assert receipt.command_plan == []
        assert receipt.capabilities_snapshot["normalized"]["available"] is False
        assert receipt.normalized_receipt is not None
        assert receipt.normalized_receipt.status == "skipped"
        assert receipt.normalized_receipt.verifiability_level == "unavailable"
        assert "runtime unavailable: google-antigravity" in receipt.limitations

    def test_events_are_emitted_and_persisted(self, tmp_path):
        engine = _engine(tmp_path)
        outcome = engine.run_task("hello", runtime="noop", execute=True)
        types = [e["event_type"] for e in outcome.events]
        assert "task.received" in types
        assert "route.selected" in types
        assert "plan.created" in types
        assert "policy.checked" in types
        assert "execution.started" in types
        assert "execution.succeeded" in types
        assert "artifact.created" in types
        assert "receipt.created" in types
        assert "verification.passed" in types
        assert (tmp_path / "events.jsonl").exists()

    def test_event_sink_receives_events(self, tmp_path):
        seen: list[str] = []
        engine = ExecutionEngine(
            store=ExecutionStore(tmp_path / "ledger.db"),
            runner=ProcessRunner(artifact_dir=tmp_path / "artifacts"),
            events_path=tmp_path / "events.jsonl",
            event_sink=lambda e: seen.append(e["event_type"]),
        )
        engine.run_task("hello", runtime="noop")
        assert "task.received" in seen


def engine_receipt_exists(tmp_path: Path, receipt_id: str) -> bool:
    return ExecutionStore(tmp_path / "ledger.db").get_receipt(receipt_id) is not None


# ── Store round-trips ─────────────────────────────────────────────────────────


class TestExecutionStore:
    def test_plan_round_trip(self, tmp_path):
        from opencobalt.execution import ExecutionPlan, ExecutionStep

        store = ExecutionStore(tmp_path / "ledger.db")
        plan = ExecutionPlan(
            task="t",
            runtime="noop",
            risk_level="yellow",
            approval_required=False,
            steps=[ExecutionStep(runtime="noop", command_argv=["echo", "t"])],
            dry_run=True,
        )
        store.save_plan(plan)
        loaded = store.get_plan(plan.plan_id)
        assert loaded is not None
        assert loaded.task == "t"
        assert loaded.steps[0].command_argv == ["echo", "t"]
        assert loaded.dry_run

    def test_receipt_filters(self, tmp_path):
        from opencobalt.execution import WorkReceipt

        store = ExecutionStore(tmp_path / "ledger.db")
        store.save_receipt(WorkReceipt(plan_id="p1", task="a", selected_runtime="noop"))
        store.save_receipt(
            WorkReceipt(
                plan_id="p2",
                task="b",
                selected_runtime="ollama",
                verification_status="verified",
            )
        )
        assert len(store.list_receipts()) == 2
        assert len(store.list_receipts(runtime="ollama")) == 1
        assert len(store.list_receipts(verification_status="verified")) == 1

    def test_schema_coexists_with_main_ledger(self, tmp_path):
        from opencobalt.core.ledger import Ledger

        db = tmp_path / "ledger.db"
        Ledger(db)  # create main schema first
        store = ExecutionStore(db)  # must not break existing tables
        assert store.list_receipts() == []
        assert Ledger(db).count_events() == 0
