"""Bounded deterministic arithmetic and conversion path."""

from __future__ import annotations

from opencobalt.personal_ai.deterministic import try_deterministic
from opencobalt.personal_ai.service import ChatRequest
from tests.test_chat_service import _real_mock_service


def test_try_deterministic_arithmetic_and_conversions():
    assert try_deterministic("What is 17 times 23").display == "391"
    assert try_deterministic("9 * 4").display == "36"
    assert try_deterministic("15 percent of 80").display == "12"
    converted = try_deterministic("Convert 32 fahrenheit to celsius")
    assert converted is not None
    assert converted.display.startswith("0")
    assert try_deterministic("Explain TCP versus UDP") is None
    assert try_deterministic("summarize this document") is None
    assert try_deterministic("rm -rf /") is None


def test_chat_arithmetic_uses_deterministic_provider(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Arithmetic")
    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="What is 17 times 23",
            )
        )
    )
    assert events[-1].event_type == "completed"
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.selected_provider == "deterministic"
    assert route.metadata.get("capability_role") == "cheap_local"
    assert store.list_messages(conversation.conversation_id)[-1].content == "391"
    assert route.receipt_id is not None
