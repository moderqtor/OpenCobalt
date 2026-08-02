from __future__ import annotations

from types import SimpleNamespace

import pytest

from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.models import RuntimeCapabilitySnapshot
from opencobalt.execution.runner import ProcessRunner
from opencobalt.execution.store import ExecutionStore
from opencobalt.personal_ai.providers import ProviderRegistry
from opencobalt.personal_ai.router import PersonalAIRouter
from opencobalt.personal_ai.service import ChatRequest, ChatService
from opencobalt.personal_ai.store import PersonalAIStore


class FakeAdapter:
    def __init__(
        self,
        runtime_id: str,
        *,
        available: bool = False,
        requires_network: bool = True,
    ) -> None:
        self.runtime_id = runtime_id
        self.display_name = runtime_id
        self.executable = runtime_id
        self.available = available
        self.requires_network = requires_network

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path=f"/test/{self.executable}" if self.available else None,
            available=self.available,
            capabilities=["completion"] if self.available else [],
            supported_artifact_types=["stdout", "stderr"],
            supports_dry_run=True,
            supports_noninteractive=self.available,
            supports_json_output=False,
            requires_network=self.requires_network,
            requires_credentials=self.requires_network,
            max_safe_risk="yellow",
            limitations=[],
            verifiability_level="partial" if self.available else "unavailable",
            capability_details={},
        ).with_hash()

    def build_command(self, task, options=None):
        return [self.executable, task]

    def supports_non_interactive(self):
        return self.available

    def default_timeout_seconds(self):
        return 30

    def risk_for_task(self, task):
        return "green"


class FakeEngine:
    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = []

    def run_task(self, task, **kwargs):
        self.calls.append((task, kwargs))
        if not self.outcomes:
            raise AssertionError("unexpected provider execution")
        return self.outcomes.pop(0)


def _outcome(*, status="succeeded", stdout="", receipt_id="receipt-test", error=None):
    return SimpleNamespace(
        result=SimpleNamespace(
            status=status,
            stdout_preview=stdout,
            stderr_preview="",
            error=error,
            usage=None,
        ),
        receipt=SimpleNamespace(receipt_id=receipt_id, limitations=[]),
        policy=SimpleNamespace(allowed=True, reason="allowed"),
    )


def _adapters(*, codex=False, antigravity=False):
    return {
        "codex-cli": FakeAdapter("codex-cli", available=codex),
        "google-antigravity": FakeAdapter(
            "google-antigravity", available=antigravity
        ),
        "claude-code": FakeAdapter("claude-code"),
        "ollama": FakeAdapter("ollama", requires_network=False),
    }


def _real_mock_service(tmp_path):
    db_path = tmp_path / "ledger.db"
    store = PersonalAIStore(db_path)
    execution_store = ExecutionStore(db_path)
    engine = ExecutionEngine(
        store=execution_store,
        runner=ProcessRunner(artifact_dir=tmp_path / "artifacts"),
        events_path=tmp_path / "execution.jsonl",
    )
    providers = ProviderRegistry(
        engine,
        adapters=_adapters(),
        executable_finder=lambda _name: None,
    )
    service = ChatService(
        store=store,
        providers=providers,
        router=PersonalAIRouter(),
        enable_mock=True,
    )
    return service, store, execution_store


def test_chat_request_rejects_ambiguous_or_unsafe_override_identifiers():
    with pytest.raises(ValueError, match="model override requires"):
        ChatRequest(
            conversation_id="conv-test",
            message="hello",
            model_override="model-v1",
        )
    with pytest.raises(ValueError, match="tool and skill identifiers"):
        ChatRequest(
            conversation_id="conv-test",
            message="hello",
            requested_tools=["--unsafe"],
        )


def test_engine_backed_mock_chat_persists_messages_route_execution_and_receipt(tmp_path):
    service, store, execution_store = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Inspect the route")

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain receipt provenance",
                persona_id="analytical",
                cognitive_policy="deep_analysis",
                provider_override="mock",
            )
        )
    )

    assert [event.event_type for event in events[:3]] == [
        "request_accepted",
        "route_selected",
        "execution_started",
    ]
    assert any(event.event_type == "text_delta" for event in events)
    assert events[-1].event_type == "completed"
    messages = store.list_messages(conversation.conversation_id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[-1].content == "Mock response: Explain receipt provenance"
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.selected_provider == "mock"
    assert route.requested_persona_id == "analytical"
    assert route.actual_persona_id == "analytical"
    assert route.receipt_id is not None
    assert route.metadata["verification"]["status"] == "passed"
    assert messages[-1].route_id == route.route_id
    receipt = execution_store.get_receipt(route.receipt_id)
    assert receipt is not None
    plan = execution_store.get_plan(receipt.plan_id)
    assert plan is not None
    assert "Interaction persona: analytical" in plan.task
    assert "Cognitive policy: deep_analysis" in plan.task
    execution = store.list_executions(conversation_id=conversation.conversation_id)[0]
    assert execution.status == "complete"
    assert execution.work_receipt_id == route.receipt_id
    persisted_events = store.list_stream_events(execution.execution_id)
    assert [event.event_type for event in persisted_events[:3]] == [
        "request_accepted",
        "route_selected",
        "execution_started",
    ]
    assert persisted_events[-1].event_type == "completed"


def test_conversation_and_routes_survive_service_restart(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Restart proof")
    list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Persist this response",
                provider_override="mock",
            )
        )
    )

    reopened = PersonalAIStore(store.db_path)

    assert reopened.get_conversation(conversation.conversation_id) is not None
    assert len(reopened.list_messages(conversation.conversation_id)) == 2
    assert reopened.list_routes(conversation_id=conversation.conversation_id)[0].receipt_id


def test_provider_policy_context_is_bounded_before_execution(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Bounded context")
    for index in range(12):
        store.add_message(
            conversation.conversation_id,
            role="user" if index % 2 == 0 else "assistant",
            content=f"history-{index}: " + ("x" * 10_000),
        )

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Summarize the bounded context",
                provider_override="mock",
            )
        )
    )

    assert events[-1].event_type == "completed"


def test_task_specific_verifier_is_not_claimed_when_only_integrity_was_checked(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Honest verification")

    list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Write a small parser",
                persona_id="builder",
                provider_override="mock",
            )
        )
    )

    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.verification_strategy == "tests_and_diff"
    assert route.metadata["verification"]["status"] == "not_performed"
    assert route.metadata["verification"]["integrity_check"] == "passed"


def test_development_mock_is_used_only_when_no_real_provider_is_routable(tmp_path):
    mock_service, mock_store, _ = _real_mock_service(tmp_path / "mock-only")
    conversation = mock_service.create_conversation(title="Automatic development route")

    list(
        mock_service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain this concept",
            )
        )
    )

    assert mock_store.list_routes(conversation_id=conversation.conversation_id)[0].selected_provider == "mock"

    engine = FakeEngine(_outcome(stdout="real response", receipt_id="receipt-real"))
    real_store = PersonalAIStore(tmp_path / "real" / "ledger.db")
    real_service = ChatService(
        store=real_store,
        providers=ProviderRegistry(
            engine,
            adapters=_adapters(codex=True),
            executable_finder=lambda _name: None,
        ),
        enable_mock=True,
    )
    real_conversation = real_service.create_conversation(title="Real route")

    list(
        real_service.stream_request(
            ChatRequest(
                conversation_id=real_conversation.conversation_id,
                message="Explain this concept",
            )
        )
    )

    assert real_store.list_routes(conversation_id=real_conversation.conversation_id)[0].selected_provider == "codex"
    assert engine.calls[0][1]["runtime"] == "codex-cli"


def test_durable_cancellation_stops_mock_stream_and_marks_execution(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Cancellation")
    stream = iter(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Produce enough output to cancel between chunks",
                provider_override="mock",
            )
        )
    )
    assert next(stream).event_type == "request_accepted"
    assert next(stream).event_type == "route_selected"
    started = next(stream)
    assert started.event_type == "execution_started"

    assert service.cancel(started.execution_id) is True
    assert service.cancel(started.execution_id) is False
    remaining = list(stream)

    assert remaining[-1].event_type == "cancelled"
    assert store.get_execution(started.execution_id).status == "cancelled"
    assert service.cancel("missing-execution") is False


def test_local_only_manual_cloud_route_is_denied_without_provider_execution(tmp_path):
    db_path = tmp_path / "ledger.db"
    engine = FakeEngine()
    store = PersonalAIStore(db_path)
    providers = ProviderRegistry(
        engine,
        adapters=_adapters(codex=True),
        executable_finder=lambda _name: None,
    )
    service = ChatService(store=store, providers=providers, enable_mock=False)
    conversation = service.create_conversation(title="Local only")

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain this concept",
                provider_override="codex",
                local_only=True,
            )
        )
    )

    assert events[-1].event_type == "route_failed"
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.outcome_status == "policy_denied"
    assert route.selected_provider == "none"
    assert route.receipt_id is None
    assert "local-only" in " ".join(route.reasons)
    assert store.list_route_candidates(route.route_id)[0].eligible is False
    assert engine.calls == []


def test_explicit_fallback_is_visible_persisted_and_uses_second_ranked_route(tmp_path):
    engine = FakeEngine(
        _outcome(status="failed", error="authentication failed", receipt_id="receipt-first"),
        _outcome(stdout="fallback answer", receipt_id="receipt-second"),
    )
    store = PersonalAIStore(tmp_path / "ledger.db")
    providers = ProviderRegistry(
        engine,
        adapters=_adapters(codex=True, antigravity=True),
        executable_finder=lambda _name: None,
    )
    service = ChatService(store=store, providers=providers, enable_mock=False)
    conversation = service.create_conversation(title="Visible fallback")

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain the decision",
                persona_id="analytical",
                allow_fallback=True,
            )
        )
    )

    assert any(event.event_type == "fallback_started" for event in events)
    assert events[-1].event_type == "completed"
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.selected_provider == "codex"
    assert route.fallback_events[0]["from_provider"] == "codex"
    assert route.fallback_events[0]["to_provider"] == "antigravity"
    assert route.receipt_id == "receipt-second"
    assert route.metadata["actual_provider_id"] == "antigravity"
    attempts = store.list_executions(request_id=route.request_id)
    assert {attempt.provider_id for attempt in attempts} == {"codex", "antigravity"}
    assert {attempt.work_receipt_id for attempt in attempts} == {
        "receipt-first",
        "receipt-second",
    }
    assert len(engine.calls) == 2


def test_provider_failure_never_falls_back_without_request_permission(tmp_path):
    engine = FakeEngine(
        _outcome(status="failed", error="authentication failed", receipt_id="receipt-first")
    )
    store = PersonalAIStore(tmp_path / "ledger.db")
    providers = ProviderRegistry(
        engine,
        adapters=_adapters(codex=True, antigravity=True),
        executable_finder=lambda _name: None,
    )
    service = ChatService(store=store, providers=providers, enable_mock=False)
    conversation = service.create_conversation(title="No silent fallback")

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain the decision",
                allow_fallback=False,
            )
        )
    )

    assert events[-1].event_type == "error"
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.fallback_events == []
    assert len(engine.calls) == 1


def test_local_outcome_history_is_a_bounded_routing_signal(tmp_path):
    engine = FakeEngine(
        _outcome(status="failed", error="authentication failed", receipt_id="receipt-1"),
        _outcome(status="failed", error="authentication failed", receipt_id="receipt-2"),
        _outcome(stdout="alternate provider response", receipt_id="receipt-3"),
    )
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters=_adapters(codex=True, antigravity=True),
            executable_finder=lambda _name: None,
        ),
    )

    for index in range(3):
        conversation = service.create_conversation(title=f"History {index}")
        list(
            service.stream_request(
                ChatRequest(
                    conversation_id=conversation.conversation_id,
                    message="Explain the decision",
                )
            )
        )

    routes = store.list_routes()
    assert [route.selected_provider for route in routes] == [
        "antigravity",
        "codex",
        "codex",
    ]
    newest_candidates = store.list_route_candidates(routes[0].route_id)
    codex = next(item for item in newest_candidates if item.provider_id == "codex")
    assert codex.score_components["historical_success"] == -4


def test_explicit_remember_request_creates_a_proposal_not_silent_memory(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Memory proposal")

    list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Remember that I prefer concise route explanations",
                provider_override="mock",
            )
        )
    )

    memories = store.list_memory()
    assert len(memories) == 1
    assert memories[0].status == "proposed"
    assert memories[0].content == "I prefer concise route explanations"
    assert memories[0].source_message_id is not None


def test_rerun_changes_persona_without_losing_provider_or_route_lineage(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Persona rerun")
    first_events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Help me think this through",
                persona_id="analytical",
                provider_override="mock",
            )
        )
    )
    first_route_id = first_events[-1].route_id

    second_events = list(
        service.rerun(
            first_route_id,
            persona_id="reflective",
            provider_id="mock",
        )
    )

    second_route = store.get_route(second_events[-1].route_id)
    assert second_route.requested_persona_id == "reflective"
    assert second_route.selected_provider == "mock"
    assert second_route.metadata["rerun_of_route_id"] == first_route_id
    assistant_messages = [
        message
        for message in store.list_messages(conversation.conversation_id)
        if message.role == "assistant"
    ]
    comparison = service.compare(
        assistant_messages[0].message_id,
        assistant_messages[1].message_id,
    )
    assert comparison[0]["route"]["requested_persona_id"] == "analytical"
    assert comparison[1]["route"]["requested_persona_id"] == "reflective"


def test_provider_native_mismatch_persists_requested_and_actual_persona(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Native mismatch")

    list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Help me reflect on this choice",
                persona_id="claude-native",
                provider_override="mock",
            )
        )
    )

    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.requested_persona_id == "claude-native"
    assert route.actual_persona_id == "provider-native"
    assert route.persona_provider_mismatch
    assistant = store.list_messages(conversation.conversation_id)[-1]
    assert assistant.metadata["requested_persona_id"] == "claude-native"
    assert assistant.metadata["actual_persona_id"] == "provider-native"
