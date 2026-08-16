"""SQLite persistence for durable agent-broker sessions and turns."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import AgentBrokerSession, AgentBrokerTurn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_broker_sessions (
    session_id          TEXT PRIMARY KEY,
    runtime             TEXT NOT NULL,
    provider_session_id TEXT,
    objective           TEXT NOT NULL,
    repository_path     TEXT NOT NULL,
    workspace_id        TEXT NOT NULL,
    workspace_path      TEXT NOT NULL,
    source_branch       TEXT,
    starting_head       TEXT,
    model               TEXT,
    status              TEXT NOT NULL,
    turn_count          INTEGER NOT NULL DEFAULT 0,
    last_prompt         TEXT,
    last_response       TEXT,
    last_receipt_id     TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    metadata_json       TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_agent_broker_sessions_updated
ON agent_broker_sessions (updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_broker_turns (
    turn_id             TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    sequence            INTEGER NOT NULL CHECK (sequence > 0),
    prompt              TEXT NOT NULL,
    response            TEXT NOT NULL DEFAULT '',
    provider_session_id TEXT,
    receipt_id          TEXT,
    status              TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    UNIQUE (session_id, sequence),
    FOREIGN KEY (session_id) REFERENCES agent_broker_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_broker_turns_session
ON agent_broker_turns (session_id, sequence);
"""


class AgentBrokerStore:
    """Additive broker persistence in the shared OpenCobalt ledger."""

    def __init__(self, db_path: str | Path = Path(".opencobalt") / "ledger.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def save_session(self, session: AgentBrokerSession) -> AgentBrokerSession:
        payload = session.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_broker_sessions (
                    session_id, runtime, provider_session_id, objective,
                    repository_path, workspace_id, workspace_path, source_branch,
                    starting_head, model, status, turn_count, last_prompt,
                    last_response, last_receipt_id, created_at, updated_at,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    runtime=excluded.runtime,
                    provider_session_id=excluded.provider_session_id,
                    objective=excluded.objective,
                    repository_path=excluded.repository_path,
                    workspace_id=excluded.workspace_id,
                    workspace_path=excluded.workspace_path,
                    source_branch=excluded.source_branch,
                    starting_head=excluded.starting_head,
                    model=excluded.model,
                    status=excluded.status,
                    turn_count=excluded.turn_count,
                    last_prompt=excluded.last_prompt,
                    last_response=excluded.last_response,
                    last_receipt_id=excluded.last_receipt_id,
                    updated_at=excluded.updated_at,
                    metadata_json=excluded.metadata_json
                """,
                (
                    payload["session_id"], payload["runtime"], payload["provider_session_id"],
                    payload["objective"], payload["repository_path"], payload["workspace_id"],
                    payload["workspace_path"], payload["source_branch"], payload["starting_head"],
                    payload["model"], payload["status"], payload["turn_count"],
                    payload["last_prompt"], payload["last_response"], payload["last_receipt_id"],
                    payload["created_at"], payload["updated_at"], json.dumps(payload["metadata"], sort_keys=True),
                ),
            )
        return session

    def get_session(self, session_id: str) -> AgentBrokerSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_broker_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._session_from_row(row) if row else None

    def list_sessions(self, *, limit: int = 50) -> list[AgentBrokerSession]:
        bounded = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_broker_sessions ORDER BY updated_at DESC LIMIT ?", (bounded,)
            ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def save_turn(self, turn: AgentBrokerTurn) -> AgentBrokerTurn:
        payload = turn.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO agent_broker_turns (
                    turn_id, session_id, sequence, prompt, response,
                    provider_session_id, receipt_id, status, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["turn_id"], payload["session_id"], payload["sequence"],
                    payload["prompt"], payload["response"], payload["provider_session_id"],
                    payload["receipt_id"], payload["status"], payload["created_at"],
                    json.dumps(payload["metadata"], sort_keys=True),
                ),
            )
        return turn

    def list_turns(self, session_id: str) -> list[AgentBrokerTurn]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_broker_turns WHERE session_id = ? ORDER BY sequence",
                (session_id,),
            ).fetchall()
        return [self._turn_from_row(row) for row in rows]

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> AgentBrokerSession:
        return AgentBrokerSession.model_validate({
            "session_id": row["session_id"],
            "runtime": row["runtime"],
            "provider_session_id": row["provider_session_id"],
            "objective": row["objective"],
            "repository_path": row["repository_path"],
            "workspace_id": row["workspace_id"],
            "workspace_path": row["workspace_path"],
            "source_branch": row["source_branch"],
            "starting_head": row["starting_head"],
            "model": row["model"],
            "status": row["status"],
            "turn_count": row["turn_count"],
            "last_prompt": row["last_prompt"],
            "last_response": row["last_response"],
            "last_receipt_id": row["last_receipt_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        })

    @staticmethod
    def _turn_from_row(row: sqlite3.Row) -> AgentBrokerTurn:
        return AgentBrokerTurn.model_validate({
            "turn_id": row["turn_id"],
            "session_id": row["session_id"],
            "sequence": row["sequence"],
            "prompt": row["prompt"],
            "response": row["response"],
            "provider_session_id": row["provider_session_id"],
            "receipt_id": row["receipt_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
        })
