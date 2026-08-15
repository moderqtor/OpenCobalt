from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.models import RuntimeCapabilitySnapshot
from opencobalt.execution.runner import ProcessRunner
from opencobalt.execution.store import ExecutionStore
from opencobalt.personal_ai.models import AISettings, ProviderPreference
from opencobalt.personal_ai.providers import (
    ProviderModel,
    ProviderModelCatalog,
    ProviderRegistry,
)
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
        isolates_answer_only_inference: bool = True,
    ) -> None:
        self.runtime_id = runtime_id
        self.display_name = runtime_id
        self.executable = runtime_id
        self.available = available
        self.requires_network = requires_network
        self.isolates_answer_only_inference = isolates_answer_only_inference

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


def _adapters(*, codex=False, antigravity=False, claude=False):
    return {
        "codex-cli": FakeAdapter("codex-cli", available=codex),
        "google-antigravity": FakeAdapter(
            "google-antigravity", available=antigravity
        ),
        "claude-code": FakeAdapter("claude-code", available=claude),
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
    with pytest.raises(ValueError, match="identifiers must be bounded"):
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

    types = [event.event_type for event in events]
    assert types[:2] == ["request_accepted", "phase_changed"]
    assert types.index("route_selected") > types.index("phase_changed")
    assert types.index("execution_started") > types.index("route_selected")
    assert types.index("provider_started") > types.index("execution_started")
    assert types.index("provider_started") < types.index("completed")
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
    assert route.metadata["verification"]["checks_performed"] == [
        "nonempty_response",
        "execution_receipt_linked",
    ]
    assert route.metadata["verification"]["limitations"] == [
        "response integrity does not verify factual correctness"
    ]
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
    persisted_types = [event.event_type for event in persisted_events]
    assert persisted_types[0] == "route_selected"
    assert "execution_started" in persisted_types
    assert "provider_started" in persisted_types
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

    assert events[-1].event_type == "completed", (
        f"expected completed, got {events[-1].event_type}: {events[-1].payload}"
    )
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.selected_provider == "mock"
    assert route.metadata.get("capability_role") == "cheap_local"


def test_first_short_request_policy_is_small_and_does_not_duplicate_the_user_message(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Short request")
    captured = {}
    provider = service.providers.get("mock")
    original = provider.execute

    def wrapped(request, cancellation=None):
        captured["policy"] = request.system_policy
        captured["message"] = request.message
        return original(request, cancellation)

    provider.execute = wrapped
    prompt = "What is TCP?"
    list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message=prompt,
                provider_override="mock",
            )
        )
    )
    policy = captured["policy"]
    assert captured["message"] == prompt
    assert policy.count("OpenCobalt interaction policy:") == 1
    assert policy.count(f"User: {prompt}") == 0
    assert "Recent conversation context:" not in policy
    assert len(policy) < 4000


def test_provider_policy_history_is_capped_and_excludes_the_current_user_message(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="History cap")
    for index in range(12):
        store.add_message(
            conversation.conversation_id,
            role="user" if index % 2 == 0 else "assistant",
            content=f"history-{index}: " + ("x" * 10_000),
        )
    captured = {}
    provider = service.providers.get("mock")
    original = provider.execute

    def wrapped(request, cancellation=None):
        captured["policy"] = request.system_policy
        captured["message"] = request.message
        return original(request, cancellation)

    provider.execute = wrapped
    prompt = "Summarize the bounded context"
    list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message=prompt,
                provider_override="mock",
            )
        )
    )
    policy = captured["policy"]
    assert captured["message"] == prompt
    assert policy.count("Recent conversation context:") == 1
    assert policy.count("history-") <= 10
    assert f"User: {prompt}" not in policy
    for line in policy.splitlines():
        if line.startswith("User: ") or line.startswith("Assistant: "):
            assert len(line) <= 3012
    assert len(policy) < 40_000


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


def test_format_constraint_outranks_persona_and_implementation_policy(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Format")
    captured = {}
    provider = service.providers.get("mock")
    original = provider.execute

    def wrapped(request, cancellation=None):
        captured["policy"] = request.system_policy
        captured["message"] = request.message
        return original(request, cancellation)

    provider.execute = wrapped
    list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain why DNS caching improves performance in three sentences.",
                cognitive_policy="implementation",
                provider_override="mock",
            )
        )
    )
    policy = captured["policy"]
    assert captured["message"].startswith("Explain why DNS caching")
    assert policy.index("User output constraint") < policy.index("OpenCobalt interaction policy")
    assert "admonition blocks" in policy
    assert "answer-only request" in policy
    assert "tests, diffs" in policy
    route = store.list_routes(conversation_id=conversation.conversation_id)[0]
    assert route.task_class == "general_reasoning"
    assert route.verification_strategy != "tests_and_diff"
    assert route.autonomy_level == "answer_only"


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


def test_disabled_isolated_provider_does_not_suppress_development_mock(tmp_path):
    adapters = _adapters()
    adapters["ollama"].available = True
    engine = FakeEngine(_outcome(stdout="mock output", receipt_id="receipt-mock"))
    store = PersonalAIStore(tmp_path / "ledger.db")
    store.save_provider_preference(ProviderPreference(provider_id="ollama", enabled=False))
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters=adapters,
            executable_finder=lambda _name: None,
        ),
        enable_mock=True,
    )
    conversation = service.create_conversation(title="Disabled real provider")

    events = list(
        service.stream_request(
            ChatRequest(conversation_id=conversation.conversation_id, message="Explain this")
        )
    )

    route = store.get_route(events[-1].route_id)
    assert events[-1].event_type == "completed"
    assert route is not None and route.selected_provider == "mock"


def test_zero_model_ollama_does_not_suppress_development_mock(tmp_path):
    adapters = _adapters()
    adapters["ollama"].available = True
    engine = FakeEngine(_outcome(stdout="mock output", receipt_id="receipt-mock"))
    store = PersonalAIStore(tmp_path / "ledger.db")
    providers = ProviderRegistry(
        engine,
        adapters=adapters,
        executable_finder=lambda _name: None,
    )
    providers.get("ollama").discover_models = lambda **_kwargs: ProviderModelCatalog(
        provider_id="ollama",
        limitations=[
            "excluded 2 remote/cloud Ollama models from Personal AI execution"
        ],
    )
    service = ChatService(
        store=store,
        providers=providers,
        enable_mock=True,
    )
    conversation = service.create_conversation(title="Empty Ollama")

    events = list(
        service.stream_request(
            ChatRequest(conversation_id=conversation.conversation_id, message="Explain this")
        )
    )

    route = store.get_route(events[-1].route_id)
    assert events[-1].event_type == "completed"
    assert route is not None and route.selected_provider == "mock"
    ollama = next(
        candidate
        for candidate in store.list_route_candidates(route.route_id)
        if candidate.provider_id == "ollama"
    )
    assert ollama.eligible is False
    assert "no models passed local-provenance admission" in (
        ollama.rejection_reason or ""
    )
    assert "excluded 2 remote/cloud" in (ollama.rejection_reason or "")


def test_local_only_unknown_ollama_model_is_denied_before_runtime_execution(tmp_path):
    adapters = _adapters()
    adapters["ollama"].available = True
    engine = FakeEngine()
    store = PersonalAIStore(tmp_path / "ledger.db")
    providers = ProviderRegistry(
        engine,
        adapters=adapters,
        executable_finder=lambda _name: None,
    )
    providers.get("ollama").discover_models = lambda **_kwargs: ProviderModelCatalog(
        provider_id="ollama",
        models=[
            ProviderModel(
                provider_id="ollama",
                model_id="installed:latest",
                display_name="installed:latest",
                source="runtime_discovered",
            )
        ],
    )
    service = ChatService(store=store, providers=providers, enable_mock=True)
    conversation = service.create_conversation(title="Unknown local model")

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain this locally",
                provider_override="ollama",
                model_override="unseen:latest",
                local_only=True,
            )
        )
    )

    assert events[-1].event_type == "route_failed"
    route = store.get_route(events[-1].route_id)
    assert route is not None and route.outcome_status == "policy_denied"
    candidate = next(
        candidate
        for candidate in store.list_route_candidates(route.route_id)
        if candidate.provider_id == "ollama"
    )
    assert candidate.model_id == "unseen:latest"
    assert "not reported by local model discovery" in (candidate.rejection_reason or "")
    assert store.list_executions(request_id=route.request_id) == []
    assert engine.calls == []


def test_settings_default_local_only_reaches_discovery_and_execution_boundary(tmp_path):
    adapters = _adapters()
    adapters["ollama"].available = True
    engine = FakeEngine(_outcome(stdout="local answer", receipt_id="receipt-local"))
    store = PersonalAIStore(tmp_path / "ledger.db")
    store.save_settings(AISettings(local_only_default=True))
    providers = ProviderRegistry(
        engine,
        adapters=adapters,
        executable_finder=lambda _name: None,
    )
    discovery_calls: list[bool] = []

    def discovered_models(*, local_only=False):
        discovery_calls.append(local_only)
        return ProviderModelCatalog(
            provider_id="ollama",
            models=[
                ProviderModel(
                    provider_id="ollama",
                    model_id="installed:latest",
                    display_name="installed:latest",
                    source="runtime_discovered",
                    execution_location="local",
                    locality_evidence=[
                        "loopback_api_tags",
                        "catalog_reported_sha256_digest",
                    ],
                )
            ],
            receipt_id="receipt-discovery",
        )

    providers.get("ollama").discover_models = discovered_models
    service = ChatService(store=store, providers=providers, enable_mock=False)
    conversation = service.create_conversation(title="Default local boundary")

    events = list(
        service.stream_request(
            ChatRequest(conversation_id=conversation.conversation_id, message="Explain this")
        )
    )

    assert events[-1].event_type == "completed"
    route = store.get_route(events[-1].route_id)
    assert route is not None and route.metadata["local_only"] is True
    assert route.selected_provider == "ollama"
    assert route.metadata["provider_discovery_receipt_id"] == "receipt-discovery"
    assert route.metadata["model_execution_location"] == "local"
    assert route.metadata["model_locality_evidence"] == [
        "loopback_api_tags",
        "catalog_reported_sha256_digest",
    ]
    assert any("model discovery receipt: receipt-discovery" in reason for reason in route.reasons)
    assert discovery_calls == [True]
    assert engine.calls[0][1]["runtime"] == "ollama-generate"


def test_automatic_chat_uses_isolated_mock_instead_of_nonisolated_agent(tmp_path):
    adapters = _adapters(codex=True)
    adapters["codex-cli"].isolates_answer_only_inference = False
    engine = FakeEngine(_outcome(stdout="mock engine output", receipt_id="receipt-mock"))
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters=adapters,
            executable_finder=lambda _name: None,
        ),
        enable_mock=True,
    )
    conversation = service.create_conversation(title="Isolated automatic route")

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain this concept",
            )
        )
    )

    assert events[-1].event_type == "completed"
    route = store.get_route(events[-1].route_id)
    assert route is not None and route.selected_provider == "mock"
    codex = next(
        candidate
        for candidate in store.list_route_candidates(route.route_id)
        if candidate.provider_id == "codex"
    )
    assert codex.eligible is False
    assert "answer-only isolation" in (codex.rejection_reason or "")


def test_manual_nonisolated_agent_is_denied_before_execution(tmp_path):
    adapters = _adapters(codex=True)
    adapters["codex-cli"].isolates_answer_only_inference = False
    engine = FakeEngine()
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters=adapters,
            executable_finder=lambda _name: None,
        ),
        enable_mock=False,
    )
    conversation = service.create_conversation(title="Non-isolated manual denial")

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain this concept",
                provider_override="codex",
            )
        )
    )

    assert events[-1].event_type == "route_failed"
    route = store.get_route(events[-1].route_id)
    assert route is not None and route.receipt_id is None
    assert "answer-only isolation" in " ".join(route.reasons)
    assert store.list_executions(request_id=route.request_id) == []
    assert engine.calls == []


def test_no_isolated_provider_records_honest_preexecution_denial(tmp_path):
    adapters = _adapters(codex=True)
    adapters["codex-cli"].isolates_answer_only_inference = False
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            FakeEngine(),
            adapters=adapters,
            executable_finder=lambda _name: None,
        ),
        enable_mock=False,
    )
    conversation = service.create_conversation(title="No isolated provider")

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain this concept",
            )
        )
    )

    assert events[-1].event_type == "route_failed"
    route = store.get_route(events[-1].route_id)
    assert route is not None and route.outcome_status == "policy_denied"
    assert "answer-only isolation" in " ".join(route.reasons)


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
    assert next(stream).event_type == "phase_changed"
    started = None
    for event in stream:
        if event.event_type == "execution_started":
            started = event
            break
    assert started is not None

    assert service.cancel(started.execution_id) is True
    assert service.cancel(started.execution_id) is False
    remaining = list(stream)

    assert remaining[-1].event_type == "cancelled"
    assert store.get_execution(started.execution_id).status == "cancelled"
    assert service.cancel("missing-execution") is False
    signals = service._historical_outcome_signals()
    assert signals.get("mock", {}).get("success", 0) == 0
    assert signals.get("mock", {}).get("cancel", 0) == 0


def test_pre_execution_request_cancellation_is_idempotent(tmp_path):
    service, _, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Early cancellation")
    stream = iter(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain this",
                provider_override="mock",
            )
        )
    )
    accepted = next(stream)
    assert next(stream).event_type == "phase_changed"

    assert service.cancel(accepted.request_id) is True
    assert service.cancel(accepted.request_id) is False
    stream.close()


@pytest.mark.parametrize("stop_type", ["execution_started", "provider_started"])
def test_abandon_before_execution_started_creates_durable_terminal_state(
    tmp_path, stop_type
):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Disconnected stream")
    stream = iter(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain enough to disconnect",
                provider_override="mock",
            )
        )
    )
    last = None
    for event in stream:
        last = event
        if event.event_type == stop_type:
            break
    assert last is not None and last.execution_id is not None

    assert service.abandon(last.execution_id) is True
    stream.close()

    execution = store.get_execution(last.execution_id)
    route = store.get_route(last.route_id)
    messages = store.list_messages(conversation.conversation_id)
    assert execution is not None and execution.status == "cancelled"
    assert route is not None and route.outcome_status == "cancelled"
    assert messages[-1].status == "cancelled"
    assert messages[-1].route_id == route.route_id
    assert service.abandon(last.execution_id) is False


def test_abandon_at_fallback_start_finalizes_the_current_attempt(tmp_path):
    engine = FakeEngine(
        _outcome(status="failed", error="authentication failed", receipt_id="receipt-first"),
        _outcome(stdout="must not be consumed", receipt_id="receipt-second"),
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
    conversation = service.create_conversation(title="Fallback disconnect")
    stream = iter(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Explain the decision",
                persona_id="chatgpt-native",
                allow_fallback=True,
            )
        )
    )
    fallback = next(event for event in stream if event.event_type == "fallback_started")

    assert service.abandon(fallback.execution_id) is True
    stream.close()

    route = store.get_route(fallback.route_id)
    attempts = store.list_executions(request_id=route.request_id)
    assert route is not None and route.outcome_status == "cancelled"
    assert [attempt.status for attempt in attempts] == ["cancelled", "failed"]
    assert len(engine.calls) == 1
    assert route.metadata["actual_provider_id"] == "antigravity"
    assert route.actual_persona_id == "provider-native"
    assert route.actual_persona_version_id is None
    assert "google" in (route.persona_provider_mismatch or "")


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
    messages = store.list_messages(conversation.conversation_id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[-1].status == "failed"
    assert messages[-1].route_id == route.route_id
    assert messages[-1].metadata["error_category"] == "policy_denied"


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


def test_provider_tool_events_are_visible_and_durable(tmp_path):
    output = "\n".join(
        [
            '{"type":"item.completed","item":{"id":"tool-1","type":"command_execution","command":"git status --short","status":"completed"}}',
            '{"type":"item.completed","item":{"id":"message-1","type":"agent_message","text":"Inspection complete."}}',
        ]
    )
    engine = FakeEngine(_outcome(stdout=output, receipt_id="receipt-tool"))
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters=_adapters(codex=True),
            executable_finder=lambda _name: None,
        ),
    )
    conversation = service.create_conversation(title="Tool visibility")

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Inspect the repository",
                provider_override="codex",
            )
        )
    )

    tool_event = next(event for event in events if event.event_type == "tool_completed")
    assert tool_event.payload["tool_event"]["summary"] == "git status --short"
    execution = store.list_executions(conversation_id=conversation.conversation_id)[0]
    persisted = store.list_stream_events(execution.execution_id)
    assert any(event.event_type == "tool_completed" for event in persisted)


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

    messages = store.list_messages(conversation.conversation_id)
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[-1].status == "failed"
    assert messages[-1].route_id == route.route_id
    assert "authentication failed" in messages[-1].content
    execution = store.list_executions(conversation_id=conversation.conversation_id)[0]
    assert execution.assistant_message_id == messages[-1].message_id


def test_provider_terminal_error_is_finalized_before_it_is_streamed(tmp_path):
    private_error = f"cwd {Path.home()}/private/repo API_KEY=secret-value-123"
    engine = FakeEngine(_outcome(status="failed", error=private_error, receipt_id="receipt-fail"))
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters=_adapters(codex=True),
            executable_finder=lambda _name: None,
        ),
    )
    conversation = service.create_conversation(title="Durable terminal failure")

    events = []
    for event in service.stream_request(
        ChatRequest(
            conversation_id=conversation.conversation_id,
            message="Explain the decision",
            provider_override="codex",
        )
    ):
        events.append(event)
        if event.event_type == "error":
            execution = store.list_executions(
                conversation_id=conversation.conversation_id
            )[0]
            route = store.get_route(event.route_id)
            messages = store.list_messages(conversation.conversation_id)
            assert execution.status == "failed"
            assert route is not None and route.outcome_status == "failed"
            assert messages[-1].status == "failed"

    assert [event.event_type for event in events].count("error") == 1
    execution = store.list_executions(conversation_id=conversation.conversation_id)[0]
    persisted_types = [
        event.event_type for event in store.list_stream_events(execution.execution_id)
    ]
    assert "provider_error" in persisted_types
    terminal_message = store.list_messages(conversation.conversation_id)[-1]
    assert str(Path.home()) not in terminal_message.content
    assert "secret-value-123" not in terminal_message.content
    assert "<home>" in terminal_message.content


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


def test_rerun_preserves_recorded_local_only_boundary_when_no_override_is_given(tmp_path):
    service, store, _ = _real_mock_service(tmp_path)
    conversation = service.create_conversation(title="Local rerun")
    first = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Keep this local",
                provider_override="mock",
                local_only=True,
            )
        )
    )
    store.save_settings(store.get_settings().model_copy(update={"local_only_default": False}))

    second = list(service.rerun(first[-1].route_id))

    second_route = store.get_route(second[-1].route_id)
    assert second_route is not None
    assert second_route.metadata["local_only"] is True


def test_cross_provider_fallback_recomputes_provider_native_persona_disclosure(tmp_path):
    engine = FakeEngine(
        _outcome(status="failed", error="authentication failed", receipt_id="receipt-claude"),
        _outcome(stdout="fallback response", receipt_id="receipt-codex"),
    )
    store = PersonalAIStore(tmp_path / "ledger.db")
    service = ChatService(
        store=store,
        providers=ProviderRegistry(
            engine,
            adapters=_adapters(codex=True, claude=True),
            executable_finder=lambda _name: None,
        ),
        enable_mock=False,
    )
    conversation = service.create_conversation(title="Native fallback")

    events = list(
        service.stream_request(
            ChatRequest(
                conversation_id=conversation.conversation_id,
                message="Help me reflect on this choice",
                persona_id="claude-native",
                allow_fallback=True,
            )
        )
    )

    assert events[-1].event_type == "completed"
    route = store.get_route(events[-1].route_id)
    assert route is not None
    assert route.selected_provider == "claude"
    assert route.metadata["actual_provider_id"] == "codex"
    assert route.actual_persona_id == "provider-native"
    assert route.actual_persona_version_id is None
    assert "openai" in (route.persona_provider_mismatch or "")
    assistant = store.list_messages(conversation.conversation_id)[-1]
    assert assistant.metadata["actual_persona_id"] == "provider-native"
    assert assistant.metadata["persona_provider_mismatch"] == route.persona_provider_mismatch


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
