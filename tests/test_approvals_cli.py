"""CLI tests for opencobalt approvals and opportunities approve.

Every test chdirs into tmp_path so the ledger and event files land in a
throwaway directory. Execution uses the noop adapter only.
"""

from __future__ import annotations

import subprocess

from typer.testing import CliRunner

from opencobalt.cli import app
from tests.cli_output import first_match

runner = CliRunner()


def _invoke(*args: str, **kwargs):
    # Wide COLUMNS keeps rich tables from truncating ids under CliRunner.
    env = {**kwargs.pop("env", {}), "NO_COLOR": "1", "COLUMNS": "200"}
    kwargs.setdefault("color", False)
    return runner.invoke(app, list(args), env=env, **kwargs)


def _first(pattern: str, output: str) -> str:
    return first_match(pattern, output)


def _setup_request(
    goal: str = "improve code quality and test coverage",
    track_name: str = "test gaps",
) -> tuple[str, str]:
    """Brainstorm a goal and promote one named track. Returns (track_id, request_id).

    Defaults to the test-gaps track because its plan steps classify yellow,
    which exercises the explicit-approval path deterministically.
    """
    result = _invoke("opportunities", "brainstorm", goal)
    assert result.exit_code == 0
    track_id = _first(rf"(otrk-[0-9a-f]{{6,}})\s+{track_name}", result.output)
    promoted = _invoke("opportunities", "approve", track_id)
    assert promoted.exit_code == 0, promoted.output
    request_id = _first(r"(areq-[0-9a-f]{6,})", promoted.output)
    return track_id, request_id


class TestPromoteCommand:
    def test_promote_creates_request_with_next_commands(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, request_id = _setup_request()
        result = _invoke("approvals", "show", request_id)
        assert result.exit_code == 0
        assert "Approval request" in result.output
        assert "astp-" in result.output

    def test_promote_reuses_existing_request(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        track_id, request_id = _setup_request()
        again = _invoke("opportunities", "approve", track_id)
        assert again.exit_code == 0
        assert "reused" in again.output
        assert request_id[:13] in again.output

    def test_promote_new_supersedes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        track_id, request_id = _setup_request()
        fresh = _invoke("opportunities", "approve", track_id, "--new")
        assert fresh.exit_code == 0
        assert "created" in fresh.output
        new_id = _first(r"(areq-[0-9a-f]{6,})", fresh.output)
        assert new_id != request_id
        listed = _invoke("approvals", "list", "--state", "superseded")
        assert request_id[:14] in listed.output

    def test_promote_unknown_source_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("opportunities", "approve", "otrk-nope")
        assert result.exit_code == 1

    def test_promote_never_starts_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("opportunities", "brainstorm", "improve code quality")
        track_id = _first(r"(otrk-[0-9a-f]{6,})\s+test gaps", result.output)

        def explode(*args, **kwargs):
            raise AssertionError("approval creation must not start a subprocess")

        monkeypatch.setattr(subprocess, "run", explode)
        monkeypatch.setattr(subprocess, "Popen", explode)
        promoted = _invoke("opportunities", "approve", track_id)
        assert promoted.exit_code == 0


class TestListAndShow:
    def test_list_empty_hint(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("approvals", "list")
        assert result.exit_code == 0
        assert "No approval requests yet" in result.output

    def test_list_shows_request(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, request_id = _setup_request()
        result = _invoke("approvals", "list")
        assert result.exit_code == 0
        assert request_id[:14] in result.output

    def test_show_unknown_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("approvals", "show", "areq-missing")
        assert result.exit_code == 1


class TestApproveReject:
    def test_approve_all_steps(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, request_id = _setup_request()
        result = _invoke("approvals", "approve", request_id)
        assert result.exit_code == 0
        shown = _invoke("approvals", "show", request_id)
        assert "pending" not in shown.output.split("Decisions:")[0]

    def test_approve_single_step(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, request_id = _setup_request()
        shown = _invoke("approvals", "show", request_id)
        step_id = _first(r"(astp-[0-9a-f]{6,})", shown.output)
        result = _invoke("approvals", "approve", request_id, "--step", step_id)
        assert result.exit_code == 0

    def test_reject_with_reason(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, request_id = _setup_request()
        result = _invoke("approvals", "reject", request_id, "--reason", "not now")
        assert result.exit_code == 0
        shown = _invoke("approvals", "show", request_id)
        assert "rejected" in shown.output
        assert "not now" in shown.output


class TestRun:
    def test_unapproved_step_refused_with_hint(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, request_id = _setup_request()
        result = _invoke("approvals", "run", request_id, "--runtime", "noop")
        assert result.exit_code == 0  # dry-run never hard-fails
        assert "refused" in result.output
        assert "approvals approve" in result.output

    def test_dry_run_is_default(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, request_id = _setup_request()
        _invoke("approvals", "approve", request_id)
        result = _invoke("approvals", "run", request_id, "--runtime", "noop")
        assert result.exit_code == 0
        assert "dry-run" in result.output
        assert "Add --execute" in result.output
        # Dry-run still produces linked receipts but no execution.
        shown = _invoke("approvals", "show", request_id)
        assert "receipt:" in shown.output
        assert "executed" not in shown.output.split("Decisions:")[0]

    def test_execute_runs_noop_and_links_receipt(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, request_id = _setup_request()
        _invoke("approvals", "approve", request_id)
        result = _invoke(
            "approvals", "run", request_id, "--runtime", "noop", "--execute"
        )
        assert result.exit_code == 0
        assert "executed" in result.output
        receipts = _invoke("receipts", "list")
        assert "noop" in receipts.output

    def test_executed_step_skipped_without_rerun(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, request_id = _setup_request()
        _invoke("approvals", "approve", request_id)
        _invoke("approvals", "run", request_id, "--runtime", "noop", "--execute")
        again = _invoke("approvals", "run", request_id, "--runtime", "noop", "--execute")
        assert "skipped" in again.output
        assert "--rerun" in again.output

    def test_unknown_request_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("approvals", "run", "areq-missing")
        assert result.exit_code == 1


class TestOutcome:
    def test_outcome_links_receipt_to_track(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        track_id, request_id = _setup_request()
        _invoke("approvals", "approve", request_id)
        _invoke("approvals", "run", request_id, "--runtime", "noop", "--execute")
        result = _invoke("approvals", "outcome", request_id, "useful")
        assert result.exit_code == 0
        assert "Outcome recorded" in result.output
        assert "Receipt evidence" in result.output

        from opencobalt.core.opportunity_store import OpportunityStore

        outcomes = OpportunityStore(tmp_path / ".opencobalt" / "ledger.db").list_outcomes()
        assert outcomes
        assert outcomes[0]["track_id"].startswith("otrk-")
        assert outcomes[0]["receipt_id"]

    def test_invalid_outcome_label_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _, request_id = _setup_request()
        result = _invoke("approvals", "outcome", request_id, "amazing")
        assert result.exit_code == 1


class TestPlanIdempotency:
    def test_plan_reused_unless_new(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("opportunities", "brainstorm", "improve code quality", "--no-plans")
        track_id = _first(r"(otrk-[0-9a-f]{6,})", result.output)
        first = _invoke("opportunities", "plan", track_id)
        plan_id = _first(r"(oplan-[0-9a-f]{6,})", first.output)
        second = _invoke("opportunities", "plan", track_id)
        assert _first(r"(oplan-[0-9a-f]{6,})", second.output) == plan_id
        fresh = _invoke("opportunities", "plan", track_id, "--new")
        assert _first(r"(oplan-[0-9a-f]{6,})", fresh.output) != plan_id
