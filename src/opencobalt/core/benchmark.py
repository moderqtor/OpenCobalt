"""Agent benchmarking store for OpenCobalt.

Records individual task results per agent, computes composite leaderboard
scores, and exposes a task-type-level best-agent lookup for eventual
router integration.

Composite score formula:
    composite = (win_rate * 0.6) + (speed_score * 0.4)
where speed_score = min(1000 / avg_latency_ms, 10.0)
-- a 1000 ms average yields speed_score = 1.0; lower latency scores higher.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


@dataclass
class BenchmarkRecord:
    agent_id: str
    task_id: str
    task_type: str
    latency_ms: int
    success: bool
    model_used: str
    tier: str
    score: float
    id: str = field(default_factory=_uid)
    timestamp: str = field(default_factory=_now_iso)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_records (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    task_type   TEXT NOT NULL,
    latency_ms  INTEGER NOT NULL,
    success     INTEGER NOT NULL,
    model_used  TEXT NOT NULL,
    tier        TEXT NOT NULL,
    score       REAL NOT NULL
);
"""


class BenchmarkStore:
    """SQLite-backed store for agent benchmark records.

    Uses a separate benchmark_records table so it can share the ledger DB
    without touching existing tables.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def record(self, result: BenchmarkRecord) -> None:
        """Persist a single benchmark result."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO benchmark_records VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    result.id,
                    result.timestamp,
                    result.agent_id,
                    result.task_id,
                    result.task_type,
                    result.latency_ms,
                    int(result.success),
                    result.model_used,
                    result.tier,
                    result.score,
                ),
            )

    def get_leaderboard(self, n: int = 10) -> list[dict]:
        """Return top n agents ranked by composite score (win_rate + speed)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    agent_id,
                    COUNT(*)        AS total,
                    SUM(success)    AS wins,
                    AVG(latency_ms) AS avg_latency
                FROM benchmark_records
                GROUP BY agent_id
                """
            ).fetchall()

        results = []
        for row in rows:
            win_rate = row["wins"] / row["total"] if row["total"] > 0 else 0.0
            avg_latency = row["avg_latency"] or 1.0
            speed_score = min(1000.0 / avg_latency, 10.0)
            composite = round((win_rate * 0.6) + (speed_score * 0.4), 4)
            results.append(
                {
                    "agent_id": row["agent_id"],
                    "total": row["total"],
                    "win_rate": round(win_rate, 4),
                    "avg_latency_ms": round(avg_latency, 1),
                    "composite_score": composite,
                }
            )

        results.sort(key=lambda r: r["composite_score"], reverse=True)
        return results[:n]

    def get_agent_stats(self, agent_id: str) -> dict | None:
        """Return aggregate stats for a single agent, or None if not found."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    agent_id,
                    COUNT(*)        AS total,
                    SUM(success)    AS wins,
                    AVG(latency_ms) AS avg_latency,
                    MIN(latency_ms) AS min_latency,
                    MAX(latency_ms) AS max_latency
                FROM benchmark_records
                WHERE agent_id = ?
                GROUP BY agent_id
                """,
                (agent_id,),
            ).fetchone()

        if row is None:
            return None

        win_rate = row["wins"] / row["total"] if row["total"] > 0 else 0.0
        return {
            "agent_id": row["agent_id"],
            "total": row["total"],
            "wins": row["wins"],
            "win_rate": round(win_rate, 4),
            "avg_latency_ms": round(row["avg_latency"] or 0.0, 1),
            "min_latency_ms": row["min_latency"],
            "max_latency_ms": row["max_latency"],
        }

    def list_recent(self, limit: int = 50) -> list[dict]:
        """Return the most recent benchmark records as plain dicts."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM benchmark_records ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_best_for_task_type(self, task_type: str) -> str | None:
        """Return the agent_id with best composite score for a given task type.

        Returns None if no records exist for that task type. The router calls
        this to auto-assign tasks once benchmark data accumulates.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    agent_id,
                    COUNT(*)        AS total,
                    SUM(success)    AS wins,
                    AVG(latency_ms) AS avg_latency
                FROM benchmark_records
                WHERE task_type = ?
                GROUP BY agent_id
                """,
                (task_type,),
            ).fetchall()

        if not rows:
            return None

        best_agent: str | None = None
        best_score = -1.0
        for row in rows:
            win_rate = row["wins"] / row["total"] if row["total"] > 0 else 0.0
            avg_latency = row["avg_latency"] or 1.0
            speed_score = min(1000.0 / avg_latency, 10.0)
            composite = (win_rate * 0.6) + (speed_score * 0.4)
            if composite > best_score:
                best_score = composite
                best_agent = row["agent_id"]

        return best_agent
