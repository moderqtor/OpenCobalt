"""CLI tests for opencobalt opportunities commands.

Follows the isolation strategy from test_execution_cli.py: every test
chdirs into tmp_path so the ledger and event files land in a throwaway
directory. No live agent runtimes are invoked.
"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from opencobalt.cli import app

runner = CliRunner()


def _invoke(*args: str, **kwargs) -> object:
    env = {**kwargs.pop("env", {}), "NO_COLOR": "1"}
    kwargs.setdefault("color", False)
    return runner.invoke(app, list(args), env=env, **kwargs)


def _track_id(output: str) -> str:
    match = re.search(r"(otrk-[0-9a-f]{6,})", output)
    assert match, f"no track id in output: {output}"
    return match.group(1)


class TestBrainstorm:
    def test_brainstorm_runs_full_pipeline(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke(
            "opportunities", "brainstorm", "improve code quality and test coverage"
        )
        assert result.exit_code == 0
        assert "class: code_quality" in result.output
        assert "test gaps" in result.output
        assert "non-executing plan(s) created" in result.output
        assert "Next actions:" in result.output

    def test_brainstorm_never_starts_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import subprocess

        def explode(*args, **kwargs):
            raise AssertionError("brainstorm must not start a subprocess")

        monkeypatch.setattr(subprocess, "run", explode)
        monkeypatch.setattr(subprocess, "Popen", explode)
        result = _invoke("opportunities", "brainstorm", "find useful opportunities")
        assert result.exit_code == 0

    def test_no_plans_flag_skips_planning(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("opportunities", "brainstorm", "improve docs", "--no-plans")
        assert result.exit_code == 0
        assert "plan(s) created" not in result.output


class TestScoreAndReport:
    def test_report_prints_ranked_table(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _invoke("opportunities", "brainstorm", "improve code quality")
        result = _invoke("opportunities", "report")
        assert result.exit_code == 0
        assert "Opportunity report" in result.output
        assert "Score" in result.output
        assert "otrk-" in result.output

    def test_report_without_runs_fails_cleanly(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("opportunities", "report")
        assert result.exit_code == 1

    def test_score_rescoring_and_explanation(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        first = _invoke("opportunities", "brainstorm", "improve code quality", "--no-plans")
        track_id = _track_id(first.output)
        result = _invoke("opportunities", "score", "--explain", track_id)
        assert result.exit_code == 0
        assert "Rescored" in result.output
        assert "expected_impact" in result.output
        assert "total=" in result.output


class TestPlan:
    def test_plan_creates_non_executing_plan(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        first = _invoke("opportunities", "brainstorm", "improve docs", "--no-plans")
        track_id = _track_id(first.output)
        result = _invoke("opportunities", "plan", track_id)
        assert result.exit_code == 0
        assert "Executed: no" in result.output
        assert "strategist" in result.output
        assert "policy gate" in result.output

    def test_plan_unknown_track_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("opportunities", "plan", "otrk-nonexistent")
        assert result.exit_code == 1


class TestListAndOutcome:
    def test_list_shows_runs(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _invoke("opportunities", "brainstorm", "grow community adoption", "--no-plans")
        result = _invoke("opportunities", "list")
        assert result.exit_code == 0
        assert "growth" in result.output

    def test_outcome_recording(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        first = _invoke("opportunities", "brainstorm", "improve docs", "--no-plans")
        track_id = _track_id(first.output)
        result = _invoke("opportunities", "outcome", track_id, "useful", "--notes", "shipped")
        assert result.exit_code == 0
        assert "Outcome recorded" in result.output

    def test_invalid_outcome_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("opportunities", "outcome", "otrk-x", "amazing")
        assert result.exit_code == 1


class TestPublicSafety:
    def test_public_check_clean_with_new_modules(self, monkeypatch):
        result = _invoke("public-check")
        assert result.exit_code == 0
        assert "clean" in result.output
