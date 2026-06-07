# tests/test_cli_telemetry.py
from typer.testing import CliRunner
from opencobalt.cli import app
from opencobalt.core.telemetry import TelemetryStore
from opencobalt.core.scoring_engine import ScoringEngine
from unittest.mock import MagicMock


runner = CliRunner()


def _seed_db(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry.db")
    session = store.start_run(run_type="route", seed_prompt="summarize logs", agent_id="claude-code")
    session.record_tool_use("pytest")
    session.record_output("log summary", token_count=100)
    session.finish("complete")
    judge = MagicMock()
    judge.judge_name = "heuristic"
    judge.judge.return_value = {
        "output_quality": 70, "prompt_adherence": 70, "novel_ideation": 70,
        "context_handling": 70, "tool_appropriateness": 70, "task_decomposition": 70,
        "agent_selection": 70, "reasoning": "", "summary": "Done.", "_judge": "heuristic",
    }
    ScoringEngine(store, judge=judge).score(session.run_id)
    return session.run_id


def test_telemetry_status(tmp_path, monkeypatch):
    _seed_db(tmp_path)
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "status"])
    assert result.exit_code == 0
    assert "1" in result.output  # 1 run


def test_telemetry_runs(tmp_path, monkeypatch):
    run_id = _seed_db(tmp_path)
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "runs"])
    assert result.exit_code == 0
    assert run_id[:8] in result.output


def test_telemetry_show(tmp_path, monkeypatch):
    run_id = _seed_db(tmp_path)
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "show", run_id])
    assert result.exit_code == 0
    assert "summarize logs" in result.output


def test_telemetry_scores(tmp_path, monkeypatch):
    _seed_db(tmp_path)
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "scores"])
    assert result.exit_code == 0
    assert "claude-code" in result.output
