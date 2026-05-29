"""SQLite-backed ledger. Source of truth for all OpenCobalt state.

Uses stdlib sqlite3 only. No ORM. Schema is append-mostly.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import (
    MemoryRecord,
    RouteDecision,
    SessionEvent,
    VerificationResult,
)

_DEFAULT_DB = Path(".opencobalt") / "ledger.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    project     TEXT NOT NULL,
    source      TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    summary     TEXT NOT NULL,
    raw_ref     TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS verification_results (
    id             TEXT PRIMARY KEY,
    timestamp      TEXT NOT NULL,
    command        TEXT NOT NULL,
    exit_code      INTEGER NOT NULL,
    passed         INTEGER NOT NULL,
    output_summary TEXT NOT NULL,
    metadata       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS route_decisions (
    id               TEXT PRIMARY KEY,
    timestamp        TEXT NOT NULL,
    task             TEXT NOT NULL,
    recommended_tool TEXT NOT NULL,
    score            INTEGER NOT NULL,
    reasoning        TEXT NOT NULL,
    tier             TEXT NOT NULL,
    metadata         TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS memory_records (
    id        TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    project   TEXT NOT NULL,
    namespace TEXT NOT NULL,
    content   TEXT NOT NULL,
    source    TEXT NOT NULL,
    metadata  TEXT NOT NULL DEFAULT '{}'
);
"""


class Ledger:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or _DEFAULT_DB).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # --- Events ---

    def insert_event(self, event: SessionEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?)",
                (
                    event.id,
                    event.timestamp.isoformat(),
                    event.project,
                    event.source,
                    event.event_type,
                    event.summary,
                    event.raw_ref,
                    json.dumps(event.metadata),
                ),
            )

    def list_events(self, *, limit: int = 50, project: str | None = None) -> list[SessionEvent]:
        sql = "SELECT * FROM events"
        params: list[str | int] = []
        if project:
            sql += " WHERE project = ?"
            params.append(project)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            SessionEvent(
                id=r["id"],
                timestamp=r["timestamp"],
                project=r["project"],
                source=r["source"],
                event_type=r["event_type"],
                summary=r["summary"],
                raw_ref=r["raw_ref"],
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]

    def count_events(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    # --- Verification results ---

    def insert_verification_result(self, result: VerificationResult) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO verification_results VALUES (?,?,?,?,?,?,?)",
                (
                    result.id,
                    result.timestamp.isoformat(),
                    result.command,
                    result.exit_code,
                    int(result.passed),
                    result.output_summary,
                    json.dumps(result.metadata),
                ),
            )

    def list_verification_results(self, *, limit: int = 20) -> list[VerificationResult]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM verification_results ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            VerificationResult(
                id=r["id"],
                timestamp=r["timestamp"],
                command=r["command"],
                exit_code=r["exit_code"],
                passed=bool(r["passed"]),
                output_summary=r["output_summary"],
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]

    # --- Route decisions ---

    def insert_route_decision(self, decision: RouteDecision) -> None:
        meta = {**decision.metadata, "_scores": decision.scores}
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO route_decisions VALUES (?,?,?,?,?,?,?,?)",
                (
                    decision.id,
                    decision.timestamp.isoformat(),
                    decision.task,
                    decision.recommended_tool,
                    decision.score,
                    decision.reasoning,
                    decision.tier,
                    json.dumps(meta),
                ),
            )

    def list_route_decisions(self, *, limit: int = 20) -> list[RouteDecision]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM route_decisions ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            RouteDecision(
                id=r["id"],
                timestamp=r["timestamp"],
                task=r["task"],
                recommended_tool=r["recommended_tool"],
                score=r["score"],
                reasoning=r["reasoning"],
                tier=r["tier"],
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]

    # --- Memory records ---

    def insert_memory_record(self, record: MemoryRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO memory_records VALUES (?,?,?,?,?,?,?)",
                (
                    record.id,
                    record.timestamp.isoformat(),
                    record.project,
                    record.namespace,
                    record.content,
                    record.source,
                    json.dumps(record.metadata),
                ),
            )

    def list_memory_records(
        self, *, project: str | None = None, namespace: str | None = None, limit: int = 100
    ) -> list[MemoryRecord]:
        sql = "SELECT * FROM memory_records WHERE 1=1"
        params: list[str | int] = []
        if project:
            sql += " AND project = ?"
            params.append(project)
        if namespace:
            sql += " AND namespace = ?"
            params.append(namespace)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            MemoryRecord(
                id=r["id"],
                timestamp=r["timestamp"],
                project=r["project"],
                namespace=r["namespace"],
                content=r["content"],
                source=r["source"],
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]

    def count_memory_records(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0]
