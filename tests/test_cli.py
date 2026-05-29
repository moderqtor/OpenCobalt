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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _invoke(*args: str, **kwargs) -> object:
    """Invoke a CLI command. Keyword args forwarded to runner.invoke()."""
    return runner.invoke(app, list(args), **kwargs)


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
