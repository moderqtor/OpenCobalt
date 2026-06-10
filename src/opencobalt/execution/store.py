"""SQLite persistence for execution plans, results, artifacts, and receipts.

Lives in the same ledger database as the rest of OpenCobalt state. Tables
are created with CREATE TABLE IF NOT EXISTS so existing databases are never
broken. JSON columns are used where relational depth is not needed in v0.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import (
    ExecutionArtifact,
    ExecutionPlan,
    ExecutionResult,
    ExecutionStep,
    WorkReceipt,
)

_DEFAULT_DB = Path(".opencobalt") / "ledger.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_plans (
    plan_id           TEXT PRIMARY KEY,
    task              TEXT NOT NULL,
    runtime           TEXT NOT NULL,
    model_policy      TEXT,
    cwd               TEXT,
    risk_level        TEXT NOT NULL,
    approval_required INTEGER NOT NULL,
    steps_json        TEXT NOT NULL,
    dry_run           INTEGER NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_results (
    execution_id      TEXT PRIMARY KEY,
    plan_id           TEXT NOT NULL,
    step_id           TEXT,
    runtime           TEXT NOT NULL,
    command_argv_json TEXT NOT NULL,
    cwd               TEXT,
    return_code       INTEGER,
    stdout_path       TEXT,
    stderr_path       TEXT,
    stdout_preview    TEXT,
    stderr_preview    TEXT,
    started_at        TEXT,
    finished_at       TEXT,
    duration_ms       INTEGER,
    status            TEXT NOT NULL,
    error             TEXT
);

CREATE TABLE IF NOT EXISTS execution_artifacts (
    artifact_id    TEXT PRIMARY KEY,
    session_id     TEXT,
    plan_id        TEXT,
    execution_id   TEXT,
    source_runtime TEXT NOT NULL,
    artifact_type  TEXT NOT NULL,
    path           TEXT NOT NULL,
    sha256         TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    summary        TEXT,
    metadata_json  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS work_receipts (
    receipt_id                 TEXT PRIMARY KEY,
    plan_id                    TEXT NOT NULL,
    execution_id               TEXT,
    task                       TEXT NOT NULL,
    selected_runtime           TEXT NOT NULL,
    route_reason               TEXT,
    risk_level                 TEXT NOT NULL,
    approval_required          INTEGER NOT NULL,
    capabilities_snapshot_json TEXT NOT NULL DEFAULT '{}',
    command_plan_json          TEXT NOT NULL DEFAULT '[]',
    artifact_ids_json          TEXT NOT NULL DEFAULT '[]',
    verification_status        TEXT NOT NULL DEFAULT 'unverified',
    created_at                 TEXT NOT NULL
);
"""


class ExecutionStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or _DEFAULT_DB).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- Plans ---

    def save_plan(self, plan: ExecutionPlan) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO execution_plans VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    plan.plan_id,
                    plan.task,
                    plan.runtime,
                    plan.model_policy,
                    plan.cwd,
                    plan.risk_level,
                    int(plan.approval_required),
                    json.dumps([s.model_dump(mode="json") for s in plan.steps]),
                    int(plan.dry_run),
                    plan.created_at.isoformat(),
                ),
            )

    def get_plan(self, plan_id: str) -> ExecutionPlan | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
        return _decode_plan(row) if row else None

    def list_plans(self, *, limit: int = 50) -> list[ExecutionPlan]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM execution_plans ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_decode_plan(r) for r in rows]

    # --- Results ---

    def save_result(self, result: ExecutionResult) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO execution_results "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    result.execution_id,
                    result.plan_id,
                    result.step_id,
                    result.runtime,
                    json.dumps(result.command_argv),
                    result.cwd,
                    result.return_code,
                    result.stdout_path,
                    result.stderr_path,
                    result.stdout_preview,
                    result.stderr_preview,
                    result.started_at.isoformat() if result.started_at else None,
                    result.finished_at.isoformat() if result.finished_at else None,
                    result.duration_ms,
                    result.status,
                    result.error,
                ),
            )

    def get_result(self, execution_id: str) -> ExecutionResult | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_results WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        return _decode_result(row) if row else None

    # --- Artifacts ---

    def save_artifact(self, artifact: ExecutionArtifact) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO execution_artifacts "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    artifact.artifact_id,
                    artifact.session_id,
                    artifact.plan_id,
                    artifact.execution_id,
                    artifact.source_runtime,
                    artifact.artifact_type,
                    artifact.path,
                    artifact.sha256,
                    artifact.size_bytes,
                    artifact.created_at.isoformat(),
                    artifact.summary,
                    json.dumps(artifact.metadata),
                ),
            )

    def get_artifact(self, artifact_id: str) -> ExecutionArtifact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return _decode_artifact(row) if row else None

    def list_artifacts(
        self,
        *,
        plan_id: str | None = None,
        execution_id: str | None = None,
        artifact_type: str | None = None,
        limit: int = 50,
    ) -> list[ExecutionArtifact]:
        sql = "SELECT * FROM execution_artifacts WHERE 1=1"
        params: list[str | int] = []
        if plan_id:
            sql += " AND plan_id = ?"
            params.append(plan_id)
        if execution_id:
            sql += " AND execution_id = ?"
            params.append(execution_id)
        if artifact_type:
            sql += " AND artifact_type = ?"
            params.append(artifact_type)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_decode_artifact(r) for r in rows]

    # --- Receipts ---

    def save_receipt(self, receipt: WorkReceipt) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO work_receipts "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    receipt.receipt_id,
                    receipt.plan_id,
                    receipt.execution_id,
                    receipt.task,
                    receipt.selected_runtime,
                    receipt.route_reason,
                    receipt.risk_level,
                    int(receipt.approval_required),
                    json.dumps(receipt.capabilities_snapshot),
                    json.dumps(receipt.command_plan),
                    json.dumps(receipt.artifact_ids),
                    receipt.verification_status,
                    receipt.created_at.isoformat(),
                ),
            )

    def get_receipt(self, receipt_id: str) -> WorkReceipt | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM work_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()
        return _decode_receipt(row) if row else None

    def list_receipts(
        self,
        *,
        runtime: str | None = None,
        verification_status: str | None = None,
        limit: int = 50,
    ) -> list[WorkReceipt]:
        sql = "SELECT * FROM work_receipts WHERE 1=1"
        params: list[str | int] = []
        if runtime:
            sql += " AND selected_runtime = ?"
            params.append(runtime)
        if verification_status:
            sql += " AND verification_status = ?"
            params.append(verification_status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_decode_receipt(r) for r in rows]

    def set_receipt_verification(self, receipt_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE work_receipts SET verification_status = ? WHERE receipt_id = ?",
                (status, receipt_id),
            )


def _decode_plan(row: sqlite3.Row) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id=row["plan_id"],
        task=row["task"],
        runtime=row["runtime"],
        model_policy=row["model_policy"],
        cwd=row["cwd"],
        risk_level=row["risk_level"],
        approval_required=bool(row["approval_required"]),
        steps=[ExecutionStep(**s) for s in json.loads(row["steps_json"])],
        dry_run=bool(row["dry_run"]),
        created_at=row["created_at"],
    )


def _decode_result(row: sqlite3.Row) -> ExecutionResult:
    return ExecutionResult(
        execution_id=row["execution_id"],
        plan_id=row["plan_id"],
        step_id=row["step_id"],
        runtime=row["runtime"],
        command_argv=json.loads(row["command_argv_json"]),
        cwd=row["cwd"],
        return_code=row["return_code"],
        stdout_path=row["stdout_path"],
        stderr_path=row["stderr_path"],
        stdout_preview=row["stdout_preview"] or "",
        stderr_preview=row["stderr_preview"] or "",
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=row["duration_ms"],
        status=row["status"],
        error=row["error"],
    )


def _decode_artifact(row: sqlite3.Row) -> ExecutionArtifact:
    return ExecutionArtifact(
        artifact_id=row["artifact_id"],
        session_id=row["session_id"],
        plan_id=row["plan_id"],
        execution_id=row["execution_id"],
        source_runtime=row["source_runtime"],
        artifact_type=row["artifact_type"],
        path=row["path"],
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        created_at=row["created_at"],
        summary=row["summary"],
        metadata=json.loads(row["metadata_json"]),
    )


def _decode_receipt(row: sqlite3.Row) -> WorkReceipt:
    return WorkReceipt(
        receipt_id=row["receipt_id"],
        plan_id=row["plan_id"],
        execution_id=row["execution_id"],
        task=row["task"],
        selected_runtime=row["selected_runtime"],
        route_reason=row["route_reason"],
        risk_level=row["risk_level"],
        approval_required=bool(row["approval_required"]),
        capabilities_snapshot=json.loads(row["capabilities_snapshot_json"]),
        command_plan=json.loads(row["command_plan_json"]),
        artifact_ids=json.loads(row["artifact_ids_json"]),
        verification_status=row["verification_status"],
        created_at=row["created_at"],
    )
