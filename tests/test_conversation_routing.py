"""Conversation-scoped manual routing presets persist independently per chat."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from opencobalt.api_server import app
from opencobalt.personal_ai.conversation_routing import (
    ConversationRoutingUpdate,
    apply_routing_update,
    default_conversation_routing,
    parse_conversation_routing,
)
from opencobalt.personal_ai.models import AISettings
from opencobalt.personal_ai.router import PersonalAIRouter, classify_task
from opencobalt.personal_ai.store import PersonalAIStore
from tests.test_personal_ai_router import _cheap_local, _request, _strong_cloud


def _store(tmp_path: Path) -> PersonalAIStore:
    return PersonalAIStore(tmp_path / "ledger.db")


def test_new_conversation_defaults_to_automatic_without_inheriting_manual_state(tmp_path):
    store = _store(tmp_path)
    first = store.create_conversation(
        title="A",
        metadata={"routing": {"mode": "manual", "manual_preset": {"provider_id": "mock"}}},
    )
    second = store.create_conversation(title="B")
    settings = store.get_settings()
    assert parse_conversation_routing(first.metadata, settings).mode == "manual"
    parsed = parse_conversation_routing(second.metadata, settings)
    assert parsed.mode == "automatic"
    assert parsed.manual_preset.provider_id is None


def test_service_create_uses_settings_defaults_not_another_chat(tmp_path):
    from tests.test_chat_service import _real_mock_service

    service, store, _ = _real_mock_service(tmp_path)
    store.save_settings(AISettings(default_routing_mode="automatic", privacy_policy="private"))
    first = service.create_conversation(title="A")
    service.update_conversation_routing(
        first.conversation_id,
        ConversationRoutingUpdate(mode="manual", provider_id="mock", model_id="mock-v1"),
    )
    second = service.create_conversation(title="B")
    assert service.conversation_routing(first.conversation_id).mode == "manual"
    routing = service.conversation_routing(second.conversation_id)
    assert routing.mode == "automatic"
    assert routing.manual_preset.provider_id is None
    assert routing.privacy_mode == "private"


def test_manual_automatic_manual_restores_same_conversation_preset(tmp_path):
    store = _store(tmp_path)
    current = default_conversation_routing()
    current = apply_routing_update(
        current,
        ConversationRoutingUpdate(
            mode="manual",
            provider_id="antigravity",
            model_id="claude-sonnet-4-6",
            reasoning_effort="high",
            allow_fallback=True,
            privacy_mode="sensitive",
            local_only=False,
        ),
    )
    automatic = apply_routing_update(current, ConversationRoutingUpdate(mode="automatic"))
    restored = apply_routing_update(automatic, ConversationRoutingUpdate(mode="manual"))
    assert automatic.mode == "automatic"
    assert automatic.manual_preset.provider_id == "antigravity"
    assert automatic.manual_preset.model_id == "claude-sonnet-4-6"
    assert restored.mode == "manual"
    assert restored.manual_preset.provider_id == "antigravity"
    assert restored.manual_preset.model_id == "claude-sonnet-4-6"
    assert restored.reasoning_effort == "high"
    assert restored.allow_fallback is True
    assert restored.privacy_mode == "sensitive"

    conversation = store.create_conversation(title="A")
    saved = store.save_conversation_routing(conversation.conversation_id, automatic)
    reopened = PersonalAIStore(store.db_path)
    loaded = parse_conversation_routing(
        reopened.get_conversation(saved.conversation_id).metadata,
        reopened.get_settings(),
    )
    assert loaded.mode == "automatic"
    assert loaded.manual_preset.provider_id == "antigravity"
    restored_live = apply_routing_update(loaded, ConversationRoutingUpdate(mode="manual"))
    assert restored_live.manual_preset.model_id == "claude-sonnet-4-6"


def test_switching_conversations_does_not_leak_manual_state(tmp_path):
    from tests.test_chat_service import _real_mock_service

    service, store, _ = _real_mock_service(tmp_path)
    conversation_a = service.create_conversation(title="A")
    conversation_b = service.create_conversation(title="B")
    service.update_conversation_routing(
        conversation_a.conversation_id,
        ConversationRoutingUpdate(mode="manual", provider_id="mock", model_id="mock-v1"),
    )
    service.update_conversation_routing(
        conversation_b.conversation_id,
        ConversationRoutingUpdate(mode="automatic"),
    )
    assert service.conversation_routing(conversation_a.conversation_id).mode == "manual"
    assert service.conversation_routing(conversation_b.conversation_id).mode == "automatic"
    service.update_conversation_routing(
        conversation_a.conversation_id,
        ConversationRoutingUpdate(model_id="mock-other"),
    )
    assert (
        service.conversation_routing(conversation_b.conversation_id).manual_preset.model_id is None
    )
    assert (
        service.conversation_routing(conversation_a.conversation_id).manual_preset.model_id
        == "mock-other"
    )


def test_two_manual_conversations_keep_distinct_providers(tmp_path):
    from tests.test_chat_service import _real_mock_service

    service, _, _ = _real_mock_service(tmp_path)
    conversation_a = service.create_conversation(title="A")
    conversation_b = service.create_conversation(title="B")
    service.update_conversation_routing(
        conversation_a.conversation_id,
        ConversationRoutingUpdate(mode="manual", provider_id="mock", model_id="mock-v1"),
    )
    service.update_conversation_routing(
        conversation_b.conversation_id,
        ConversationRoutingUpdate(mode="manual", provider_id="ollama", model_id="llama3.2"),
    )
    routing_a = service.conversation_routing(conversation_a.conversation_id)
    routing_b = service.conversation_routing(conversation_b.conversation_id)
    assert routing_a.manual_preset.provider_id == "mock"
    assert routing_b.manual_preset.provider_id == "ollama"


def test_routing_survives_store_restart_and_is_not_a_global_default(tmp_path):
    db_path = tmp_path / "ledger.db"
    first = PersonalAIStore(db_path)
    conversation = first.create_conversation(title="Keep me")
    first.save_conversation_routing(
        conversation.conversation_id,
        apply_routing_update(
            default_conversation_routing(),
            ConversationRoutingUpdate(
                mode="manual",
                provider_id="mock",
                local_only=True,
                allow_fallback=False,
            ),
        ),
    )
    first.save_settings(AISettings(default_routing_mode="automatic"))
    second = PersonalAIStore(db_path)
    loaded = parse_conversation_routing(
        second.get_conversation(conversation.conversation_id).metadata,
        second.get_settings(),
    )
    created = second.create_conversation(title="Fresh")
    fresh = parse_conversation_routing(created.metadata, second.get_settings())
    assert loaded.mode == "manual"
    assert loaded.manual_preset.provider_id == "mock"
    assert loaded.local_only is True
    assert fresh.mode == "automatic"
    assert fresh.manual_preset.provider_id is None
    assert second.get_settings().default_routing_mode == "automatic"


def test_delete_conversation_does_not_leak_preset_into_others(tmp_path):
    store = _store(tmp_path)
    conversation_a = store.create_conversation(title="A")
    conversation_b = store.create_conversation(title="B")
    store.save_conversation_routing(
        conversation_a.conversation_id,
        apply_routing_update(
            default_conversation_routing(),
            ConversationRoutingUpdate(mode="manual", provider_id="mock"),
        ),
    )
    store.save_conversation_routing(
        conversation_b.conversation_id,
        apply_routing_update(
            default_conversation_routing(),
            ConversationRoutingUpdate(mode="automatic"),
        ),
    )
    assert store.delete_conversation(conversation_a.conversation_id) is True
    assert store.get_conversation(conversation_a.conversation_id) is None
    remaining = parse_conversation_routing(
        store.get_conversation(conversation_b.conversation_id).metadata,
        store.get_settings(),
    )
    assert remaining.mode == "automatic"
    assert remaining.manual_preset.provider_id is None
    created = store.create_conversation(title="C")
    assert parse_conversation_routing(created.metadata, store.get_settings()).mode == "automatic"


def test_existing_database_without_routing_metadata_is_backward_compatible(tmp_path):
    store = _store(tmp_path)
    conversation = store.create_conversation(title="Legacy", metadata={"acp_session_id": "sess-1"})
    parsed = parse_conversation_routing(conversation.metadata, store.get_settings())
    assert parsed.mode == "automatic"
    saved = store.save_conversation_routing(
        conversation.conversation_id,
        apply_routing_update(parsed, ConversationRoutingUpdate(mode="manual", provider_id="mock")),
    )
    assert saved.metadata["acp_session_id"] == "sess-1"
    assert saved.metadata["routing"]["mode"] == "manual"


def test_malformed_routing_metadata_falls_back_to_defaults(tmp_path):
    parsed = parse_conversation_routing(
        {"routing": {"mode": "not-a-mode", "provider_id": 12}},
        AISettings(),
    )
    assert parsed == default_conversation_routing()


def test_stale_provider_and_model_are_preserved_not_substituted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENCOBALT_ENABLE_DEVELOPMENT_MOCK", "1")
    with TestClient(app) as client:
        created = client.post("/api/v1/conversations", json={"title": "Stale"}).json()
        conversation_id = created["conversation_id"]
        patched = client.patch(
            f"/api/v1/conversations/{conversation_id}/routing",
            json={
                "mode": "manual",
                "provider_id": "vanished-cloud",
                "model_id": "ghost-model",
            },
        )
        assert patched.status_code == 200
        body = patched.json()
        assert body["provider_id"] == "vanished-cloud"
        assert body["model_id"] == "ghost-model"
        assert body["provider_status"] == "unavailable"
        assert "registry" in (body["provider_unavailable_reason"] or "")
        automatic = client.patch(
            f"/api/v1/conversations/{conversation_id}/routing",
            json={"mode": "automatic"},
        ).json()
        assert automatic["mode"] == "automatic"
        assert automatic["provider_id"] == "vanished-cloud"
        restored = client.patch(
            f"/api/v1/conversations/{conversation_id}/routing",
            json={"mode": "manual"},
        ).json()
        assert restored["provider_id"] == "vanished-cloud"
        assert restored["model_id"] == "ghost-model"


def test_api_presets_are_isolated_across_reload_and_new_chats(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENCOBALT_ENABLE_DEVELOPMENT_MOCK", "1")
    with TestClient(app) as client:
        conversation_a = client.post("/api/v1/conversations", json={"title": "A"}).json()
        conversation_b = client.post("/api/v1/conversations", json={"title": "B"}).json()
        assert (
            client.patch(
                f"/api/v1/conversations/{conversation_a['conversation_id']}/routing",
                json={
                    "mode": "manual",
                    "provider_id": "mock",
                    "model_id": "mock-v1",
                    "reasoning_effort": "high",
                    "allow_fallback": True,
                    "privacy_mode": "private",
                    "local_only": True,
                },
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/v1/conversations/{conversation_b['conversation_id']}/routing"
            ).json()["mode"]
            == "automatic"
        )

    with TestClient(app) as reloaded:
        routing_a = reloaded.get(
            f"/api/v1/conversations/{conversation_a['conversation_id']}/routing"
        ).json()
        routing_b = reloaded.get(
            f"/api/v1/conversations/{conversation_b['conversation_id']}/routing"
        ).json()
        created = reloaded.post("/api/v1/conversations", json={"title": "C"}).json()
        routing_c = reloaded.get(
            f"/api/v1/conversations/{created['conversation_id']}/routing"
        ).json()
        assert routing_a["mode"] == "manual"
        assert routing_a["provider_id"] == "mock"
        assert routing_a["model_id"] == "mock-v1"
        assert routing_a["allow_fallback"] is True
        assert routing_a["local_only"] is True
        assert routing_a["privacy_mode"] == "private"
        assert routing_b["mode"] == "automatic"
        assert routing_b["provider_id"] is None
        assert routing_c["mode"] == "automatic"
        assert routing_c["provider_id"] is None


def test_unavailable_mock_model_is_preserved_when_catalog_lacks_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENCOBALT_ENABLE_DEVELOPMENT_MOCK", "1")
    with TestClient(app) as client:
        created = client.post("/api/v1/conversations", json={"title": "Missing model"}).json()
        body = client.patch(
            f"/api/v1/conversations/{created['conversation_id']}/routing",
            json={"mode": "manual", "provider_id": "mock", "model_id": "not-a-real-mock-model"},
        ).json()
        assert body["provider_id"] == "mock"
        assert body["model_id"] == "not-a-real-mock-model"
        assert body["model_status"] == "unavailable"
        assert "catalog" in (body["model_unavailable_reason"] or "")


def test_manual_override_from_stored_preset_does_not_change_task_or_authority():
    prompt = "Explain why DNS caching improves performance in three sentences."
    automatic = PersonalAIRouter().route(_request(prompt), [_cheap_local(), _strong_cloud()])
    overridden = PersonalAIRouter().route(
        _request(prompt, provider_override="antigravity", model_override="antigravity-model"),
        [_cheap_local(), _strong_cloud()],
    )
    assert classify_task(prompt) == "general_reasoning"
    assert overridden.task_class == automatic.task_class
    assert overridden.record.autonomy_level == "answer_only"
    assert overridden.requirements.mutation_authority == "none"
    assert overridden.record.approval_requirements == automatic.record.approval_requirements


def test_fallback_and_local_only_are_conversation_fields_not_global(tmp_path):
    from tests.test_chat_service import _real_mock_service

    service, store, _ = _real_mock_service(tmp_path)
    store.save_settings(AISettings(local_only_default=False))
    conversation_a = service.create_conversation(title="A")
    conversation_b = service.create_conversation(title="B")
    service.update_conversation_routing(
        conversation_a.conversation_id,
        ConversationRoutingUpdate(local_only=True, allow_fallback=True),
    )
    routing_b = service.conversation_routing(conversation_b.conversation_id)
    assert service.conversation_routing(conversation_a.conversation_id).local_only is True
    assert service.conversation_routing(conversation_a.conversation_id).allow_fallback is True
    assert routing_b.local_only is False
    assert routing_b.allow_fallback is False
    assert store.get_settings().local_only_default is False
