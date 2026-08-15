"""Simple key-value config store backed by the SQLite ledger."""
from __future__ import annotations

from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

class Config:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        from opencobalt.core.sqlite import closing_sqlite

        with closing_sqlite(self.db_path) as conn:
            conn.executescript(_SCHEMA)

    def _connect(self):
        from opencobalt.core.sqlite import closing_sqlite

        return closing_sqlite(self.db_path)

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (key, value))

    def delete(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM config WHERE key=?", (key,))

    def list_all(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM config ORDER BY key").fetchall()
        return {r["key"]: r["value"] for r in rows}


def get_db_path() -> Path:
    """Return canonical path to SQLite ledger.db."""
    return Path(".opencobalt") / "ledger.db"
