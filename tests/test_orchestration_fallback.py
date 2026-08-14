"""Fallback and escalation: bounded, inspectable, constraint-preserving."""

from __future__ import annotations

from opencobalt.personal_ai.providers import ProviderRegistry
from opencobalt.personal_ai.service import ChatRequest, ChatService
from opencobalt.personal_ai.store import PersonalAIStore
from tests.test_chat_service import FakeEngine, _adapters, _outcome, _real_mock_service


def test_unavailable_provider_falls_back_to_a_different_provider(tmp_path):
    engine = FakeEngine(
        _outcome(status="failed", error="authentication failed", receipt_id="receipt-first"),
        _outcome(stdout="fallback answer", receipt_id="receipt-second"),
    )
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters=_adapters(codex=True, antigravity=True),
            executable_finder=lambda _name: None,
        ),
        enable_mock=True,
    )
    conversation = service.create_conversation(title="Fallback")
    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain the decision",
                allow_fallback=True,
            )
        )
    )
    assert any(event.event_type == "fallback_started" for event in events)
    assert events[-1].event_type == "completed"
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.fallback_events
    assert route.fallback_events[0]["from_provider"] != route.fallback_events[0]["to_provider"]
    assert route.metadata.get("actual_provider_id") != route.fallback_events[0]["from_provider"]


def test_fallback_disabled_does_not_retry(tmp_path):
    engine = FakeEngine(
        _outcome(status="failed", error="authentication failed", receipt_id="receipt-first"),
        _outcome(stdout="must not run", receipt_id="receipt-second"),
    )
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters=_adapters(antigravity=True),
            executable_finder=lambda _name: None,
        ),
        enable_mock=True,
    )
    conversation = service.create_conversation(title="No fallback")
    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain the decision",
                provider_override="antigravity",
                allow_fallback=False,
            )
        )
    )
    assert events[-1].event_type == "error"
    assert not any(event.event_type == "fallback_started" for event in events)
    assert len(engine.calls) == 1
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.outcome_status == "failed"
    assert route.fallback_events == []


def test_local_only_does_not_fallback_to_network(tmp_path):
    engine = FakeEngine()
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters=_adapters(antigravity=True),
            executable_finder=lambda _name: None,
        ),
        enable_mock=False,
    )
    conversation = service.create_conversation(title="Local only")
    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain this concept",
                local_only=True,
                allow_fallback=True,
            )
        )
    )
    assert events[-1].event_type == "route_failed"
    assert engine.calls == []
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.outcome_status == "policy_denied"


def test_cancellation_does_not_fallback(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Cancel")
    stream = iter(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Produce enough output to cancel between chunks",
                provider_override="mock",
                allow_fallback=True,
            )
        )
    )
    started = next(event for event in stream if event.event_type == "execution_started")
    assert service.cancel(started.execution_id) is True
    remaining = list(stream)
    assert remaining[-1].event_type == "cancelled"
    assert not any(event.event_type == "fallback_started" for event in remaining)
    route = store.get_route(started.route_id)
    assert route is not None and route.outcome_status == "cancelled"
