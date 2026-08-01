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
from opencobalt.personal_ai.store import PersonalAIStore


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
        foreign_keys = conn.execute("PRAGMA foreign_key_list(chat_messages)").fetchall()

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
    assert versions == [(1,)]
    assert any(row[2] == "conversations" for row in foreign_keys)


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

