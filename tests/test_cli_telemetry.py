# tests/test_cli_telemetry.py
from unittest.mock import MagicMock

from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.core.scoring_engine import ScoringEngine
from opencobalt.core.telemetry import TelemetryStore

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


def test_telemetry_show_prefix_id(tmp_path, monkeypatch):
    run_id = _seed_db(tmp_path)
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "show", run_id[:8]])
    assert result.exit_code == 0
    assert "summarize logs" in result.output
    assert "Overall Score" in result.output


def test_telemetry_show_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "show", "nonexistent-run-id"])
    assert result.exit_code == 1


def test_telemetry_score_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "score", "nonexistent-run-id"])
    assert result.exit_code == 1


def test_telemetry_score_scores_existing_run(tmp_path, monkeypatch):
    store = TelemetryStore(tmp_path / "telemetry.db")
    session = store.start_run(run_type="route", seed_prompt="summarize logs", agent_id="claude-code")
    session.record_output("log summary", token_count=100)
    session.finish("complete")
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    monkeypatch.setattr("opencobalt.cli._DB_PATH", tmp_path / "ledger.db")

    judge = MagicMock()
    judge.judge_name = "heuristic"
    judge.judge.return_value = {
        "output_quality": 70, "prompt_adherence": 70, "novel_ideation": 70,
        "context_handling": 70, "tool_appropriateness": 70, "task_decomposition": 70,
        "agent_selection": 70, "reasoning": "", "summary": "Done.", "_judge": "heuristic",
    }
    monkeypatch.setattr("opencobalt.core.ollama_judge.OllamaJudge", lambda model: judge)

    result = runner.invoke(app, ["telemetry", "score", session.run_id[:8]])

    assert result.exit_code == 0
    assert "Overall:" in result.output
    assert store.get_score(session.run_id) is not None


def test_telemetry_export_no_path_configured(tmp_path, monkeypatch):
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "export"])
    assert result.exit_code == 1


def test_telemetry_export_writes_files(tmp_path, monkeypatch):
    _seed_db(tmp_path)
    export_dir = tmp_path / "exports"
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["telemetry", "export", "--output", str(export_dir)])
    assert result.exit_code == 0
    md_files = list(export_dir.glob("*.md"))
    assert len(md_files) == 1


def test_benchmark_status_telemetry_flag(tmp_path, monkeypatch):
    _seed_db(tmp_path)
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["benchmark", "status", "--telemetry"])
    assert result.exit_code == 0
    assert "claude-code" in result.output


def test_benchmark_status_telemetry_flag_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("opencobalt.cli._TELEMETRY_DB_PATH", tmp_path / "telemetry.db")
    result = runner.invoke(app, ["benchmark", "status", "--telemetry"])
    assert result.exit_code == 0
    assert "No scored runs" in result.output
