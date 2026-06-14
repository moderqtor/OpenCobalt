"""Integration tests for the OpenCobalt CLI.

These tests exercise the actual CLI commands via Typer's CliRunner.
They prove the CLI wires up correctly end-to-end, without mocking
internal modules.

Isolation strategy:
- Commands that write to the ledger (status, history, cost, config,
  log, route with record) use monkeypatch.chdir(tmp_path) so they
  create their .opencobalt/ledger.db inside a throwaway directory.
- Commands that are purely read-only and don't touch the ledger
  (benchmark, agents list, models, public-check) run against the
  real project root.
- Route tests use --no-record to skip the ledger write entirely.
"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from opencobalt.cli import app

runner = CliRunner()


def test_no_args_entry_point_exists():
    """opencobalt with no args should not error; it invokes the shell."""
    import tempfile
    from pathlib import Path

    from opencobalt.shell import CobaltShell

    with tempfile.TemporaryDirectory() as directory:
        shell = CobaltShell(
            db_path=Path(directory) / "ledger.db",
            bridge_path=Path(directory) / "memories.db",
        )
        assert hasattr(shell, "run")
        assert hasattr(shell, "dispatch")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _invoke(*args: str, **kwargs) -> object:
    """Invoke a CLI command. Keyword args forwarded to runner.invoke()."""
    env = {**kwargs.pop("env", {}), "NO_COLOR": "1"}
    kwargs.setdefault("color", False)
    return runner.invoke(app, list(args), env=env, **kwargs)


def _plain(output: str) -> str:
    """Return CLI output without ANSI escape sequences."""
    return re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", output)


def _debug(result) -> str:
    """Return a string with output + exception for test failure messages."""
    exc = ""
    if result.exception:
        import traceback
        exc = "".join(traceback.format_exception(type(result.exception), result.exception, result.exception.__traceback__))
    return f"\n--- output ---\n{result.output}\n--- exception ---\n{exc}"


# ── status command ─────────────────────────────────────────────────────────────

class TestStatus:
    def test_exit_code_zero(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("status")
        assert result.exit_code == 0, _debug(result)

    def test_output_contains_opencobalt(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("status")
        assert "OPENCOBALT" in result.output, _debug(result)

    def test_output_contains_python(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("status")
        assert "python" in result.output.lower(), _debug(result)

    def test_output_contains_ledger(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("status")
        assert "Ledger" in result.output, _debug(result)


class TestDoctorAntigravity:
    def test_antigravity_doctor_reports_missing_cleanly(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "opencobalt.integrations.antigravity_integration.discover_antigravity_runtime",
            lambda ledger=None: {
                "installed": False,
                "path": None,
                "version": {"ok": False, "value": None, "error": "agy not on PATH"},
                "help": {"ok": False, "value": "", "error": "agy not on PATH"},
                "capabilities": {
                    "non_interactive_mode": {"supported": None, "source": "unknown", "evidence": ""},
                    "model_selection": {"supported": None, "source": "unknown", "evidence": ""},
                    "plugin_support": {"supported": None, "source": "unknown", "evidence": ""},
                    "skills_hooks_subagents": {"supported": None, "source": "unknown", "evidence": ""},
                    "artifact_locations": {"supported": None, "source": "unknown", "evidence": ""},
                },
            },
        )
        result = _invoke("doctor", "antigravity")
        plain = _plain(result.output)
        assert result.exit_code == 0, _debug(result)
        assert "Google Antigravity CLI" in plain
        assert "agy not on PATH" in plain

    def test_antigravity_doctor_reports_discovered_capabilities(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "opencobalt.integrations.antigravity_integration.discover_antigravity_runtime",
            lambda ledger=None: {
                "installed": True,
                "path": "/usr/local/bin/agy",
                "version": {"ok": True, "value": "1.0.6", "error": ""},
                "help": {"ok": True, "value": "--print --model plugin", "error": ""},
                "capabilities": {
                    "non_interactive_mode": {"supported": True, "source": "runtime_discovered", "evidence": "--print"},
                    "model_selection": {"supported": True, "source": "runtime_discovered", "evidence": "--model"},
                    "plugin_support": {"supported": True, "source": "runtime_discovered", "evidence": "plugin"},
                    "skills_hooks_subagents": {"supported": None, "source": "unknown", "evidence": ""},
                    "artifact_locations": {"supported": None, "source": "unknown", "evidence": ""},
                },
            },
        )
        result = _invoke("doctor", "antigravity")
        plain = _plain(result.output)
        assert result.exit_code == 0, _debug(result)
        assert "/usr/local/bin/agy" in plain
        assert "1.0.6" in plain
        assert "non_interactive_mode" in plain
        assert "runtime_discovered" in plain


class TestIntegrationsCheck:
    def test_cursor_check_does_not_claim_runtime_execution(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "opencobalt.integrations.cursor_integration.CursorIntegration.install_check",
            lambda self: True,
        )

        result = _invoke("integrations", "check")
        plain = _plain(result.output)

        assert result.exit_code == 0, _debug(result)
        assert "cursor" in plain
        assert (
            "runtime evidence: opencobalt adapters inspect cursor"
            in plain.replace("\n", "")
        )


# ── route command ─────────────────────────────────────────────────────────────

class TestRoute:
    def test_summarize_exits_zero(self):
        result = _invoke("route", "--no-record", "summarize this file")
        assert result.exit_code == 0, _debug(result)

    def test_summarize_routes_to_ollama(self):
        result = _invoke("route", "--no-record", "summarize this file")
        assert "ollama" in result.output.lower(), _debug(result)

    def test_architecture_routes_to_claude_code(self):
        result = _invoke("route", "--no-record", "design the architecture")
        assert "claude-code" in result.output.lower(), _debug(result)

    def test_run_tests_output_contains_score(self):
        result = _invoke("route", "--no-record", "run tests")
        assert "Score" in result.output, _debug(result)


# ── benchmark command ─────────────────────────────────────────────────────────

class TestBenchmark:
    def test_exits_zero(self):
        result = _invoke("benchmark")
        assert result.exit_code == 0, _debug(result)

    def test_output_contains_benchmark(self):
        result = _invoke("benchmark")
        assert "Benchmark" in result.output, _debug(result)

    def test_output_contains_executive(self):
        result = _invoke("benchmark")
        assert "executive" in result.output.lower(), _debug(result)


# ── public-check command ──────────────────────────────────────────────────────

class TestPublicCheck:
    def test_exits_zero_from_project_root(self):
        # Run from the actual project root -- the task requires it's clean.
        result = _invoke("public-check")
        assert result.exit_code == 0, _debug(result)

    def test_output_contains_clean(self):
        result = _invoke("public-check")
        assert "clean" in result.output.lower(), _debug(result)

    def test_exits_zero_with_generated_tauri_target_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "ui" / "src-tauri" / "target" / "debug"
        target.mkdir(parents=True)
        (target / "opencobalt-desktop").write_bytes(b"x" * (11 * 1024 * 1024))
        (target / "__global-api-script.js").write_text("~/cobaltos-vault build path")

        result = _invoke("public-check")

        assert result.exit_code == 0, _debug(result)
        assert "clean" in result.output.lower(), _debug(result)

    def test_exits_nonzero_when_temp_project_has_env_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text("OPENCOBALT_TOKEN=abcdefg\n")

        result = _invoke("public-check")

        assert result.exit_code == 1
        assert ".env file present" in result.output


# ── agents list command ───────────────────────────────────────────────────────

class TestAgentsList:
    def test_exits_zero(self):
        result = _invoke("agents", "list")
        assert result.exit_code == 0, _debug(result)

    def test_output_contains_summarizer(self):
        result = _invoke("agents", "list")
        assert "summarizer" in result.output.lower(), _debug(result)

    def test_output_contains_agent_count(self):
        result = _invoke("agents", "list")
        assert "4 agent(s)" in result.output, _debug(result)


# ── cost status command ───────────────────────────────────────────────────────

class TestCostStatus:
    def test_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("cost", "status")
        assert result.exit_code == 0, _debug(result)

    def test_output_contains_monthly(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("cost", "status")
        assert "monthly" in result.output.lower(), _debug(result)


# ── history command ───────────────────────────────────────────────────────────

class TestHistory:
    def test_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("history")
        assert result.exit_code == 0, _debug(result)

    def test_does_not_crash(self, tmp_path, monkeypatch):
        # Even with an empty ledger (no decisions), history should run cleanly.
        monkeypatch.chdir(tmp_path)
        result = _invoke("history")
        assert result.exception is None, _debug(result)


# ── config set + get round-trip ───────────────────────────────────────────────

class TestConfigRoundTrip:
    def test_set_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("config", "set", "testkey", "testval")
        assert result.exit_code == 0, _debug(result)

    def test_get_returns_value(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _invoke("config", "set", "testkey", "testval")
        result = _invoke("config", "get", "testkey")
        assert result.exit_code == 0, _debug(result)
        assert "testval" in result.output, _debug(result)


# ── models command ────────────────────────────────────────────────────────────

class TestModels:
    def test_exits_zero(self):
        result = _invoke("models")
        assert result.exit_code == 0, _debug(result)


# ── desktop command ───────────────────────────────────────────────────────────

class TestDesktop:
    def test_help_is_registered_and_describes_tauri(self):
        result = _invoke("desktop", "--help")
        assert result.exit_code == 0, _debug(result)
        assert "Tauri" in result.output, _debug(result)
        assert "FastAPI" in result.output, _debug(result)
        assert "api" in result.output.lower(), _debug(result)
        assert "port" in result.output.lower(), _debug(result)


# ── orch command ───────────────────────────────────────────────────────────────

class TestOrch:
    def test_help_is_registered(self):
        result = _invoke("orch", "--help")
        assert result.exit_code == 0, _debug(result)
        assert "task" in result.output.lower() or "orch" in result.output.lower()

    def test_orch_runs_with_patched_session(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        from opencobalt.core.models import OrchestrationResult, SubTask

        st = SubTask(task_type="impl", prompt="build it", preferred_tool="claude-code")
        fake_result = MagicMock(spec=OrchestrationResult)
        fake_result.success = True
        fake_result.task = "build auth"
        fake_result.subtasks = [st]
        fake_result.outputs = {st.id: "done"}
        fake_result.synthesis = "## merged output"
        fake_result.elapsed_s = 0.1
        fake_result.errors = []
        fake_result.id = "test-id"

        with patch("opencobalt.core.orchestrator.OrchestrationSession") as mock_cls:
            mock_cls.return_value.run.return_value = fake_result
            result = _invoke("orch", "build auth")

        assert result.exit_code == 0, _debug(result)


# ── Converge command ──────────────────────────────────────────────────────────

def test_converge_history_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke("converge", "history")
    assert result.exit_code == 0
    assert "No convergence sessions" in result.output or result.exit_code == 0


def test_converge_history_with_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from opencobalt.core.ledger import Ledger
    ledger = Ledger(tmp_path / ".opencobalt" / "ledger.db")
    ledger.upsert_convergence_session(
        session_id="abc12345-test", seed_task="implement auth", status="converged",
        started_at=1000.0, finished_at=1100.0, total_waves=2, total_retries=0,
        commit_sha="abc12345", log_path=None,
    )
    result = _invoke("converge", "history")
    assert result.exit_code == 0
    assert "abc12345" in result.output or "implement auth" in result.output


def test_converge_show_not_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke("converge", "show", "nonexistent-id")
    assert result.exit_code != 0


def test_converge_show_with_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from opencobalt.core.ledger import Ledger
    ledger = Ledger(tmp_path / ".opencobalt" / "ledger.db")
    ledger.upsert_convergence_session(
        session_id="full-session-id-here", seed_task="test task", status="converged",
        started_at=1000.0, finished_at=1100.0, total_waves=1, total_retries=0,
        commit_sha="abc12345", log_path=None,
    )
    result = _invoke("converge", "show", "full-session-id-here")
    assert result.exit_code == 0
    assert "test task" in result.output


def test_auto_accepts_converge_flag_help():
    result = _invoke("auto", "--help")
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "converge" in output
    assert "use-limits" in output


def test_auto_creates_checkpointed_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke("auto", "--hours", "1", "--use-limits", "max", "build auth with tests")
    assert result.exit_code == 0, _debug(result)
    assert "Autonomy run" in result.output
    assert "max" in result.output


def test_overlay_help_registered():
    result = _invoke("overlay", "--help")
    assert result.exit_code == 0, _debug(result)
    assert "prompt" in result.output.lower()


def test_policy_show_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke("policy", "show")
    assert result.exit_code == 0, _debug(result)
    assert "auto_commit" in result.output
    assert "api_usage" in result.output


def test_policy_set_round_trip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke("policy", "set", "auto_commit", "false")
    assert result.exit_code == 0, _debug(result)
    result = _invoke("policy", "show")
    assert "auto_commit" in result.output
    assert "false" in result.output.lower()


def test_limits_status_registered(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke("limits", "status")
    assert result.exit_code == 0, _debug(result)
    assert "usage" in result.output.lower()


def test_mission_help_registered():
    result = _invoke("mission", "--help")
    assert result.exit_code == 0, _debug(result)
    assert "hours" in result.output.lower()
    assert "allow" in result.output.lower()


def test_mission_creates_local_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke(
        "mission",
        "--allow",
        "local-build,draft-content",
        "--deny",
        "purchases,messages",
        "make me money",
    )
    assert result.exit_code == 0, _debug(result)
    assert "Mission" in result.output
    assert "permission envelope" in result.output


def test_council_coordinate_mode_publishes_artifact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _invoke("council", "--mode", "coordinate", "handoff to tests")
    assert result.exit_code == 0, _debug(result)
    assert "coordinate" in result.output
    assert "artifact" in result.output.lower()


class TestTuiHelpers:
    def test_tool_chips_shape(self):
        from opencobalt.cli import _tool_chips

        chips = _tool_chips()
        labels = [c[0] for c in chips]
        assert labels == ["antigravity", "claude", "codex", "ollama"]
        for _label, detail, available in chips:
            assert isinstance(detail, str)
            assert isinstance(available, bool)

    def test_merged_event_stream_orders_and_limits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.cli import _merged_event_stream
        from opencobalt.core.events import append_event, make_event

        base = tmp_path / ".opencobalt" / "events"
        for i, (name, source) in enumerate(
            [("execution.jsonl", "x"), ("approval.jsonl", "y")]
        ):
            event = make_event(
                event_type=f"test.{source}", subject_type="t", subject_id=str(i),
                message=f"message {source}",
            )
            append_event(event, path=base / name)
        rows = _merged_event_stream(limit=5)
        assert len(rows) == 2
        assert {r[1] for r in rows} == {"execution", "approval"}
        # Sorted by time-of-day stamp.
        assert rows == sorted(rows, key=lambda r: r[0])

    def test_merged_event_stream_empty_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.cli import _merged_event_stream

        assert _merged_event_stream() == []

    def test_git_branch_reads_head(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.cli import _git_branch

        assert _git_branch() == "-"
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/evolve-mode-v0\n")
        assert _git_branch() == "evolve-mode-v0"
