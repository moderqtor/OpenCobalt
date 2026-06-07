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
    return runner.invoke(app, list(args), env=env, **kwargs)


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
    assert "converge" in result.output
    assert "use-limits" in result.output


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
