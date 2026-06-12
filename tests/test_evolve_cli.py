"""CLI tests for opencobalt evolve commands.

Every test chdirs into tmp_path so all state lands in a throwaway
directory. Execution uses the noop adapter only; no git push, merge, or
deploy ever happens.
"""

from __future__ import annotations

import re
import subprocess

from typer.testing import CliRunner

from opencobalt.cli import app

runner = CliRunner()

ROADMAP = """# Roadmap

## In Progress / Next

- Outcome-weighted scoring: feed outcomes back into track priors
- UI panels for opportunity tracks and approval state
"""


def _invoke(*args: str, **kwargs):
    env = {**kwargs.pop("env", {}), "NO_COLOR": "1", "COLUMNS": "200"}
    kwargs.setdefault("color", False)
    return runner.invoke(app, list(args), env=env, **kwargs)


def _first(pattern: str, output: str) -> str:
    match = re.search(pattern, output)
    assert match, f"no match for {pattern} in output: {output}"
    return match.group(1)


def _seed_repo(tmp_path) -> None:
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "ROADMAP.md").write_text(ROADMAP)
    (tmp_path / "alpha.py").write_text("x = 1\n")


def _start_mission(tmp_path) -> tuple[str, str]:
    """Start a mission. Returns (mission_id, top candidate id)."""
    _seed_repo(tmp_path)
    result = _invoke("evolve", "start", "make OpenCobalt more useful this week")
    assert result.exit_code == 0, result.output
    mission_id = _first(r"(emis-[0-9a-f]{6,})", result.output)
    candidate_id = _first(r"(ecand-[0-9a-f]{6,})", result.output)
    return mission_id, candidate_id


class TestStart:
    def test_start_prints_report_and_next_commands(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mission_id, candidate_id = _start_mission(tmp_path)
        assert mission_id.startswith("emis-")
        assert candidate_id.startswith("ecand-")

    def test_bare_evolve_goal_starts_mission(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _seed_repo(tmp_path)
        result = _invoke("evolve", "make OpenCobalt more useful this week")
        assert result.exit_code == 0, result.output
        assert "Evolve mission" in result.output
        assert "ecand-" in result.output

    def test_start_never_starts_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _seed_repo(tmp_path)

        def explode(*args, **kwargs):
            raise AssertionError("evolve start must not start a subprocess")

        monkeypatch.setattr(subprocess, "run", explode)
        monkeypatch.setattr(subprocess, "Popen", explode)
        result = _invoke("evolve", "start", "improve quietly")
        assert result.exit_code == 0

    def test_bare_evolve_prints_usage(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("evolve")
        assert result.exit_code == 0
        assert "Usage" in result.output


class TestReportAndCandidates:
    def test_report_shows_ranked_candidates(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mission_id, _ = _start_mission(tmp_path)
        result = _invoke("evolve", "report", mission_id)
        assert result.exit_code == 0
        assert "Evolve report" in result.output
        assert "Escape" in result.output

    def test_report_defaults_to_latest(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _start_mission(tmp_path)
        result = _invoke("evolve", "report")
        assert result.exit_code == 0

    def test_report_without_missions_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("evolve", "report")
        assert result.exit_code == 1

    def test_candidates_shows_steps_and_explain(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mission_id, candidate_id = _start_mission(tmp_path)
        result = _invoke(
            "evolve", "candidates", mission_id, "--explain", candidate_id
        )
        assert result.exit_code == 0
        assert "Score explanation" in result.output
        assert "wrapperware_escape_value" in result.output

    def test_list_shows_missions(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mission_id, _ = _start_mission(tmp_path)
        result = _invoke("evolve", "list")
        assert mission_id[:16] in result.output


class TestApproveAndRun:
    def test_approve_creates_request(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, candidate_id = _start_mission(tmp_path)
        result = _invoke("evolve", "approve", candidate_id)
        assert result.exit_code == 0
        assert "areq-" in result.output
        listed = _invoke("approvals", "list")
        assert "areq-" in listed.output

    def test_run_refuses_without_approval(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, candidate_id = _start_mission(tmp_path)
        result = _invoke("evolve", "run", candidate_id, "--runtime", "noop")
        assert result.exit_code == 1
        assert "evolve approve" in result.output

    def test_run_dry_run_by_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, candidate_id = _start_mission(tmp_path)
        _invoke("evolve", "approve", candidate_id)
        result = _invoke("evolve", "run", candidate_id, "--runtime", "noop")
        assert result.exit_code == 0
        assert "dry-run" in result.output
        assert "Add --execute" in result.output

    def test_run_execute_writes_receipts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, candidate_id = _start_mission(tmp_path)
        _invoke("evolve", "approve", candidate_id)
        result = _invoke(
            "evolve", "run", candidate_id, "--runtime", "noop", "--execute"
        )
        assert result.exit_code == 0
        assert "executed" in result.output
        receipts = _invoke("receipts", "list")
        assert "noop" in receipts.output

    def test_unknown_candidate_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("evolve", "run", "ecand-missing")
        assert result.exit_code == 1


class TestRoadmapCommand:
    def test_roadmap_read_only_by_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mission_id, _ = _start_mission(tmp_path)
        before = (tmp_path / "docs" / "ROADMAP.md").read_text()
        result = _invoke("evolve", "roadmap", mission_id)
        assert result.exit_code == 0
        assert "read-only" in result.output
        assert (tmp_path / "docs" / "ROADMAP.md").read_text() == before

    def test_roadmap_write_appends(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mission_id, _ = _start_mission(tmp_path)
        result = _invoke("evolve", "roadmap", mission_id, "--write")
        assert result.exit_code == 0
        text = (tmp_path / "docs" / "ROADMAP.md").read_text()
        assert f"evolve mission {mission_id[:13]}" in text
        assert "nothing was pushed" in result.output
