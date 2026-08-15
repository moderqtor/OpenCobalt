"""MemoryBridge: SQLite-backed cross-session agent memory store.

mem0 requires an LLM + vector store backend (no SQLite support); using SQLite
directly for local-first consistency with the rest of OpenCobalt.
Attempts `from mem0 import Memory` at import time -- if unavailable, all
methods become no-ops with a one-time warning.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from mem0 import Memory as _Mem0Memory  # noqa: F401

    _MEM0_AVAILABLE = True
except ImportError:
    _MEM0_AVAILABLE = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id         TEXT PRIMARY KEY,
    timestamp  TEXT NOT NULL,
    content    TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    metadata   TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories (agent_id);
CREATE INDEX IF NOT EXISTS idx_memories_session ON memories (session_id);
"""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class MemoryBridge:
    """Persist and retrieve agent memories across sessions.

    Primary backend: SQLite at .opencobalt/memories.db.
    mem0 is imported if available; its absence only produces a one-time log warning
    -- all methods remain functional via the SQLite path.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = Path(".opencobalt") / "memories.db"
        self._db_path = Path(db_path).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        if not _MEM0_AVAILABLE:
            logger.warning("memory bridge: mem0 not installed -- running on SQLite-only path")
        logger.info("memory bridge: initialized")

    def _connect(self):
        from opencobalt.core.sqlite import closing_sqlite

        return closing_sqlite(self._db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def add(
        self,
        content: str,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> str:
        """Persist a memory and return its UUID."""
        memory_id = str(uuid.uuid4())
        meta_json = json.dumps(metadata or {})
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories (id, timestamp, content, agent_id, session_id, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (memory_id, _now_iso(), content, agent_id, session_id, meta_json),
            )
        return memory_id

    def search(self, query: str, agent_id: str = "", limit: int = 5) -> list[dict]:
        """Return up to `limit` memories whose content contains `query` (case-insensitive)."""
        terms = [f"%{t}%" for t in query.split() if t]
        if not terms:
            return []
        clauses = " AND ".join("content LIKE ?" for _ in terms)
        params: list[Any] = terms
        if agent_id:
            clauses += " AND agent_id = ?"
            params.append(agent_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM memories WHERE {clauses} ORDER BY timestamp DESC LIMIT ?",
                params + [limit],
            ).fetchall()
        return [dict(row) for row in rows]

    def get_session_memories(self, session_id: str) -> list[dict]:
        """Return all memories tagged with the given session_id."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE session_id = ? ORDER BY timestamp ASC",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_session_summary(self, session_id: str, summary: str, agent_id: str) -> str:
        """Store a session summary as a memory tagged with session_id."""
        return self.add(
            content=summary,
            agent_id=agent_id,
            session_id=session_id,
            metadata={"type": "session_summary"},
        )

    def count(self) -> int:
        """Return total number of stored memories."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
        return row["n"] if row else 0

    def recent(self, limit: int = 10) -> list[dict]:
        """Return the most recent memories across all agents."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
