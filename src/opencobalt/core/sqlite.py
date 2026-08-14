"""SQLite connection ownership.

Callers historically used ``with sqlite3.connect(...)`` / ``with self._connect()``.
``sqlite3.Connection`` as a context manager commits or rolls back; it does not
close the connection. Each store operation therefore leaked a file descriptor
until GC, which on macOS at the default soft limit produced EMFILE and then
``unable to open database file``.

This helper commits on success, rolls back on error, and always closes.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def closing_sqlite(
    path: Path | str,
    *,
    timeout: float = 5.0,
    foreign_keys: bool = False,
    busy_timeout_ms: int | None = None,
) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(path), timeout=timeout)
    try:
        conn.row_factory = sqlite3.Row
        if foreign_keys:
            conn.execute("PRAGMA foreign_keys = ON")
        if busy_timeout_ms is not None:
            conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
