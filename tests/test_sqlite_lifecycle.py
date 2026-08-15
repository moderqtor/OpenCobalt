"""SQLite connection ownership: connections must close, not leak FDs."""

from __future__ import annotations

import sqlite3

import pytest

from opencobalt.core.sqlite import closing_sqlite
from opencobalt.personal_ai.store import PersonalAIStore


def test_closing_sqlite_closes_the_connection(tmp_path):
    path = tmp_path / "owned.db"
    with closing_sqlite(path) as conn:
        conn.execute("CREATE TABLE t (id INTEGER)")
        leaked = conn
    with pytest.raises(sqlite3.ProgrammingError):
        leaked.execute("SELECT 1")


def test_personal_ai_store_does_not_leave_a_live_handle(tmp_path):
    store = PersonalAIStore(tmp_path / "ledger.db")
    conversation = store.create_conversation(title="FD")
    assert conversation.title == "FD"
    with store._connect() as conn:
        raw = conn
    with pytest.raises(sqlite3.ProgrammingError):
        raw.execute("SELECT 1")
