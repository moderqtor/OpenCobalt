"""SQLite-backed ledger. Source of truth for all OpenCobalt state.

Uses stdlib sqlite3 only. No ORM. Schema is append-mostly.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import (
    MemoryRecord,
    MultiRouteDecision,
    RouteDecision,
    SessionEvent,
    SubTask,
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

CREATE TABLE IF NOT EXISTS outcomes (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    tool        TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS multi_route_decisions (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    task        TEXT NOT NULL,
    subtasks    TEXT NOT NULL DEFAULT '[]',
    tools_used  TEXT NOT NULL DEFAULT '[]',
    result_id   TEXT NOT NULL DEFAULT '',
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS autonomy_runs (
    id              TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,
    seed_goal       TEXT NOT NULL,
    profile         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    allowed_actions TEXT NOT NULL DEFAULT '[]',
    denied_actions  TEXT NOT NULL DEFAULT '[]',
    metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS autonomy_tasks (
    id                 TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL,
    timestamp          TEXT NOT NULL,
    prompt             TEXT NOT NULL,
    task_type          TEXT NOT NULL,
    preferred_tool     TEXT,
    preferred_subagent TEXT,
    priority           INTEGER NOT NULL DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'queued',
    artifact_ids       TEXT NOT NULL DEFAULT '[]',
    metadata           TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (run_id) REFERENCES autonomy_runs(id)
);

CREATE TABLE IF NOT EXISTS usage_observations (
    id          TEXT PRIMARY KEY,
    run_id      TEXT,
    timestamp   TEXT NOT NULL,
    tool        TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    task_type   TEXT NOT NULL,
    latency_ms  INTEGER,
    success     INTEGER,
    message     TEXT NOT NULL DEFAULT '',
    metadata    TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (run_id) REFERENCES autonomy_runs(id)
);
"""


class Ledger:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or _DEFAULT_DB).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._create_convergence_tables()

    def _connect(self):
        from opencobalt.core.sqlite import closing_sqlite

        return closing_sqlite(self.db_path)

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

    # --- Autonomy runs ---

    def create_autonomy_run(
        self,
        seed_goal: str,
        *,
        profile: str = "balanced",
        allowed_actions: list[str] | None = None,
        denied_actions: list[str] | None = None,
        status: str = "queued",
        metadata: dict | None = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO autonomy_runs VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    _utc_now(),
                    seed_goal,
                    profile,
                    status,
                    json.dumps(allowed_actions or []),
                    json.dumps(denied_actions or []),
                    json.dumps(metadata or {}),
                ),
            )
        return run_id

    def get_autonomy_run(self, run_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM autonomy_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        return _decode_autonomy_run(row) if row else None

    # --- Autonomy tasks ---

    def add_autonomy_task(
        self,
        *,
        run_id: str,
        prompt: str,
        task_type: str,
        preferred_tool: str | None = None,
        preferred_subagent: str | None = None,
        priority: int = 0,
        status: str = "queued",
        artifact_ids: list[str] | None = None,
        metadata: dict | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO autonomy_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    task_id,
                    run_id,
                    _utc_now(),
                    prompt,
                    task_type,
                    preferred_tool,
                    preferred_subagent,
                    priority,
                    status,
                    json.dumps(artifact_ids or []),
                    json.dumps(metadata or {}),
                ),
            )
        return task_id

    def update_autonomy_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        artifact_ids: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[str] = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if artifact_ids is not None:
            fields.append("artifact_ids = ?")
            params.append(json.dumps(artifact_ids))
        if metadata is not None:
            fields.append("metadata = ?")
            params.append(json.dumps(metadata))
        if not fields:
            return
        params.append(task_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE autonomy_tasks SET {', '.join(fields)} WHERE id = ?",
                params,
            )

    def list_autonomy_tasks(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM autonomy_tasks WHERE run_id = ? ORDER BY priority DESC, timestamp",
                (run_id,),
            ).fetchall()
        return [_decode_autonomy_task(row) for row in rows]

    # --- Usage observations ---

    def insert_usage_observation(
        self,
        *,
        run_id: str | None = None,
        tool: str,
        event_type: str,
        task_type: str,
        latency_ms: int | None,
        success: bool | None,
        message: str = "",
        metadata: dict | None = None,
    ) -> str:
        observation_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO usage_observations VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    observation_id,
                    run_id,
                    _utc_now(),
                    tool,
                    event_type,
                    task_type,
                    latency_ms,
                    None if success is None else int(success),
                    message,
                    json.dumps(metadata or {}),
                ),
            )
        return observation_id

    def list_usage_observations(
        self,
        run_id: str | None = None,
        *,
        tool: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT * FROM usage_observations WHERE 1=1"
        params: list[str | int] = []
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if tool is not None:
            sql += " AND tool = ?"
            params.append(tool)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_decode_usage_observation(row) for row in rows]

    # --- Outcomes ---

    def insert_outcome(
        self,
        task_id: str,
        tool: str,
        outcome: str,
        metadata: dict | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    _utc_now(),
                    task_id,
                    tool,
                    outcome,
                    json.dumps(metadata or {}),
                ),
            )

    def list_outcomes(self, *, limit: int = 100, tool: str | None = None) -> list[dict]:
        sql = "SELECT * FROM outcomes"
        params: list[str | int] = []
        if tool:
            sql += " WHERE tool = ?"
            params.append(tool)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # --- Multi-route decisions ---

    def insert_multi_route_decision(self, decision: MultiRouteDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO multi_route_decisions VALUES (?,?,?,?,?,?,?)",
                (
                    decision.id,
                    decision.timestamp.isoformat(),
                    decision.task,
                    json.dumps([st.model_dump() for st in decision.subtasks]),
                    json.dumps(decision.tools_used),
                    decision.result_id,
                    json.dumps(decision.metadata),
                ),
            )

    def list_multi_route_decisions(self, *, limit: int = 20) -> list[MultiRouteDecision]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM multi_route_decisions ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        results = []
        for r in rows:
            subtasks = [SubTask(**s) for s in json.loads(r["subtasks"])]
            results.append(
                MultiRouteDecision(
                    id=r["id"],
                    timestamp=r["timestamp"],
                    task=r["task"],
                    subtasks=subtasks,
                    tools_used=json.loads(r["tools_used"]),
                    result_id=r["result_id"],
                    metadata=json.loads(r["metadata"]),
                )
            )
        return results

    # --- Convergence tables ---

    _CONVERGENCE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS convergence_sessions (
        id TEXT PRIMARY KEY,
        seed_task TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        started_at REAL NOT NULL,
        finished_at REAL,
        total_waves INTEGER NOT NULL DEFAULT 0,
        total_retries INTEGER NOT NULL DEFAULT 0,
        commit_sha TEXT,
        log_path TEXT
    );
    CREATE TABLE IF NOT EXISTS convergence_wave_results (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        wave INTEGER NOT NULL,
        tests_ok INTEGER,
        verifier_score REAL,
        verifier_ok INTEGER,
        passed INTEGER NOT NULL DEFAULT 0,
        retry_count INTEGER NOT NULL DEFAULT 0,
        feedback TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (session_id) REFERENCES convergence_sessions(id)
    );
    """

    def _create_convergence_tables(self) -> None:
        with self._connect() as conn:
            conn.executescript(self._CONVERGENCE_SCHEMA)

    def upsert_convergence_session(
        self,
        session_id: str,
        seed_task: str,
        status: str,
        started_at: float,
        finished_at: float | None,
        total_waves: int,
        total_retries: int,
        commit_sha: str | None,
        log_path: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO convergence_sessions "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    session_id, seed_task, status, started_at,
                    finished_at, total_waves, total_retries,
                    commit_sha, log_path,
                ),
            )

    def get_convergence_session(self, session_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM convergence_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_convergence_sessions(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM convergence_sessions "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def insert_wave_result(
        self,
        session_id: str,
        wave: int,
        tests_ok: bool | None,
        verifier_score: float | None,
        verifier_ok: bool | None,
        passed: bool,
        retry_count: int,
        feedback: str,
    ) -> None:
        import uuid as _uuid
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO convergence_wave_results VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    str(_uuid.uuid4()),
                    session_id,
                    wave,
                    None if tests_ok is None else int(tests_ok),
                    verifier_score,
                    None if verifier_ok is None else int(verifier_ok),
                    int(passed),
                    retry_count,
                    feedback,
                ),
            )

    def get_wave_results(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM convergence_wave_results "
                "WHERE session_id = ? ORDER BY wave, retry_count",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _decode_autonomy_run(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["allowed_actions"] = json.loads(result["allowed_actions"])
    result["denied_actions"] = json.loads(result["denied_actions"])
    result["metadata"] = json.loads(result["metadata"])
    return result


def _decode_autonomy_task(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["artifact_ids"] = json.loads(result["artifact_ids"])
    result["metadata"] = json.loads(result["metadata"])
    return result


def _decode_usage_observation(row: sqlite3.Row) -> dict:
    result = dict(row)
    if result["success"] is not None:
        result["success"] = bool(result["success"])
    result["metadata"] = json.loads(result["metadata"])
    return result
