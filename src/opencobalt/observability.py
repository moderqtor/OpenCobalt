"""ObservabilitySession: SQLite-backed agent run tracking.

agentops requires a cloud API key and remote dashboard; implementing
directly on SQLite to keep observability local-first and offline.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS obs_sessions (
    id          TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    agent_id    TEXT NOT NULL,
    task        TEXT NOT NULL,
    model       TEXT NOT NULL,
    success     INTEGER,
    cost_usd    REAL
);
CREATE TABLE IF NOT EXISTS obs_tool_calls (
    id             TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    tool_name      TEXT NOT NULL,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    latency_ms     INTEGER NOT NULL DEFAULT 0
);
"""


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


@dataclass
class SessionReport:
    session_id: str
    agent_id: str
    task: str
    model: str
    started_at: str
    ended_at: str | None
    success: bool | None
    cost_usd: float | None
    tool_calls: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "task": self.task,
            "model": self.model,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "success": self.success,
            "cost_usd": self.cost_usd,
            "tool_calls": self.tool_calls,
        }


class ObservabilitySession:
    """Track agent sessions and tool calls in a local SQLite store."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = Path(".opencobalt") / "observability.db"
        self._db_path = Path(db_path).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def start_session(self, agent_id: str, task: str, model: str) -> str:
        """Open a new observability session and return its session_id."""
        session_id = _uid()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO obs_sessions (id, started_at, agent_id, task, model) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, _now_iso(), agent_id, task, model),
            )
        return session_id

    def record_tool_call(
        self,
        session_id: str,
        tool_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
    ) -> None:
        """Append a tool-call record to the session."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO obs_tool_calls "
                "(id, session_id, timestamp, tool_name, input_tokens, output_tokens, latency_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_uid(), session_id, _now_iso(), tool_name, input_tokens, output_tokens, latency_ms),
            )

    def end_session(self, session_id: str, success: bool, cost: float = 0.0) -> None:
        """Close the session with a success flag and optional cost."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE obs_sessions SET ended_at = ?, success = ?, cost_usd = ? WHERE id = ?",
                (_now_iso(), int(success), cost, session_id),
            )

    def get_session_report(self, session_id: str) -> dict | None:
        """Return a full session report dict, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM obs_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            calls = conn.execute(
                "SELECT * FROM obs_tool_calls WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            ).fetchall()

        report = SessionReport(
            session_id=row["id"],
            agent_id=row["agent_id"],
            task=row["task"],
            model=row["model"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            success=bool(row["success"]) if row["success"] is not None else None,
            cost_usd=row["cost_usd"],
            tool_calls=[dict(c) for c in calls],
        )
        return report.to_dict()

    def count_sessions(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM obs_sessions").fetchone()
        return row["n"] if row else 0

    def recent_sessions(self, limit: int = 10) -> list[dict]:
        """Return the most recent sessions, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM obs_sessions ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def summary_stats(self) -> dict:
        """Return aggregate stats: total sessions, success rate, avg cost."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*)            AS total,
                    SUM(success)        AS successes,
                    AVG(cost_usd)       AS avg_cost,
                    SUM(cost_usd)       AS total_cost
                FROM obs_sessions
                WHERE ended_at IS NOT NULL
                """
            ).fetchone()
        if row is None or row["total"] == 0:
            return {"total": 0, "success_rate": 0.0, "avg_cost_usd": 0.0, "total_cost_usd": 0.0}
        total = row["total"]
        successes = row["successes"] or 0
        return {
            "total": total,
            "success_rate": round(successes / total, 4),
            "avg_cost_usd": round(row["avg_cost"] or 0.0, 6),
            "total_cost_usd": round(row["total_cost"] or 0.0, 6),
        }
