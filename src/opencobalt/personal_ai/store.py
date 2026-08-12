"""Additive SQLite persistence for OpenCobalt's personal-AI domain."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opencobalt.core.models import SessionEvent

from .models import (
    AISettings,
    ChatExecution,
    ChatMessage,
    Conversation,
    MemoryEntry,
    Persona,
    PersonaVersion,
    ProviderPreference,
    RouteCandidate,
    RouteRecord,
    SkillRecord,
    SkillVersion,
    StreamEvent,
)

_DEFAULT_DB = Path(".opencobalt") / "ledger.db"

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS personal_ai_schema_versions (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    project_path     TEXT,
    archived         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    metadata_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_conversations_updated
ON conversations (archived, updated_at DESC);

CREATE TABLE IF NOT EXISTS personas (
    persona_id        TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    built_in          INTEGER NOT NULL DEFAULT 0,
    active_version_id TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (active_version_id) REFERENCES persona_versions(persona_version_id)
);

CREATE TABLE IF NOT EXISTS persona_versions (
    persona_version_id       TEXT PRIMARY KEY,
    persona_id               TEXT NOT NULL,
    version                  INTEGER NOT NULL CHECK (version > 0),
    controls_json            TEXT NOT NULL,
    cognitive_policies_json  TEXT NOT NULL DEFAULT '[]',
    provider_affinities_json TEXT NOT NULL DEFAULT '{}',
    custom_instructions      TEXT NOT NULL DEFAULT '',
    native_provider_family   TEXT,
    created_at               TEXT NOT NULL,
    UNIQUE (persona_id, version),
    FOREIGN KEY (persona_id) REFERENCES personas(persona_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_persona_versions_persona
ON persona_versions (persona_id, version DESC);

CREATE TRIGGER IF NOT EXISTS persona_versions_no_update
BEFORE UPDATE ON persona_versions
BEGIN
    SELECT RAISE(ABORT, 'persona_versions is immutable');
END;

CREATE TRIGGER IF NOT EXISTS persona_versions_no_delete
BEFORE DELETE ON persona_versions
BEGIN
    SELECT RAISE(ABORT, 'persona_versions is immutable');
END;

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id          TEXT PRIMARY KEY,
    conversation_id     TEXT NOT NULL,
    role                TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content             TEXT NOT NULL,
    status              TEXT NOT NULL,
    persona_version_id  TEXT,
    route_id            TEXT,
    parent_message_id   TEXT,
    created_at          TEXT NOT NULL,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (persona_version_id) REFERENCES persona_versions(persona_version_id),
    FOREIGN KEY (route_id) REFERENCES ai_route_decisions(route_id),
    FOREIGN KEY (parent_message_id) REFERENCES chat_messages(message_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation
ON chat_messages (conversation_id, created_at, message_id);

CREATE TABLE IF NOT EXISTS ai_route_decisions (
    route_id                      TEXT PRIMARY KEY,
    request_id                    TEXT NOT NULL UNIQUE,
    conversation_id               TEXT NOT NULL,
    request_message_id            TEXT NOT NULL,
    task_class                    TEXT NOT NULL,
    task_complexity               TEXT NOT NULL,
    selected_provider             TEXT NOT NULL,
    selected_model                TEXT,
    selected_runtime              TEXT,
    requested_persona_id          TEXT NOT NULL,
    requested_persona_version_id  TEXT,
    actual_persona_id             TEXT NOT NULL,
    actual_persona_version_id     TEXT,
    selected_tools_json           TEXT NOT NULL DEFAULT '[]',
    selected_skills_json          TEXT NOT NULL DEFAULT '[]',
    privacy_classification        TEXT NOT NULL,
    autonomy_level                TEXT NOT NULL,
    approval_requirements_json    TEXT NOT NULL DEFAULT '[]',
    estimated_cost_category       TEXT NOT NULL,
    actual_usage_json             TEXT NOT NULL DEFAULT '{}',
    expected_latency_category     TEXT NOT NULL,
    route_score                   INTEGER NOT NULL,
    reasons_json                  TEXT NOT NULL DEFAULT '[]',
    fallback_events_json          TEXT NOT NULL DEFAULT '[]',
    verification_strategy         TEXT NOT NULL,
    persona_provider_mismatch     TEXT,
    outcome_status                TEXT NOT NULL,
    receipt_id                    TEXT,
    created_at                    TEXT NOT NULL,
    updated_at                    TEXT NOT NULL,
    metadata_json                 TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (request_message_id) REFERENCES chat_messages(message_id),
    FOREIGN KEY (requested_persona_id) REFERENCES personas(persona_id),
    FOREIGN KEY (requested_persona_version_id) REFERENCES persona_versions(persona_version_id),
    FOREIGN KEY (actual_persona_id) REFERENCES personas(persona_id),
    FOREIGN KEY (actual_persona_version_id) REFERENCES persona_versions(persona_version_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_routes_created
ON ai_route_decisions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_routes_conversation
ON ai_route_decisions (conversation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ai_route_candidates (
    candidate_id          TEXT PRIMARY KEY,
    route_id              TEXT NOT NULL,
    provider_id           TEXT NOT NULL,
    model_id              TEXT,
    runtime_id            TEXT,
    rank                  INTEGER NOT NULL CHECK (rank > 0),
    score                 INTEGER NOT NULL,
    score_components_json TEXT NOT NULL DEFAULT '{}',
    eligible              INTEGER NOT NULL,
    reasons_json          TEXT NOT NULL DEFAULT '[]',
    rejection_reason      TEXT,
    created_at            TEXT NOT NULL,
    UNIQUE (route_id, rank),
    FOREIGN KEY (route_id) REFERENCES ai_route_decisions(route_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_executions (
    execution_id          TEXT PRIMARY KEY,
    request_id            TEXT NOT NULL,
    route_id              TEXT NOT NULL,
    conversation_id       TEXT NOT NULL,
    provider_id           TEXT NOT NULL,
    model_id              TEXT,
    status                TEXT NOT NULL,
    provider_error_type   TEXT,
    provider_error_message TEXT,
    work_receipt_id       TEXT,
    assistant_message_id  TEXT,
    usage_json            TEXT NOT NULL DEFAULT '{}',
    started_at            TEXT,
    finished_at           TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    FOREIGN KEY (route_id) REFERENCES ai_route_decisions(route_id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (assistant_message_id) REFERENCES chat_messages(message_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_executions_request
ON chat_executions (request_id, created_at);

CREATE TABLE IF NOT EXISTS chat_stream_events (
    event_id      TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    sequence     INTEGER NOT NULL CHECK (sequence > 0),
    event_type   TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    UNIQUE (execution_id, sequence),
    FOREIGN KEY (execution_id) REFERENCES chat_executions(execution_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS curated_memory_entries (
    memory_id         TEXT PRIMARY KEY,
    content           TEXT NOT NULL,
    source_type       TEXT NOT NULL,
    source_ref        TEXT,
    reason            TEXT NOT NULL,
    scope             TEXT NOT NULL,
    status            TEXT NOT NULL,
    sensitivity       TEXT NOT NULL,
    pinned            INTEGER NOT NULL DEFAULT 0,
    conversation_id   TEXT,
    source_message_id TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    metadata_json     TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL,
    FOREIGN KEY (source_message_id) REFERENCES chat_messages(message_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_curated_memory_scope
ON curated_memory_entries (status, scope, pinned DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS skill_records (
    skill_id                   TEXT PRIMARY KEY,
    name                       TEXT NOT NULL UNIQUE,
    description                TEXT NOT NULL,
    source_kind                TEXT NOT NULL,
    source_ref                 TEXT NOT NULL,
    enabled                    INTEGER NOT NULL DEFAULT 1,
    trust_level                TEXT NOT NULL,
    active_version_id          TEXT,
    requested_permissions_json TEXT NOT NULL DEFAULT '[]',
    compatibility_json         TEXT NOT NULL DEFAULT '{}',
    last_used_at               TEXT,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL,
    FOREIGN KEY (active_version_id) REFERENCES skill_versions(skill_version_id)
);

CREATE TABLE IF NOT EXISTS skill_versions (
    skill_version_id TEXT PRIMARY KEY,
    skill_id         TEXT NOT NULL,
    version          TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    manifest_json    TEXT NOT NULL DEFAULT '{}',
    install_path     TEXT,
    receipt_id       TEXT,
    created_at       TEXT NOT NULL,
    UNIQUE (skill_id, version, content_hash),
    FOREIGN KEY (skill_id) REFERENCES skill_records(skill_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS provider_preferences (
    provider_id TEXT PRIMARY KEY,
    enabled     INTEGER NOT NULL DEFAULT 1,
    priority    INTEGER NOT NULL,
    cost_policy TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS personal_ai_settings (
    settings_id   TEXT PRIMARY KEY CHECK (settings_id = 'default'),
    settings_json TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""

_MIGRATION_V2 = """
BEGIN IMMEDIATE;

CREATE TABLE personas_v2 (
    persona_id        TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    built_in          INTEGER NOT NULL DEFAULT 0,
    active_version_id TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (active_version_id) REFERENCES persona_versions(persona_version_id)
);

INSERT INTO personas_v2
    (persona_id, name, description, built_in, active_version_id, created_at, updated_at)
SELECT
    persona_id,
    name,
    description,
    built_in,
    active_version_id,
    created_at,
    updated_at
FROM personas;

DROP TABLE personas;
ALTER TABLE personas_v2 RENAME TO personas;

CREATE TABLE chat_messages_v2 (
    message_id          TEXT PRIMARY KEY,
    conversation_id     TEXT NOT NULL,
    role                TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content             TEXT NOT NULL,
    status              TEXT NOT NULL,
    persona_version_id  TEXT,
    route_id            TEXT,
    parent_message_id   TEXT,
    created_at          TEXT NOT NULL,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (persona_version_id) REFERENCES persona_versions(persona_version_id),
    FOREIGN KEY (route_id) REFERENCES ai_route_decisions(route_id),
    FOREIGN KEY (parent_message_id) REFERENCES chat_messages_v2(message_id)
);

INSERT INTO chat_messages_v2
    (message_id, conversation_id, role, content, status, persona_version_id,
     route_id, parent_message_id, created_at, metadata_json)
SELECT
    message_id,
    conversation_id,
    role,
    content,
    status,
    persona_version_id,
    route_id,
    parent_message_id,
    created_at,
    metadata_json
FROM chat_messages;

DROP TABLE chat_messages;
ALTER TABLE chat_messages_v2 RENAME TO chat_messages;
CREATE INDEX idx_chat_messages_conversation
ON chat_messages (conversation_id, created_at, message_id);

CREATE TABLE ai_route_decisions_v2 (
    route_id                      TEXT PRIMARY KEY,
    request_id                    TEXT NOT NULL UNIQUE,
    conversation_id               TEXT NOT NULL,
    request_message_id            TEXT NOT NULL,
    task_class                    TEXT NOT NULL,
    task_complexity               TEXT NOT NULL,
    selected_provider             TEXT NOT NULL,
    selected_model                TEXT,
    selected_runtime              TEXT,
    requested_persona_id          TEXT NOT NULL,
    requested_persona_version_id  TEXT,
    actual_persona_id             TEXT NOT NULL,
    actual_persona_version_id     TEXT,
    selected_tools_json           TEXT NOT NULL DEFAULT '[]',
    selected_skills_json          TEXT NOT NULL DEFAULT '[]',
    privacy_classification        TEXT NOT NULL,
    autonomy_level                TEXT NOT NULL,
    approval_requirements_json    TEXT NOT NULL DEFAULT '[]',
    estimated_cost_category       TEXT NOT NULL,
    actual_usage_json             TEXT NOT NULL DEFAULT '{}',
    expected_latency_category     TEXT NOT NULL,
    route_score                   INTEGER NOT NULL,
    reasons_json                  TEXT NOT NULL DEFAULT '[]',
    fallback_events_json          TEXT NOT NULL DEFAULT '[]',
    verification_strategy         TEXT NOT NULL,
    persona_provider_mismatch     TEXT,
    outcome_status                TEXT NOT NULL,
    receipt_id                    TEXT,
    created_at                    TEXT NOT NULL,
    updated_at                    TEXT NOT NULL,
    metadata_json                 TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (request_message_id) REFERENCES chat_messages(message_id),
    FOREIGN KEY (requested_persona_id) REFERENCES personas(persona_id),
    FOREIGN KEY (requested_persona_version_id) REFERENCES persona_versions(persona_version_id),
    FOREIGN KEY (actual_persona_id) REFERENCES personas(persona_id),
    FOREIGN KEY (actual_persona_version_id) REFERENCES persona_versions(persona_version_id)
);

INSERT INTO ai_route_decisions_v2
    (route_id, request_id, conversation_id, request_message_id, task_class,
     task_complexity, selected_provider, selected_model, selected_runtime,
     requested_persona_id, requested_persona_version_id, actual_persona_id,
     actual_persona_version_id, selected_tools_json, selected_skills_json,
     privacy_classification, autonomy_level, approval_requirements_json,
     estimated_cost_category, actual_usage_json, expected_latency_category,
     route_score, reasons_json, fallback_events_json, verification_strategy,
     persona_provider_mismatch, outcome_status, receipt_id, created_at, updated_at,
     metadata_json)
SELECT
    route_id, request_id, conversation_id, request_message_id, task_class,
    task_complexity, selected_provider, selected_model, selected_runtime,
    requested_persona_id, requested_persona_version_id, actual_persona_id,
    actual_persona_version_id, selected_tools_json, selected_skills_json,
    privacy_classification, autonomy_level, approval_requirements_json,
    estimated_cost_category, actual_usage_json, expected_latency_category,
    route_score, reasons_json, fallback_events_json, verification_strategy,
    persona_provider_mismatch, outcome_status, receipt_id, created_at, updated_at,
    metadata_json
FROM ai_route_decisions;

DROP TABLE ai_route_decisions;
ALTER TABLE ai_route_decisions_v2 RENAME TO ai_route_decisions;
CREATE INDEX idx_ai_routes_created
ON ai_route_decisions (created_at DESC);
CREATE INDEX idx_ai_routes_conversation
ON ai_route_decisions (conversation_id, created_at DESC);

CREATE TABLE skill_records_v2 (
    skill_id                   TEXT PRIMARY KEY,
    name                       TEXT NOT NULL UNIQUE,
    description                TEXT NOT NULL,
    source_kind                TEXT NOT NULL,
    source_ref                 TEXT NOT NULL,
    enabled                    INTEGER NOT NULL DEFAULT 1,
    trust_level                TEXT NOT NULL,
    active_version_id          TEXT,
    requested_permissions_json TEXT NOT NULL DEFAULT '[]',
    compatibility_json         TEXT NOT NULL DEFAULT '{}',
    last_used_at               TEXT,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL,
    FOREIGN KEY (active_version_id) REFERENCES skill_versions(skill_version_id)
);

INSERT INTO skill_records_v2
    (skill_id, name, description, source_kind, source_ref, enabled, trust_level,
     active_version_id, requested_permissions_json, compatibility_json,
     last_used_at, created_at, updated_at)
SELECT
    skill_id,
    name,
    description,
    source_kind,
    source_ref,
    enabled,
    trust_level,
    active_version_id,
    requested_permissions_json,
    compatibility_json,
    last_used_at,
    created_at,
    updated_at
FROM skill_records;

DROP TABLE skill_records;
ALTER TABLE skill_records_v2 RENAME TO skill_records;

INSERT OR IGNORE INTO personal_ai_schema_versions (version, applied_at)
VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
"""

_V2_REQUIRED_FOREIGN_KEYS = {
    "personas": {("active_version_id", "persona_versions", "persona_version_id")},
    "chat_messages": {("route_id", "ai_route_decisions", "route_id")},
    "ai_route_decisions": {
        ("requested_persona_id", "personas", "persona_id"),
        ("actual_persona_id", "personas", "persona_id"),
    },
    "skill_records": {("active_version_id", "skill_versions", "skill_version_id")},
}

_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS research_missions (
    research_id      TEXT PRIMARY KEY,
    mission_id       TEXT NOT NULL UNIQUE,
    conversation_id  TEXT,
    route_id         TEXT,
    question         TEXT NOT NULL,
    status           TEXT NOT NULL,
    synthesis        TEXT NOT NULL DEFAULT '',
    limitations_json TEXT NOT NULL DEFAULT '[]',
    model_roles_json TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    metadata_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS research_queries (
    query_id     TEXT PRIMARY KEY,
    research_id  TEXT NOT NULL,
    query_text   TEXT NOT NULL,
    purpose      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    FOREIGN KEY (research_id) REFERENCES research_missions(research_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_sources (
    source_id            TEXT PRIMARY KEY,
    research_id          TEXT NOT NULL,
    url                  TEXT NOT NULL,
    title                TEXT NOT NULL DEFAULT '',
    source_type          TEXT NOT NULL DEFAULT 'unknown',
    publication_date     TEXT,
    authors_json         TEXT NOT NULL DEFAULT '[]',
    retrieved_at         TEXT,
    retrieval_status     TEXT NOT NULL DEFAULT 'unverified',
    content_hash         TEXT,
    excerpt              TEXT NOT NULL DEFAULT '',
    quality_assessment   TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    FOREIGN KEY (research_id) REFERENCES research_missions(research_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_research_sources_research
ON research_sources (research_id, created_at);

CREATE TABLE IF NOT EXISTS research_evidence (
    evidence_id          TEXT PRIMARY KEY,
    research_id          TEXT NOT NULL,
    source_id            TEXT,
    claim                TEXT NOT NULL,
    passage              TEXT NOT NULL DEFAULT '',
    summary              TEXT NOT NULL DEFAULT '',
    evidence_strength    TEXT NOT NULL DEFAULT 'unknown',
    causal_class         TEXT NOT NULL DEFAULT 'unspecified',
    relation             TEXT NOT NULL DEFAULT 'neutral',
    study_design         TEXT NOT NULL DEFAULT '',
    population           TEXT NOT NULL DEFAULT '',
    sample_size          TEXT NOT NULL DEFAULT '',
    endpoint             TEXT NOT NULL DEFAULT '',
    effect_direction     TEXT NOT NULL DEFAULT '',
    effect_magnitude     TEXT NOT NULL DEFAULT '',
    limitations          TEXT NOT NULL DEFAULT '',
    extraction_model     TEXT,
    reviewer_model       TEXT,
    verification_status  TEXT NOT NULL DEFAULT 'unverified',
    created_at           TEXT NOT NULL,
    FOREIGN KEY (research_id) REFERENCES research_missions(research_id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES research_sources(source_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_research_evidence_research
ON research_evidence (research_id, created_at);

CREATE TABLE IF NOT EXISTS research_citations (
    citation_id          TEXT PRIMARY KEY,
    research_id          TEXT NOT NULL,
    evidence_id          TEXT,
    source_id            TEXT,
    claim_span           TEXT NOT NULL DEFAULT '',
    verification_status  TEXT NOT NULL DEFAULT 'unverified',
    verification_note    TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    FOREIGN KEY (research_id) REFERENCES research_missions(research_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS research_disagreements (
    disagreement_id TEXT PRIMARY KEY,
    research_id     TEXT NOT NULL,
    topic           TEXT NOT NULL,
    positions_json  TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    FOREIGN KEY (research_id) REFERENCES research_missions(research_id) ON DELETE CASCADE
);
"""


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load(raw: str | None, fallback: Any) -> Any:
    return json.loads(raw) if raw else fallback


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


class PersonalAIStore:
    """Owns additive chat-domain tables inside the shared local ledger."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = (db_path or _DEFAULT_DB).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA_V1)
            conn.execute(
                "INSERT OR IGNORE INTO personal_ai_schema_versions (version, applied_at) "
                "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (1,),
            )
            conn.commit()
            self._apply_v2(conn)
            self._apply_v3(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _apply_v2(self, conn: sqlite3.Connection) -> None:
        needs_rebuild = any(
            not required.issubset(self._foreign_keys(conn, table))
            for table, required in _V2_REQUIRED_FOREIGN_KEYS.items()
        )
        if needs_rebuild:
            conn.execute("PRAGMA foreign_keys = OFF")
            try:
                # The migration script opens its own transaction so schema and version
                # changes remain reversible until the rebuilt graph passes validation.
                conn.executescript(_MIGRATION_V2)
                violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    raise sqlite3.IntegrityError(
                        "personal AI v2 migration left foreign key violations: "
                        f"{violations}"
                    )
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")
        else:
            conn.execute(
                "INSERT OR IGNORE INTO personal_ai_schema_versions (version, applied_at) "
                "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
                (2,),
            )

    def _apply_v3(self, conn: sqlite3.Connection) -> None:
        versions = {
            row[0]
            for row in conn.execute("SELECT version FROM personal_ai_schema_versions")
        }
        if 2 not in versions:
            return
        conn.executescript(_SCHEMA_V3)
        conn.execute(
            "INSERT OR IGNORE INTO personal_ai_schema_versions (version, applied_at) "
            "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
            (3,),
        )

    @staticmethod
    def _foreign_keys(
        conn: sqlite3.Connection, table: str
    ) -> set[tuple[str, str, str]]:
        return {
            (row[3], row[2], row[4])
            for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        }

    # Conversations and messages

    def create_conversation(
        self,
        *,
        title: str = "New conversation",
        project_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation:
        conversation = Conversation(
            title=title,
            project_path=project_path,
            metadata=metadata or {},
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations "
                "(conversation_id, title, project_path, archived, created_at, updated_at, "
                "metadata_json) VALUES (?,?,?,?,?,?,?)",
                (
                    conversation.conversation_id,
                    conversation.title,
                    conversation.project_path,
                    int(conversation.archived),
                    _iso(conversation.created_at),
                    _iso(conversation.updated_at),
                    _dump(conversation.metadata),
                ),
            )
        return conversation

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return self._decode_conversation(row) if row else None

    def list_conversations(self, *, limit: int = 100, include_archived: bool = False) -> list[Conversation]:
        sql = "SELECT * FROM conversations"
        params: list[Any] = []
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_conversation(row) for row in rows]

    def add_message(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str,
        status: str = "complete",
        persona_version_id: str | None = None,
        route_id: str | None = None,
        parent_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            status=status,
            persona_version_id=persona_version_id,
            route_id=route_id,
            parent_message_id=parent_message_id,
            metadata=metadata or {},
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_messages "
                "(message_id, conversation_id, role, content, status, persona_version_id, "
                "route_id, parent_message_id, created_at, metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    message.message_id,
                    message.conversation_id,
                    message.role,
                    message.content,
                    message.status,
                    message.persona_version_id,
                    message.route_id,
                    message.parent_message_id,
                    _iso(message.created_at),
                    _dump(message.metadata),
                ),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                (_iso(message.created_at), conversation_id),
            )
        return message

    def list_messages(self, conversation_id: str, *, limit: int = 500) -> list[ChatMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_messages WHERE conversation_id = ? "
                "ORDER BY created_at, message_id LIMIT ?",
                (conversation_id, max(1, min(limit, 2000))),
            ).fetchall()
        return [self._decode_message(row) for row in rows]

    def get_message(self, message_id: str) -> ChatMessage | None:
        """Return one durable chat message without broad conversation scans."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_messages WHERE message_id = ?", (message_id,)
            ).fetchone()
        return self._decode_message(row) if row else None

    def update_message(
        self,
        message_id: str,
        *,
        content: str | None = None,
        status: str | None = None,
        route_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_messages WHERE message_id = ?", (message_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown message: {message_id}")
            current = self._decode_message(row)
            payload = current.model_dump()
            payload.update(
                {
                    "content": content if content is not None else current.content,
                    "status": status if status is not None else current.status,
                    "route_id": route_id if route_id is not None else current.route_id,
                    "metadata": metadata if metadata is not None else current.metadata,
                }
            )
            updated = ChatMessage.model_validate(payload)
            conn.execute(
                "UPDATE chat_messages SET content = ?, status = ?, route_id = ?, "
                "metadata_json = ? WHERE message_id = ?",
                (
                    updated.content,
                    updated.status,
                    updated.route_id,
                    _dump(updated.metadata),
                    message_id,
                ),
            )
        return updated

    # Personas

    def save_persona(self, persona: Persona) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO personas "
                "(persona_id, name, description, built_in, active_version_id, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(persona_id) DO UPDATE SET "
                "name=excluded.name, description=excluded.description, "
                "active_version_id=excluded.active_version_id, updated_at=excluded.updated_at",
                (
                    persona.persona_id,
                    persona.name,
                    persona.description,
                    int(persona.built_in),
                    persona.active_version_id,
                    _iso(persona.created_at),
                    _iso(persona.updated_at),
                ),
            )

    def add_persona_version(self, version: PersonaVersion, *, activate: bool = True) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO persona_versions "
                "(persona_version_id, persona_id, version, controls_json, "
                "cognitive_policies_json, provider_affinities_json, custom_instructions, "
                "native_provider_family, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    version.persona_version_id,
                    version.persona_id,
                    version.version,
                    _dump(version.controls.model_dump(mode="json")),
                    _dump(version.allowed_cognitive_policies),
                    _dump(version.provider_affinities),
                    version.custom_instructions,
                    version.native_provider_family,
                    _iso(version.created_at),
                ),
            )
            if activate:
                conn.execute(
                    "UPDATE personas SET active_version_id = ?, updated_at = ? "
                    "WHERE persona_id = ?",
                    (version.persona_version_id, _iso(version.created_at), version.persona_id),
                )

    def get_persona(self, persona_id: str) -> Persona | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM personas WHERE persona_id = ?", (persona_id,)
            ).fetchone()
        return self._decode_persona(row) if row else None

    def list_personas(self) -> list[Persona]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM personas ORDER BY built_in DESC, name"
            ).fetchall()
        return [self._decode_persona(row) for row in rows]

    def get_persona_version(self, persona_version_id: str) -> PersonaVersion | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM persona_versions WHERE persona_version_id = ?",
                (persona_version_id,),
            ).fetchone()
        return self._decode_persona_version(row) if row else None

    def get_active_persona_version(self, persona_id: str) -> PersonaVersion | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT pv.* FROM personas p JOIN persona_versions pv "
                "ON pv.persona_version_id = p.active_version_id WHERE p.persona_id = ?",
                (persona_id,),
            ).fetchone()
        return self._decode_persona_version(row) if row else None

    # Route and execution records

    def save_route(self, route: RouteRecord) -> None:
        values = (
            route.route_id,
            route.request_id,
            route.conversation_id,
            route.request_message_id,
            route.task_class,
            route.task_complexity,
            route.selected_provider,
            route.selected_model,
            route.selected_runtime,
            route.requested_persona_id,
            route.requested_persona_version_id,
            route.actual_persona_id,
            route.actual_persona_version_id,
            _dump(route.selected_tools),
            _dump(route.selected_skills),
            route.privacy_classification,
            route.autonomy_level,
            _dump(route.approval_requirements),
            route.estimated_cost_category,
            _dump(route.actual_usage),
            route.expected_latency_category,
            route.route_score,
            _dump(route.reasons),
            _dump(route.fallback_events),
            route.verification_strategy,
            route.persona_provider_mismatch,
            route.outcome_status,
            route.receipt_id,
            _iso(route.created_at),
            _iso(route.updated_at),
            _dump(route.metadata),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ai_route_decisions "
                "(route_id, request_id, conversation_id, request_message_id, task_class, "
                "task_complexity, selected_provider, selected_model, selected_runtime, "
                "requested_persona_id, requested_persona_version_id, actual_persona_id, "
                "actual_persona_version_id, selected_tools_json, selected_skills_json, "
                "privacy_classification, autonomy_level, approval_requirements_json, "
                "estimated_cost_category, actual_usage_json, expected_latency_category, "
                "route_score, reasons_json, fallback_events_json, verification_strategy, "
                "persona_provider_mismatch, outcome_status, receipt_id, created_at, updated_at, "
                "metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(route_id) DO UPDATE SET actual_usage_json=excluded.actual_usage_json, "
                "actual_persona_id=excluded.actual_persona_id, "
                "actual_persona_version_id=excluded.actual_persona_version_id, "
                "persona_provider_mismatch=excluded.persona_provider_mismatch, "
                "fallback_events_json=excluded.fallback_events_json, "
                "outcome_status=excluded.outcome_status, receipt_id=excluded.receipt_id, "
                "updated_at=excluded.updated_at, metadata_json=excluded.metadata_json",
                values,
            )

    def get_route(self, route_id: str) -> RouteRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ai_route_decisions WHERE route_id = ?", (route_id,)
            ).fetchone()
        return self._decode_route(row) if row else None

    def list_routes(
        self, *, conversation_id: str | None = None, limit: int = 100
    ) -> list[RouteRecord]:
        sql = "SELECT * FROM ai_route_decisions"
        params: list[Any] = []
        if conversation_id:
            sql += " WHERE conversation_id = ?"
            params.append(conversation_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_route(row) for row in rows]

    def save_route_candidate(self, candidate: RouteCandidate) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ai_route_candidates "
                "(candidate_id, route_id, provider_id, model_id, runtime_id, rank, score, "
                "score_components_json, eligible, reasons_json, rejection_reason, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    candidate.candidate_id,
                    candidate.route_id,
                    candidate.provider_id,
                    candidate.model_id,
                    candidate.runtime_id,
                    candidate.rank,
                    candidate.score,
                    _dump(candidate.score_components),
                    int(candidate.eligible),
                    _dump(candidate.reasons),
                    candidate.rejection_reason,
                    _iso(candidate.created_at),
                ),
            )

    def list_route_candidates(self, route_id: str) -> list[RouteCandidate]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_route_candidates WHERE route_id = ? ORDER BY rank",
                (route_id,),
            ).fetchall()
        return [self._decode_candidate(row) for row in rows]

    def save_execution(self, execution: ChatExecution) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_executions "
                "(execution_id, request_id, route_id, conversation_id, provider_id, model_id, "
                "status, provider_error_type, provider_error_message, work_receipt_id, "
                "assistant_message_id, usage_json, started_at, finished_at, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(execution_id) DO UPDATE SET status=excluded.status, "
                "provider_error_type=excluded.provider_error_type, "
                "provider_error_message=excluded.provider_error_message, "
                "work_receipt_id=excluded.work_receipt_id, "
                "assistant_message_id=excluded.assistant_message_id, usage_json=excluded.usage_json, "
                "started_at=excluded.started_at, finished_at=excluded.finished_at, "
                "updated_at=excluded.updated_at",
                (
                    execution.execution_id,
                    execution.request_id,
                    execution.route_id,
                    execution.conversation_id,
                    execution.provider_id,
                    execution.model_id,
                    execution.status,
                    execution.provider_error_type,
                    execution.provider_error_message,
                    execution.work_receipt_id,
                    execution.assistant_message_id,
                    _dump(execution.usage),
                    _iso(execution.started_at),
                    _iso(execution.finished_at),
                    _iso(execution.created_at),
                    _iso(execution.updated_at),
                ),
            )

    def get_execution(self, execution_id: str) -> ChatExecution | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM chat_executions WHERE execution_id = ?", (execution_id,)
            ).fetchone()
        return self._decode_execution(row) if row else None

    def list_executions(
        self,
        *,
        conversation_id: str | None = None,
        request_id: str | None = None,
        limit: int = 100,
    ) -> list[ChatExecution]:
        """List bounded chat execution attempts, newest first."""
        clauses: list[str] = []
        params: list[Any] = []
        if conversation_id is not None:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if request_id is not None:
            clauses.append("request_id = ?")
            params.append(request_id)
        sql = "SELECT * FROM chat_executions"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, execution_id DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_execution(row) for row in rows]

    def append_stream_event(self, event: StreamEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_stream_events "
                "(event_id, execution_id, sequence, event_type, payload_json, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.execution_id,
                    event.sequence,
                    event.event_type,
                    _dump(event.payload),
                    _iso(event.created_at),
                ),
            )

    def list_stream_events(self, execution_id: str) -> list[StreamEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM chat_stream_events WHERE execution_id = ? ORDER BY sequence",
                (execution_id,),
            ).fetchall()
        return [
            StreamEvent(
                event_id=row["event_id"],
                execution_id=row["execution_id"],
                sequence=row["sequence"],
                event_type=row["event_type"],
                payload=_load(row["payload_json"], {}),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # Curated memory and skills

    def save_memory(self, memory: MemoryEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO curated_memory_entries "
                "(memory_id, content, source_type, source_ref, reason, scope, status, sensitivity, "
                "pinned, conversation_id, source_message_id, created_at, updated_at, metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(memory_id) DO UPDATE SET content=excluded.content, reason=excluded.reason, "
                "scope=excluded.scope, status=excluded.status, sensitivity=excluded.sensitivity, "
                "pinned=excluded.pinned, updated_at=excluded.updated_at, "
                "metadata_json=excluded.metadata_json",
                (
                    memory.memory_id,
                    memory.content,
                    memory.source_type,
                    memory.source_ref,
                    memory.reason,
                    memory.scope,
                    memory.status,
                    memory.sensitivity,
                    int(memory.pinned),
                    memory.conversation_id,
                    memory.source_message_id,
                    _iso(memory.created_at),
                    _iso(memory.updated_at),
                    _dump(memory.metadata),
                ),
            )

    def list_memory(self, *, status: str | None = None, limit: int = 200) -> list[MemoryEntry]:
        sql = "SELECT * FROM curated_memory_entries"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_memory(row) for row in rows]

    def get_memory(self, memory_id: str) -> MemoryEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM curated_memory_entries WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        return self._decode_memory(row) if row else None

    def delete_memory(self, memory_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM curated_memory_entries WHERE memory_id = ?", (memory_id,)
            )
        return cursor.rowcount == 1

    def save_skill(self, skill: SkillRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_records "
                "(skill_id, name, description, source_kind, source_ref, enabled, trust_level, "
                "active_version_id, requested_permissions_json, compatibility_json, last_used_at, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET description=excluded.description, "
                "source_ref=excluded.source_ref, enabled=excluded.enabled, "
                "active_version_id=excluded.active_version_id, "
                "requested_permissions_json=excluded.requested_permissions_json, "
                "compatibility_json=excluded.compatibility_json, last_used_at=excluded.last_used_at, "
                "updated_at=excluded.updated_at",
                (
                    skill.skill_id,
                    skill.name,
                    skill.description,
                    skill.source_kind,
                    skill.source_ref,
                    int(skill.enabled),
                    skill.trust_level,
                    skill.active_version_id,
                    _dump(skill.requested_permissions),
                    _dump(skill.compatibility),
                    _iso(skill.last_used_at),
                    _iso(skill.created_at),
                    _iso(skill.updated_at),
                ),
            )

    def list_skills(self, *, enabled: bool | None = None) -> list[SkillRecord]:
        sql = "SELECT * FROM skill_records"
        params: list[Any] = []
        if enabled is not None:
            sql += " WHERE enabled = ?"
            params.append(int(enabled))
        sql += " ORDER BY name"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_skill(row) for row in rows]

    def get_skill(self, skill_id: str) -> SkillRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_records WHERE skill_id = ?", (skill_id,)
            ).fetchone()
        return self._decode_skill(row) if row else None

    def get_skill_by_name(self, name: str) -> SkillRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_records WHERE name = ?", (name,)
            ).fetchone()
        return self._decode_skill(row) if row else None

    def save_skill_version(self, version: SkillVersion, *, activate: bool = True) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_versions "
                "(skill_version_id, skill_id, version, content_hash, manifest_json, install_path, "
                "receipt_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    version.skill_version_id,
                    version.skill_id,
                    version.version,
                    version.content_hash,
                    _dump(version.manifest),
                    version.install_path,
                    version.receipt_id,
                    _iso(version.created_at),
                ),
            )
            if activate:
                conn.execute(
                    "UPDATE skill_records SET active_version_id = ?, updated_at = ? WHERE skill_id = ?",
                    (version.skill_version_id, _iso(version.created_at), version.skill_id),
                )

    def get_skill_version(self, skill_version_id: str) -> SkillVersion | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_versions WHERE skill_version_id = ?",
                (skill_version_id,),
            ).fetchone()
        return self._decode_skill_version(row) if row else None

    def get_skill_version_by_identity(
        self,
        skill_id: str,
        version: str,
        content_hash: str,
    ) -> SkillVersion | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM skill_versions WHERE skill_id = ? AND version = ? "
                "AND content_hash = ?",
                (skill_id, version, content_hash),
            ).fetchone()
        return self._decode_skill_version(row) if row else None

    def list_skill_versions(self, skill_id: str) -> list[SkillVersion]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_versions WHERE skill_id = ? "
                "ORDER BY created_at DESC, skill_version_id DESC",
                (skill_id,),
            ).fetchall()
        return [self._decode_skill_version(row) for row in rows]

    def activate_skill_version(
        self, skill_id: str, skill_version_id: str
    ) -> SkillRecord:
        now = _iso(datetime.now(tz=timezone.utc))
        with self._connect() as conn:
            version = conn.execute(
                "SELECT 1 FROM skill_versions WHERE skill_version_id = ? AND skill_id = ?",
                (skill_version_id, skill_id),
            ).fetchone()
            if version is None:
                raise KeyError(f"skill version does not belong to skill: {skill_version_id}")
            cursor = conn.execute(
                "UPDATE skill_records SET active_version_id = ?, updated_at = ? "
                "WHERE skill_id = ?",
                (skill_version_id, now, skill_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown skill: {skill_id}")
        skill = self.get_skill(skill_id)
        if skill is None:  # pragma: no cover - guarded by the update rowcount
            raise KeyError(f"unknown skill: {skill_id}")
        return skill

    def save_imported_skill_with_receipt(
        self,
        skill: SkillRecord,
        version: SkillVersion,
        receipt: SessionEvent,
    ) -> None:
        """Atomically persist an imported skill version and its ledger receipt."""
        if skill.skill_id != version.skill_id:
            raise ValueError("skill version does not belong to the supplied skill")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_records "
                "(skill_id, name, description, source_kind, source_ref, enabled, trust_level, "
                "active_version_id, requested_permissions_json, compatibility_json, last_used_at, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET description=excluded.description, "
                "source_ref=excluded.source_ref, enabled=excluded.enabled, "
                "trust_level=excluded.trust_level, "
                "requested_permissions_json=excluded.requested_permissions_json, "
                "compatibility_json=excluded.compatibility_json, "
                "last_used_at=excluded.last_used_at, updated_at=excluded.updated_at",
                (
                    skill.skill_id,
                    skill.name,
                    skill.description,
                    skill.source_kind,
                    skill.source_ref,
                    int(skill.enabled),
                    skill.trust_level,
                    skill.active_version_id,
                    _dump(skill.requested_permissions),
                    _dump(skill.compatibility),
                    _iso(skill.last_used_at),
                    _iso(skill.created_at),
                    _iso(skill.updated_at),
                ),
            )
            conn.execute(
                "INSERT INTO skill_versions "
                "(skill_version_id, skill_id, version, content_hash, manifest_json, "
                "install_path, receipt_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    version.skill_version_id,
                    version.skill_id,
                    version.version,
                    version.content_hash,
                    _dump(version.manifest),
                    version.install_path,
                    version.receipt_id,
                    _iso(version.created_at),
                ),
            )
            conn.execute(
                "UPDATE skill_records SET active_version_id = ?, updated_at = ? "
                "WHERE skill_id = ?",
                (version.skill_version_id, _iso(version.created_at), skill.skill_id),
            )
            self._insert_event(conn, receipt)

    def activate_skill_version_with_receipt(
        self,
        skill_id: str,
        skill_version_id: str,
        receipt: SessionEvent,
    ) -> SkillRecord:
        """Activate a pinned version and record the decision in one DB transaction."""
        now = _iso(datetime.now(tz=timezone.utc))
        with self._connect() as conn:
            version = conn.execute(
                "SELECT 1 FROM skill_versions WHERE skill_version_id = ? AND skill_id = ?",
                (skill_version_id, skill_id),
            ).fetchone()
            if version is None:
                raise KeyError(f"skill version does not belong to skill: {skill_version_id}")
            cursor = conn.execute(
                "UPDATE skill_records SET active_version_id = ?, updated_at = ? "
                "WHERE skill_id = ?",
                (skill_version_id, now, skill_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown skill: {skill_id}")
            self._insert_event(conn, receipt)
        skill = self.get_skill(skill_id)
        if skill is None:  # pragma: no cover - guarded by the update rowcount
            raise KeyError(f"unknown skill: {skill_id}")
        return skill

    def record_event(self, event: SessionEvent) -> None:
        with self._connect() as conn:
            self._insert_event(conn, event)

    @staticmethod
    def _insert_event(conn: sqlite3.Connection, event: SessionEvent) -> None:
        conn.execute(
            "INSERT INTO events "
            "(id, timestamp, project, source, event_type, summary, raw_ref, metadata) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                event.id,
                event.timestamp.isoformat(),
                event.project,
                event.source,
                event.event_type,
                event.summary,
                event.raw_ref,
                _dump(event.metadata),
            ),
        )

    # Typed settings and provider preferences

    def get_settings(self) -> AISettings:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT settings_json FROM personal_ai_settings WHERE settings_id = 'default'"
            ).fetchone()
        return AISettings.model_validate_json(row["settings_json"]) if row else AISettings()

    def save_settings(self, settings: AISettings) -> None:
        now = _iso(datetime.now(tz=timezone.utc))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO personal_ai_settings (settings_id, settings_json, updated_at) "
                "VALUES ('default', ?, ?) ON CONFLICT(settings_id) DO UPDATE SET "
                "settings_json=excluded.settings_json, updated_at=excluded.updated_at",
                (settings.model_dump_json(), now),
            )

    def save_provider_preference(self, preference: ProviderPreference) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO provider_preferences "
                "(provider_id, enabled, priority, cost_policy, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(provider_id) DO UPDATE SET enabled=excluded.enabled, "
                "priority=excluded.priority, cost_policy=excluded.cost_policy, "
                "updated_at=excluded.updated_at",
                (
                    preference.provider_id,
                    int(preference.enabled),
                    preference.priority,
                    preference.cost_policy,
                    _iso(preference.updated_at),
                ),
            )

    def list_provider_preferences(self) -> list[ProviderPreference]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM provider_preferences ORDER BY priority DESC, provider_id"
            ).fetchall()
        return [
            ProviderPreference(
                provider_id=row["provider_id"],
                enabled=bool(row["enabled"]),
                priority=row["priority"],
                cost_policy=row["cost_policy"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    # Decoders

    @staticmethod
    def _decode_conversation(row: sqlite3.Row) -> Conversation:
        return Conversation(
            conversation_id=row["conversation_id"],
            title=row["title"],
            project_path=row["project_path"],
            archived=bool(row["archived"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=_load(row["metadata_json"], {}),
        )

    @staticmethod
    def _decode_message(row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            message_id=row["message_id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            status=row["status"],
            persona_version_id=row["persona_version_id"],
            route_id=row["route_id"],
            parent_message_id=row["parent_message_id"],
            created_at=row["created_at"],
            metadata=_load(row["metadata_json"], {}),
        )

    @staticmethod
    def _decode_persona(row: sqlite3.Row) -> Persona:
        return Persona(
            persona_id=row["persona_id"],
            name=row["name"],
            description=row["description"],
            built_in=bool(row["built_in"]),
            active_version_id=row["active_version_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _decode_persona_version(row: sqlite3.Row) -> PersonaVersion:
        return PersonaVersion(
            persona_version_id=row["persona_version_id"],
            persona_id=row["persona_id"],
            version=row["version"],
            controls=_load(row["controls_json"], {}),
            allowed_cognitive_policies=_load(row["cognitive_policies_json"], []),
            provider_affinities=_load(row["provider_affinities_json"], {}),
            custom_instructions=row["custom_instructions"],
            native_provider_family=row["native_provider_family"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _decode_route(row: sqlite3.Row) -> RouteRecord:
        return RouteRecord(
            route_id=row["route_id"],
            request_id=row["request_id"],
            conversation_id=row["conversation_id"],
            request_message_id=row["request_message_id"],
            task_class=row["task_class"],
            task_complexity=row["task_complexity"],
            selected_provider=row["selected_provider"],
            selected_model=row["selected_model"],
            selected_runtime=row["selected_runtime"],
            requested_persona_id=row["requested_persona_id"],
            requested_persona_version_id=row["requested_persona_version_id"],
            actual_persona_id=row["actual_persona_id"],
            actual_persona_version_id=row["actual_persona_version_id"],
            selected_tools=_load(row["selected_tools_json"], []),
            selected_skills=_load(row["selected_skills_json"], []),
            privacy_classification=row["privacy_classification"],
            autonomy_level=row["autonomy_level"],
            approval_requirements=_load(row["approval_requirements_json"], []),
            estimated_cost_category=row["estimated_cost_category"],
            actual_usage=_load(row["actual_usage_json"], {}),
            expected_latency_category=row["expected_latency_category"],
            route_score=row["route_score"],
            reasons=_load(row["reasons_json"], []),
            fallback_events=_load(row["fallback_events_json"], []),
            verification_strategy=row["verification_strategy"],
            persona_provider_mismatch=row["persona_provider_mismatch"],
            outcome_status=row["outcome_status"],
            receipt_id=row["receipt_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=_load(row["metadata_json"], {}),
        )

    @staticmethod
    def _decode_candidate(row: sqlite3.Row) -> RouteCandidate:
        return RouteCandidate(
            candidate_id=row["candidate_id"],
            route_id=row["route_id"],
            provider_id=row["provider_id"],
            model_id=row["model_id"],
            runtime_id=row["runtime_id"],
            rank=row["rank"],
            score=row["score"],
            score_components=_load(row["score_components_json"], {}),
            eligible=bool(row["eligible"]),
            reasons=_load(row["reasons_json"], []),
            rejection_reason=row["rejection_reason"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _decode_execution(row: sqlite3.Row) -> ChatExecution:
        return ChatExecution(
            execution_id=row["execution_id"],
            request_id=row["request_id"],
            route_id=row["route_id"],
            conversation_id=row["conversation_id"],
            provider_id=row["provider_id"],
            model_id=row["model_id"],
            status=row["status"],
            provider_error_type=row["provider_error_type"],
            provider_error_message=row["provider_error_message"],
            work_receipt_id=row["work_receipt_id"],
            assistant_message_id=row["assistant_message_id"],
            usage=_load(row["usage_json"], {}),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _decode_memory(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            memory_id=row["memory_id"],
            content=row["content"],
            source_type=row["source_type"],
            source_ref=row["source_ref"],
            reason=row["reason"],
            scope=row["scope"],
            status=row["status"],
            sensitivity=row["sensitivity"],
            pinned=bool(row["pinned"]),
            conversation_id=row["conversation_id"],
            source_message_id=row["source_message_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=_load(row["metadata_json"], {}),
        )

    @staticmethod
    def _decode_skill(row: sqlite3.Row) -> SkillRecord:
        return SkillRecord(
            skill_id=row["skill_id"],
            name=row["name"],
            description=row["description"],
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            enabled=bool(row["enabled"]),
            trust_level=row["trust_level"],
            active_version_id=row["active_version_id"],
            requested_permissions=_load(row["requested_permissions_json"], []),
            compatibility=_load(row["compatibility_json"], {}),
            last_used_at=row["last_used_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _decode_skill_version(row: sqlite3.Row) -> SkillVersion:
        return SkillVersion(
            skill_version_id=row["skill_version_id"],
            skill_id=row["skill_id"],
            version=row["version"],
            content_hash=row["content_hash"],
            manifest=_load(row["manifest_json"], {}),
            install_path=row["install_path"],
            receipt_id=row["receipt_id"],
            created_at=row["created_at"],
        )

    def save_research_mission(self, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO research_missions ("
                "research_id, mission_id, conversation_id, route_id, question, status, "
                "synthesis, limitations_json, model_roles_json, created_at, updated_at, "
                "metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(research_id) DO UPDATE SET "
                "mission_id=excluded.mission_id, conversation_id=excluded.conversation_id, "
                "route_id=excluded.route_id, question=excluded.question, status=excluded.status, "
                "synthesis=excluded.synthesis, limitations_json=excluded.limitations_json, "
                "model_roles_json=excluded.model_roles_json, updated_at=excluded.updated_at, "
                "metadata_json=excluded.metadata_json",
                (
                    record["research_id"],
                    record["mission_id"],
                    record.get("conversation_id"),
                    record.get("route_id"),
                    record["question"],
                    record["status"],
                    record.get("synthesis", ""),
                    _dump(record.get("limitations", [])),
                    _dump(record.get("model_roles", {})),
                    record["created_at"],
                    record["updated_at"],
                    _dump(record.get("metadata", {})),
                ),
            )

    def get_research_mission(self, research_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_missions WHERE research_id = ? OR mission_id = ?",
                (research_id, research_id),
            ).fetchone()
        return self._decode_research_mission(row) if row else None

    def get_research_by_route(self, route_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM research_missions WHERE route_id = ?",
                (route_id,),
            ).fetchone()
        return self._decode_research_mission(row) if row else None

    def list_research_missions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM research_missions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._decode_research_mission(row) for row in rows]

    def save_research_query(self, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO research_queries "
                "(query_id, research_id, query_text, purpose, created_at) VALUES (?,?,?,?,?)",
                (
                    record["query_id"],
                    record["research_id"],
                    record["query_text"],
                    record.get("purpose", ""),
                    record["created_at"],
                ),
            )

    def save_research_source(self, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO research_sources ("
                "source_id, research_id, url, title, source_type, publication_date, "
                "authors_json, retrieved_at, retrieval_status, content_hash, excerpt, "
                "quality_assessment, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["source_id"],
                    record["research_id"],
                    record["url"],
                    record.get("title", ""),
                    record.get("source_type", "unknown"),
                    record.get("publication_date"),
                    _dump(record.get("authors", [])),
                    record.get("retrieved_at"),
                    record.get("retrieval_status", "unverified"),
                    record.get("content_hash"),
                    record.get("excerpt", ""),
                    record.get("quality_assessment", ""),
                    record["created_at"],
                ),
            )

    def save_research_evidence(self, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO research_evidence ("
                "evidence_id, research_id, source_id, claim, passage, summary, "
                "evidence_strength, causal_class, relation, study_design, population, "
                "sample_size, endpoint, effect_direction, effect_magnitude, limitations, "
                "extraction_model, reviewer_model, verification_status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["evidence_id"],
                    record["research_id"],
                    record.get("source_id"),
                    record["claim"],
                    record.get("passage", ""),
                    record.get("summary", ""),
                    record.get("evidence_strength", "unknown"),
                    record.get("causal_class", "unspecified"),
                    record.get("relation", "neutral"),
                    record.get("study_design", ""),
                    record.get("population", ""),
                    record.get("sample_size", ""),
                    record.get("endpoint", ""),
                    record.get("effect_direction", ""),
                    record.get("effect_magnitude", ""),
                    record.get("limitations", ""),
                    record.get("extraction_model"),
                    record.get("reviewer_model"),
                    record.get("verification_status", "unverified"),
                    record["created_at"],
                ),
            )

    def save_research_citation(self, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO research_citations ("
                "citation_id, research_id, evidence_id, source_id, claim_span, "
                "verification_status, verification_note, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    record["citation_id"],
                    record["research_id"],
                    record.get("evidence_id"),
                    record.get("source_id"),
                    record.get("claim_span", ""),
                    record.get("verification_status", "unverified"),
                    record.get("verification_note", ""),
                    record["created_at"],
                ),
            )

    def save_research_disagreement(self, record: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO research_disagreements "
                "(disagreement_id, research_id, topic, positions_json, created_at) "
                "VALUES (?,?,?,?,?)",
                (
                    record["disagreement_id"],
                    record["research_id"],
                    record["topic"],
                    _dump(record.get("positions", [])),
                    record["created_at"],
                ),
            )

    def research_bundle(self, research_id: str) -> dict[str, Any] | None:
        mission = self.get_research_mission(research_id)
        if mission is None:
            return None
        with self._connect() as conn:
            queries = conn.execute(
                "SELECT * FROM research_queries WHERE research_id = ? ORDER BY created_at",
                (mission["research_id"],),
            ).fetchall()
            sources = conn.execute(
                "SELECT * FROM research_sources WHERE research_id = ? ORDER BY created_at",
                (mission["research_id"],),
            ).fetchall()
            evidence = conn.execute(
                "SELECT * FROM research_evidence WHERE research_id = ? ORDER BY created_at",
                (mission["research_id"],),
            ).fetchall()
            citations = conn.execute(
                "SELECT * FROM research_citations WHERE research_id = ? ORDER BY created_at",
                (mission["research_id"],),
            ).fetchall()
            disagreements = conn.execute(
                "SELECT * FROM research_disagreements WHERE research_id = ? ORDER BY created_at",
                (mission["research_id"],),
            ).fetchall()
        return {
            **mission,
            "queries": [dict(row) for row in queries],
            "sources": [
                {**dict(row), "authors": _load(row["authors_json"], [])} for row in sources
            ],
            "evidence": [dict(row) for row in evidence],
            "citations": [dict(row) for row in citations],
            "disagreements": [
                {**dict(row), "positions": _load(row["positions_json"], [])}
                for row in disagreements
            ],
        }

    @staticmethod
    def _decode_research_mission(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "research_id": row["research_id"],
            "mission_id": row["mission_id"],
            "conversation_id": row["conversation_id"],
            "route_id": row["route_id"],
            "question": row["question"],
            "status": row["status"],
            "synthesis": row["synthesis"],
            "limitations": _load(row["limitations_json"], []),
            "model_roles": _load(row["model_roles_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": _load(row["metadata_json"], {}),
        }
