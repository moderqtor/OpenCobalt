"""CLI integration tests for OpenCobalt Daily Operator commands."""

import json

from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.core.ledger import Ledger

runner = CliRunner()


def test_cli_capture_and_inbox(tmp_path, monkeypatch):
    db_file = tmp_path / "ledger.db"
    monkeypatch.setattr("opencobalt.core.config.get_db_path", lambda: db_file)

    # Capture command
    res_cap = runner.invoke(app, ["capture", "Finish advocacy paper outline"])
    assert res_cap.exit_code == 0
    assert "Captured" in res_cap.stdout

    # Inbox command
    res_inb = runner.invoke(app, ["inbox"])
    assert res_inb.exit_code == 0
    assert "Finish advocacy paper outline" in res_inb.stdout

    # Inbox JSON
    res_inb_json = runner.invoke(app, ["inbox", "--json"])
    assert res_inb_json.exit_code == 0
    data = json.loads(res_inb_json.stdout)
    assert data["status"] == "success"
    assert len(data["data"]["items"]) == 1
    assert data["data"]["items"][0]["raw_text"] == "Finish advocacy paper outline"


def test_cli_clarify_today_and_next(tmp_path, monkeypatch):
    db_file = tmp_path / "ledger.db"
    monkeypatch.setattr("opencobalt.core.config.get_db_path", lambda: db_file)

    # 1. Capture item
    res_cap = runner.invoke(app, ["capture", "Email Tuition Exchange", "--json"])
    assert res_cap.exit_code == 0
    cpt_id = json.loads(res_cap.stdout)["data"]["capture_id"]

    # 2. Clarify item
    res_clar = runner.invoke(app, ["clarify", cpt_id, "--title", "Email Tuition Exchange re award", "--impact", "4", "--due", "2026-07-22T17:00:00Z"])
    assert res_clar.exit_code == 0
    assert "Clarified" in res_clar.stdout

    # 3. Today command
    res_today = runner.invoke(app, ["today"])
    assert res_today.exit_code == 0
    assert "Email Tuition Exchange re award" in res_today.stdout

    # 4. Next command
    res_next = runner.invoke(app, ["next", "--json"])
    assert res_next.exit_code == 0
    next_data = json.loads(res_next.stdout)["data"]
    assert "Email Tuition Exchange re award" in next_data["commitment"]["title"]


def test_cli_focus_done_and_review(tmp_path, monkeypatch):
    db_file = tmp_path / "ledger.db"
    monkeypatch.setattr("opencobalt.core.config.get_db_path", lambda: db_file)

    # Capture & Clarify
    res_cap = runner.invoke(app, ["capture", "Write daily operator tests", "--json"])
    cpt_id = json.loads(res_cap.stdout)["data"]["capture_id"]

    res_clar = runner.invoke(app, ["clarify", cpt_id, "--json"])
    cmt_id = json.loads(res_clar.stdout)["data"]["commitment_id"]

    # Focus start
    res_foc = runner.invoke(app, ["focus", cmt_id])
    assert res_foc.exit_code == 0
    assert "Focus Started" in res_foc.stdout

    # Done command
    res_done = runner.invoke(app, ["done", cmt_id, "-s", "All tests passing", "-f", "Write docs"])
    assert res_done.exit_code == 0
    assert "Completed" in res_done.stdout

    # Review command
    res_rev = runner.invoke(app, ["review", "--json"])
    assert res_rev.exit_code == 0
    rev_data = json.loads(res_rev.stdout)["data"]
    assert rev_data["scorecard"]["completed_count"] == 1


def test_cli_search_and_why(tmp_path, monkeypatch):
    db_file = tmp_path / "ledger.db"
    monkeypatch.setattr("opencobalt.core.config.get_db_path", lambda: db_file)

    # Capture item
    res_cap = runner.invoke(app, ["capture", "Research quantum compiler", "--json"])
    cpt_id = json.loads(res_cap.stdout)["data"]["capture_id"]

    # Search
    res_srch = runner.invoke(app, ["search", "quantum"])
    assert res_srch.exit_code == 0
    assert cpt_id in res_srch.stdout

    # Why command
    res_why = runner.invoke(app, ["why", cpt_id])
    assert res_why.exit_code == 0


def test_cli_why_links_and_resolves_daily_completion_outcome(tmp_path, monkeypatch):
    db_file = tmp_path / "ledger.db"
    monkeypatch.setattr("opencobalt.core.config.get_db_path", lambda: db_file)

    captured = runner.invoke(app, ["capture", "Write provenance test", "--json"])
    capture_id = json.loads(captured.stdout)["data"]["capture_id"]
    clarified = runner.invoke(app, ["clarify", capture_id, "--json"])
    commitment_id = json.loads(clarified.stdout)["data"]["commitment_id"]
    completed = runner.invoke(
        app,
        ["done", commitment_id, "--summary", "Provenance verified"],
    )
    assert completed.exit_code == 0

    outcomes = Ledger(db_file).list_outcomes(tool="daily_operator")
    assert len(outcomes) == 1
    outcome_id = outcomes[0]["id"]

    commitment_why = runner.invoke(app, ["why", commitment_id])
    assert commitment_why.exit_code == 0
    assert "recorded_outcome" in commitment_why.stdout
    assert outcome_id[:14] in commitment_why.stdout

    outcome_why = runner.invoke(app, ["why", outcome_id])
    assert outcome_why.exit_code == 0
    assert "kind: outcome" in outcome_why.stdout
    assert commitment_id[:14] in outcome_why.stdout
