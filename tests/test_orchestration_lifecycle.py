"""Request lifecycle: route-selected must start the provider promptly."""

from __future__ import annotations

from opencobalt.personal_ai.service import ChatRequest
from tests.test_chat_service import _real_mock_service


def test_route_leaves_planned_before_provider_returns(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Lifecycle")
    stream = iter(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain receipt provenance",
                provider_override="mock",
            )
        )
    )
    selected = next(
        event for event in stream if event.event_type == "route_selected"
    )
    route = store.get_route(selected.route_id)
    assert route is not None
    assert route.outcome_status != "planned"
    assert route.outcome_status in {"starting", "running"}
    assert route.metadata.get("lifecycle", {}).get("phase") in {
        "starting_provider",
        "running",
    }

    started = next(
        event for event in stream if event.event_type == "provider_started"
    )
    assert started.payload.get("phase_label", "").startswith("Provider running")
    running = store.get_route(selected.route_id)
    assert running is not None
    assert running.outcome_status == "running"

    remaining = list(stream)
    assert remaining[-1].event_type == "completed"
    finished = store.get_route(selected.route_id)
    assert finished is not None
    assert finished.outcome_status == "complete"
    timings = finished.metadata.get("lifecycle", {}).get("timings") or {}
    assert "total_ms" in timings


def test_provider_started_is_emitted_before_execute_returns(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Started first")
    provider = service.providers.get("mock")
    original = provider.execute
    execute_saw_started = {}

    def wrapped(request, cancellation=None):
        routes = store.list_routes(conversation_id=conversation.conversation_id)
        execute_saw_started["outcome"] = routes[0].outcome_status if routes else None
        execute_saw_started["phase"] = (
            routes[0].metadata.get("lifecycle", {}).get("phase") if routes else None
        )
        return original(request, cancellation)

    provider.execute = wrapped
    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain this",
                provider_override="mock",
            )
        )
    )
    types = [event.event_type for event in events]
    assert types.index("provider_started") < types.index("completed")
    assert execute_saw_started["outcome"] in {"starting", "running"}
    assert execute_saw_started["phase"] in {"starting_provider", "running"}


def test_pre_execution_failure_is_durable_failed_not_planned(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Blocked")
    provider = service.providers.get("mock")

    def boom(request, cancellation=None):
        from opencobalt.personal_ai.providers import _pre_execution_error

        return _pre_execution_error(
            request,
            "mock",
            category="unavailable",
            message="provider disappeared after routing",
            status="unavailable",
        )

    provider.execute = boom
    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain this",
                provider_override="mock",
            )
        )
    )
    assert events[-1].event_type == "error"
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.outcome_status == "failed"
    assert route.outcome_status != "planned"
    messages = store.list_messages(conversation.conversation_id)
    assert messages[-1].status == "failed"
