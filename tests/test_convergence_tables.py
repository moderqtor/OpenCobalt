import pytest
import sqlite3
from pathlib import Path
from opencobalt.core.ledger import Ledger


def test_convergence_tables_created(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    conn = sqlite3.connect(ledger.db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "convergence_sessions" in tables
    assert "convergence_wave_results" in tables


def test_upsert_and_get_convergence_session(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    ledger.upsert_convergence_session(
        session_id="test-123",
        seed_task="implement auth",
        status="queued",
        started_at=1000.0,
        finished_at=None,
        total_waves=0,
        total_retries=0,
        commit_sha=None,
        log_path=None,
    )
    row = ledger.get_convergence_session("test-123")
    assert row is not None
    assert row["seed_task"] == "implement auth"
    assert row["status"] == "queued"


def test_upsert_updates_existing_session(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    ledger.upsert_convergence_session(
        session_id="s1", seed_task="task A", status="queued",
        started_at=1.0, finished_at=None, total_waves=0,
        total_retries=0, commit_sha=None, log_path=None,
    )
    ledger.upsert_convergence_session(
        session_id="s1", seed_task="task A", status="converged",
        started_at=1.0, finished_at=2.0, total_waves=2,
        total_retries=1, commit_sha="abc12345", log_path=None,
    )
    row = ledger.get_convergence_session("s1")
    assert row["status"] == "converged"
    assert row["commit_sha"] == "abc12345"


def test_list_convergence_sessions(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    for i in range(3):
        ledger.upsert_convergence_session(
            session_id=f"s{i}", seed_task=f"task {i}", status="converged",
            started_at=float(i), finished_at=float(i + 1), total_waves=1,
            total_retries=0, commit_sha=None, log_path=None,
        )
    sessions = ledger.list_convergence_sessions(limit=10)
    assert len(sessions) == 3


def test_insert_and_get_wave_results(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    ledger.upsert_convergence_session(
        session_id="s1", seed_task="task", status="running",
        started_at=1.0, finished_at=None, total_waves=1,
        total_retries=0, commit_sha=None, log_path=None,
    )
    ledger.insert_wave_result(
        session_id="s1",
        wave=0,
        tests_ok=True,
        verifier_score=0.85,
        verifier_ok=True,
        passed=True,
        retry_count=0,
        feedback="all gates passed",
    )
    results = ledger.get_wave_results("s1")
    assert len(results) == 1
    assert results[0]["passed"] == 1
    assert results[0]["verifier_score"] == pytest.approx(0.85)


def test_get_convergence_session_returns_none_for_unknown(tmp_path):
    ledger = Ledger(tmp_path / "test.db")
    assert ledger.get_convergence_session("nonexistent") is None
