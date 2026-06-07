"""SQLite-backed typed artifact pub/sub bus for convergence sessions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_DB = Path(".opencobalt") / "artifacts.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS convergence_artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    iteration INTEGER NOT NULL DEFAULT 0,
    wave INTEGER NOT NULL DEFAULT 0,
    producer TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_art_session_type
    ON convergence_artifacts(session_id, type);
"""


class ArtifactType:
    IMPL_CODE = "impl_code"
    TEST_CODE = "test_code"
    DIFF = "diff"
    REVIEW_SCORE = "review_score"
    DOC_TEXT = "doc_text"
    ANALYSIS = "analysis"
    SUMMARY = "summary"
    ERROR_CONTEXT = "error_context"


@dataclass
class AgentArtifact:
    id: str
    session_id: str
    iteration: int
    wave: int
    producer: str
    type: str
    content: str
    metadata: dict
    timestamp: float


class ArtifactBus:
    """SQLite-backed pub/sub bus for typed agent artifacts."""

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

    def publish(self, artifact: AgentArtifact) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO convergence_artifacts "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    artifact.id,
                    artifact.session_id,
                    artifact.iteration,
                    artifact.wave,
                    artifact.producer,
                    artifact.type,
                    artifact.content,
                    json.dumps(artifact.metadata),
                    artifact.timestamp,
                ),
            )

    def subscribe(self, types: list[str], session_id: str) -> list[AgentArtifact]:
        if not types:
            return []
        placeholders = ",".join("?" * len(types))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM convergence_artifacts "
                f"WHERE type IN ({placeholders}) AND session_id = ? "
                f"ORDER BY timestamp ASC",
                (*types, session_id),
            ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def latest(self, type: str, session_id: str) -> AgentArtifact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM convergence_artifacts "
                "WHERE type = ? AND session_id = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (type, session_id),
            ).fetchone()
        return self._row_to_artifact(row) if row else None

    def context_for(self, consumes: list[str], session_id: str) -> str:
        """Build a prompt context block from published artifacts matching consumes."""
        if not consumes:
            return ""
        artifacts = self.subscribe(consumes, session_id)
        if not artifacts:
            return ""
        blocks = [
            f"--- {a.type} from {a.producer} ---\n{a.content}"
            for a in artifacts
        ]
        return "\n\n".join(blocks)

    def _row_to_artifact(self, row: sqlite3.Row) -> AgentArtifact:
        return AgentArtifact(
            id=row["id"],
            session_id=row["session_id"],
            iteration=row["iteration"],
            wave=row["wave"],
            producer=row["producer"],
            type=row["type"],
            content=row["content"],
            metadata=json.loads(row["metadata_json"]),
            timestamp=row["timestamp"],
        )
