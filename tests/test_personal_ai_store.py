from __future__ import annotations

import sqlite3

import pytest

from opencobalt.core.ledger import Ledger
from opencobalt.core.models import SessionEvent
from opencobalt.personal_ai.models import (
    ChatExecution,
    MemoryEntry,
    RouteCandidate,
    RouteRecord,
    SkillRecord,
)
from opencobalt.personal_ai.personas import ensure_builtin_personas
from opencobalt.personal_ai.store import PersonalAIStore

_V1_REMOVED_FK_FRAGMENTS = {
    "personas": [
        ",\n    FOREIGN KEY (active_version_id) REFERENCES persona_versions(persona_version_id)"
    ],
    "chat_messages": [
        "    FOREIGN KEY (route_id) REFERENCES ai_route_decisions(route_id),\n"
    ],
    "ai_route_decisions": [
        "    FOREIGN KEY (requested_persona_id) REFERENCES personas(persona_id),\n",
        "    FOREIGN KEY (actual_persona_id) REFERENCES personas(persona_id),\n",
    ],
    "skill_records": [
        ",\n    FOREIGN KEY (active_version_id) REFERENCES skill_versions(skill_version_id)"
    ],
}


def _downgrade_to_true_v1_schema(conn: sqlite3.Connection) -> None:
    """Reproduce Task 1's committed v1 DDL while preserving every other constraint."""
    conn.execute("PRAGMA foreign_keys = OFF")
    for table, removed_fragments in _V1_REMOVED_FK_FRAGMENTS.items():
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        assert row is not None
        legacy_table = f"{table}_legacy_v1"
        legacy_sql = row[0].replace(f"CREATE TABLE {table}", f"CREATE TABLE {legacy_table}")
        for fragment in removed_fragments:
            assert fragment in legacy_sql
            legacy_sql = legacy_sql.replace(fragment, "")
        conn.execute(legacy_sql)
        columns = [
            column[1] for column in conn.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        column_list = ", ".join(columns)
        conn.execute(
            f"INSERT INTO {legacy_table} ({column_list}) "
            f"SELECT {column_list} FROM {table}"
        )
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {legacy_table} RENAME TO {table}")
    conn.execute("DELETE FROM personal_ai_schema_versions WHERE version = 2")


def test_store_adds_versioned_schema_without_disturbing_legacy_ledger(tmp_path):
    db_path = tmp_path / "ledger.db"
    ledger = Ledger(db_path)
    event = SessionEvent(
        project="test",
        source="test",
        event_type="baseline",
        summary="legacy row survives",
    )
    ledger.insert_event(event)

    PersonalAIStore(db_path)

    assert Ledger(db_path).list_events()[0].id == event.id
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        versions = conn.execute(
            "SELECT version FROM personal_ai_schema_versions ORDER BY version"
        ).fetchall()
        foreign_keys = {
            table: {
                (row[3], row[2], row[4])
                for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
            }
            for table in (
                "personas",
                "persona_versions",
                "chat_messages",
                "ai_route_decisions",
                "ai_route_candidates",
                "chat_executions",
                "chat_stream_events",
                "curated_memory_entries",
                "skill_records",
                "skill_versions",
            )
        }

    assert {
        "conversations",
        "chat_messages",
        "personas",
        "persona_versions",
        "ai_route_decisions",
        "ai_route_candidates",
        "chat_executions",
        "chat_stream_events",
        "curated_memory_entries",
        "skill_records",
        "skill_versions",
        "provider_preferences",
        "personal_ai_settings",
    }.issubset(tables)
    assert versions == [(1,), (2,)]
    assert foreign_keys == {
        "personas": {("active_version_id", "persona_versions", "persona_version_id")},
        "persona_versions": {("persona_id", "personas", "persona_id")},
        "chat_messages": {
            ("conversation_id", "conversations", "conversation_id"),
            ("persona_version_id", "persona_versions", "persona_version_id"),
            ("route_id", "ai_route_decisions", "route_id"),
            ("parent_message_id", "chat_messages", "message_id"),
        },
        "ai_route_decisions": {
            ("conversation_id", "conversations", "conversation_id"),
            ("request_message_id", "chat_messages", "message_id"),
            ("requested_persona_id", "personas", "persona_id"),
            ("requested_persona_version_id", "persona_versions", "persona_version_id"),
            ("actual_persona_id", "personas", "persona_id"),
            ("actual_persona_version_id", "persona_versions", "persona_version_id"),
        },
        "ai_route_candidates": {("route_id", "ai_route_decisions", "route_id")},
        "chat_executions": {
            ("route_id", "ai_route_decisions", "route_id"),
            ("conversation_id", "conversations", "conversation_id"),
            ("assistant_message_id", "chat_messages", "message_id"),
        },
        "chat_stream_events": {("execution_id", "chat_executions", "execution_id")},
        "curated_memory_entries": {
            ("conversation_id", "conversations", "conversation_id"),
            ("source_message_id", "chat_messages", "message_id"),
        },
        "skill_records": {("active_version_id", "skill_versions", "skill_version_id")},
        "skill_versions": {("skill_id", "skill_records", "skill_id")},
    }


def test_conversation_and_messages_survive_store_restart(tmp_path):
    db_path = tmp_path / "ledger.db"
    first = PersonalAIStore(db_path)
    conversation = first.create_conversation(
        title="Router design",
        project_path="/workspace/project",
    )
    user = first.add_message(
        conversation.conversation_id,
        role="user",
        content="Design the router",
    )
    assistant = first.add_message(
        conversation.conversation_id,
        role="assistant",
        content="I selected a bounded route.",
        parent_message_id=user.message_id,
    )

    second = PersonalAIStore(db_path)

    assert second.get_conversation(conversation.conversation_id) == conversation.model_copy(
        update={"updated_at": assistant.created_at}
    )
    assert [message.content for message in second.list_messages(conversation.conversation_id)] == [
        "Design the router",
        "I selected a bounded route.",
    ]
    assert second.list_conversations()[0].conversation_id == conversation.conversation_id


def test_route_execution_memory_and_skill_records_round_trip(tmp_path):
    store = PersonalAIStore(tmp_path / "ledger.db")
    ensure_builtin_personas(store)
    conversation = store.create_conversation(title="Trace")
    message = store.add_message(conversation.conversation_id, role="user", content="Trace it")
    route = RouteRecord(
        request_id="req-1",
        conversation_id=conversation.conversation_id,
        request_message_id=message.message_id,
        task_class="general_reasoning",
        selected_provider="mock",
        selected_model="mock-v1",
        selected_runtime="mock",
        requested_persona_id="analytical",
        actual_persona_id="analytical",
        privacy_classification="private",
        autonomy_level="answer_only",
        route_score=42,
        reasons=["deterministic development route"],
    )
    store.save_route(route)
    store.save_route_candidate(
        RouteCandidate(
            route_id=route.route_id,
            provider_id="mock",
            model_id="mock-v1",
            rank=1,
            score=42,
            score_components={"capability_fit": 30, "privacy_fit": 12},
            eligible=True,
            reasons=["available"],
        )
    )
    execution = ChatExecution(
        request_id="req-1",
        route_id=route.route_id,
        conversation_id=conversation.conversation_id,
        provider_id="mock",
        model_id="mock-v1",
    )
    store.save_execution(execution)
    memory = MemoryEntry(
        content="Prefer inspectable routes",
        source_type="explicit",
        reason="User asked OpenCobalt to remember it",
        scope="user",
        status="proposed",
        conversation_id=conversation.conversation_id,
        source_message_id=message.message_id,
    )
    store.save_memory(memory)
    skill = SkillRecord(
        name="file-reader",
        description="Read a local file",
        source_kind="builtin",
        source_ref="opencobalt.skills.file_reader",
        trust_level="builtin",
    )
    store.save_skill(skill)

    reopened = PersonalAIStore(tmp_path / "ledger.db")
    assert reopened.get_route(route.route_id).selected_provider == "mock"
    assert reopened.list_route_candidates(route.route_id)[0].score_components == {
        "capability_fit": 30,
        "privacy_fit": 12,
    }
    assert reopened.get_execution(execution.execution_id).status == "queued"
    assert reopened.list_memory()[0].reason == "User asked OpenCobalt to remember it"
    assert reopened.list_skills()[0].source_kind == "builtin"


def test_foreign_keys_reject_orphan_messages(tmp_path):
    store = PersonalAIStore(tmp_path / "ledger.db")

    with pytest.raises(sqlite3.IntegrityError):
        store.add_message("missing-conversation", role="user", content="orphan")


def test_update_message_revalidates_content_and_status(tmp_path):
    store = PersonalAIStore(tmp_path / "ledger.db")
    conversation = store.create_conversation()
    message = store.add_message(conversation.conversation_id, role="user", content="valid")

    with pytest.raises(ValueError, match="content cannot be blank"):
        store.update_message(message.message_id, content="   ")
    with pytest.raises(ValueError, match="status"):
        store.update_message(message.message_id, status="invented")

    assert store.list_messages(conversation.conversation_id)[0].content == "valid"


def test_v2_migration_rebuilds_pre_fix_tables_without_losing_records(tmp_path):
    db_path = tmp_path / "ledger.db"
    store = PersonalAIStore(db_path)
    ensure_builtin_personas(store)
    conversation = store.create_conversation(title="Legacy conversation")
    message = store.add_message(conversation.conversation_id, role="user", content="Legacy text")
    route = RouteRecord(
        request_id="legacy-request",
        conversation_id=conversation.conversation_id,
        request_message_id=message.message_id,
        task_class="general_reasoning",
        selected_provider="mock",
        requested_persona_id="analytical",
        actual_persona_id="analytical",
        privacy_classification="private",
        autonomy_level="answer_only",
        route_score=10,
    )
    store.save_route(route)
    store.update_message(message.message_id, route_id=route.route_id)
    skill = SkillRecord(
        name="legacy-skill",
        description="Preserved by migration",
        source_kind="user",
        source_ref="local",
    )
    store.save_skill(skill)

    with sqlite3.connect(db_path) as conn:
        _downgrade_to_true_v1_schema(conn)

    reopened = PersonalAIStore(db_path)
    reopened_again = PersonalAIStore(db_path)

    assert reopened.get_conversation(conversation.conversation_id) is not None
    assert reopened.list_messages(conversation.conversation_id)[0].route_id == route.route_id
    assert reopened.get_route(route.route_id).request_id == "legacy-request"
    assert reopened.list_skills()[0].name == "legacy-skill"
    assert reopened_again.get_route(route.route_id).request_id == "legacy-request"
    with pytest.raises(sqlite3.IntegrityError):
        reopened.update_message(message.message_id, route_id="missing-route")
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT version FROM personal_ai_schema_versions ORDER BY version"
        ).fetchall() == [(1,), (2,)]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert {
            (row[3], row[2], row[4])
            for row in conn.execute("PRAGMA foreign_key_list(chat_messages)").fetchall()
        } >= {("route_id", "ai_route_decisions", "route_id")}


def test_v2_migration_rolls_back_schema_and_version_when_integrity_check_fails(tmp_path):
    db_path = tmp_path / "ledger.db"
    store = PersonalAIStore(db_path)
    conversation = store.create_conversation(title="Corrupt v1 fixture")
    message = store.add_message(conversation.conversation_id, role="user", content="Keep me")

    with sqlite3.connect(db_path) as conn:
        _downgrade_to_true_v1_schema(conn)
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO ai_route_candidates "
            "(candidate_id, route_id, provider_id, model_id, runtime_id, rank, score, "
            "score_components_json, eligible, reasons_json, rejection_reason, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "orphan-candidate",
                "missing-route",
                "mock",
                "mock-v1",
                "mock",
                1,
                1,
                "{}",
                1,
                "[]",
                None,
                "2026-08-01T00:00:00+00:00",
            ),
        )

    with pytest.raises(sqlite3.IntegrityError, match="migration left foreign key violations"):
        PersonalAIStore(db_path)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT version FROM personal_ai_schema_versions ORDER BY version"
        ).fetchall() == [(1,)]
        assert (
            "route_id",
            "ai_route_decisions",
            "route_id",
        ) not in {
            (row[3], row[2], row[4])
            for row in conn.execute("PRAGMA foreign_key_list(chat_messages)").fetchall()
        }
        assert conn.execute(
            "SELECT COUNT(*) FROM chat_messages WHERE message_id = ?", (message.message_id,)
        ).fetchone()[0] == 1
