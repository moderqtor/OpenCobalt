"""First-message conversation titles for daily Chat."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opencobalt.api_server import app
from opencobalt.personal_ai.models import DEFAULT_CONVERSATION_TITLE, derive_conversation_title
from opencobalt.personal_ai.service import ChatRequest
from opencobalt.personal_ai.store import PersonalAIStore
from tests.test_chat_service import _real_mock_service


def test_derive_conversation_title_uses_first_line_without_a_model_call():
    assert derive_conversation_title("") == DEFAULT_CONVERSATION_TITLE
    assert derive_conversation_title("  What is 17 times 23?  ") == "What is 17 times 23?"
    long_title = derive_conversation_title(" ".join(["alpha"] * 40))
    assert long_title.endswith("…")
    assert len(long_title) <= 73


def test_store_can_patch_title_and_project_path(tmp_path: Path):
    store = PersonalAIStore(tmp_path / "ledger.db")
    created = store.create_conversation(title=DEFAULT_CONVERSATION_TITLE)
    updated = store.update_conversation(created.conversation_id, title="DNS caching")
    assert updated.title == "DNS caching"
    assert updated.project_path is None
    with_path = store.update_conversation(created.conversation_id, project_path=str(tmp_path))
    assert with_path.title == "DNS caching"
    assert with_path.project_path == str(tmp_path)


def test_first_chat_message_renames_default_title(tmp_path: Path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation()
    assert conversation.title == DEFAULT_CONVERSATION_TITLE
    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain DNS caching in three sentences.",
            )
        )
    )
    accepted = next(event for event in events if event.event_type == "request_accepted")
    assert accepted.payload["conversation_title"] == "Explain DNS caching in three sentences."
    stored = store.get_conversation(conversation.conversation_id)
    assert stored is not None
    assert stored.title == "Explain DNS caching in three sentences."


def test_explicit_title_is_not_overwritten_by_the_first_message(tmp_path: Path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Keep this title")
    list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="A later goal should not rename this conversation.",
            )
        )
    )
    stored = store.get_conversation(conversation.conversation_id)
    assert stored is not None
    assert stored.title == "Keep this title"


def test_api_patch_conversation_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENCOBALT_ENABLE_DEVELOPMENT_MOCK", "1")
    with TestClient(app) as client:
        created = client.post("/api/v1/conversations", json={"title": "New conversation"}).json()
        patched = client.patch(
            f"/api/v1/conversations/{created['conversation_id']}",
            json={"title": "Named later"},
        )
        assert patched.status_code == 200
        assert patched.json()["title"] == "Named later"
        blank = client.patch(
            f"/api/v1/conversations/{created['conversation_id']}",
            json={"title": "   "},
        )
        assert blank.status_code == 422
