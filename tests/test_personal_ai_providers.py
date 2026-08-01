"""Behavioral tests for the normalized personal-AI provider boundary."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opencobalt.execution.models import RuntimeCapabilitySnapshot
from opencobalt.personal_ai.providers import (
    CancellationToken,
    MockChatProvider,
    ProviderRegistry,
    ProviderRequest,
)


class FakeAdapter:
    def __init__(
        self,
        runtime_id: str,
        *,
        available: bool = True,
        requires_network: bool = True,
        requires_credentials: bool = True,
        supports_noninteractive: bool = True,
    ) -> None:
        self.runtime_id = runtime_id
        self.display_name = runtime_id.replace("-", " ").title()
        self.executable = runtime_id
        self._available = available
        self._requires_network = requires_network
        self._requires_credentials = requires_credentials
        self._supports_noninteractive = supports_noninteractive

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path=f"/private/bin/{self.executable}" if self._available else None,
            available=self._available,
            capabilities=["completion"] if self._supports_noninteractive else [],
            supported_artifact_types=["stdout", "stderr"],
            supports_dry_run=True,
            supports_noninteractive=self._supports_noninteractive,
            supports_json_output=False,
            requires_network=self._requires_network,
            requires_credentials=self._requires_credentials,
            max_safe_risk="yellow",
            limitations=[],
            verifiability_level="partial" if self._available else "unavailable",
            capability_details={"private_runtime_detail": "must not cross provider boundary"},
        ).with_hash()

    def build_command(self, task, options=None):
        model = options.model if options is not None else None
        command = [self.executable, "run"]
        if model:
            command.append(model)
        command.append(task)
        return command

    def supports_non_interactive(self) -> bool:
        return self._supports_noninteractive

    def default_timeout_seconds(self) -> int:
        return 30

    def risk_for_task(self, task: str) -> str:
        return "green"


class FakeEngine:
    def __init__(self, *outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, dict]] = []

    def run_task(self, task: str, **kwargs):
        self.calls.append((task, kwargs))
        if not self.outcomes:
            raise AssertionError("unexpected engine execution")
        return self.outcomes.pop(0)


def _outcome(
    *,
    stdout: str = "",
    status: str = "succeeded",
    receipt_id: str = "receipt-1",
    error: str | None = None,
    allowed: bool = True,
    policy_reason: str = "allowed",
    usage: dict | None = None,
):
    result = None
    if status != "not_executed":
        result = SimpleNamespace(
            status=status,
            stdout_preview=stdout,
            stderr_preview="",
            error=error,
            usage=usage,
        )
    return SimpleNamespace(
        result=result,
        receipt=SimpleNamespace(receipt_id=receipt_id, limitations=[]),
        policy=SimpleNamespace(allowed=allowed, reason=policy_reason),
    )


def _adapters() -> dict[str, FakeAdapter]:
    return {
        "codex-cli": FakeAdapter("codex-cli"),
        "google-antigravity": FakeAdapter("google-antigravity"),
        "claude-code": FakeAdapter("claude-code"),
        "ollama": FakeAdapter(
            "ollama",
            requires_network=False,
            requires_credentials=False,
        ),
    }


def test_registry_discovery_keeps_installation_authentication_and_readiness_distinct():
    engine = FakeEngine()
    registry = ProviderRegistry(
        engine,
        adapters=_adapters(),
        executable_finder=lambda name: "/private/bin/gemini" if name == "gemini" else None,
        ollama_endpoint="http://127.0.0.1:11434",
    )

    statuses = {status.provider_id: status for status in registry.discover()}

    assert list(statuses) == [
        "mock",
        "codex",
        "antigravity",
        "claude",
        "ollama",
        "gemini",
    ]
    assert statuses["mock"].health == "ready"
    assert statuses["mock"].authentication == "not_required"
    assert statuses["codex"].installed is True
    assert statuses["codex"].authentication == "unknown"
    assert statuses["codex"].health == "unknown"
    assert statuses["codex"].routing_profile.provider_family == "openai"
    assert statuses["codex"].routing_profile.evidence == "opencobalt_adapter_contract"
    assert statuses["codex"].routing_profile.statistically_calibrated is False
    assert "repository" in statuses["codex"].routing_profile.task_capabilities
    assert statuses["antigravity"].authentication == "unknown"
    assert statuses["claude"].installed is True
    assert statuses["claude"].authentication == "unknown"
    assert statuses["claude"].health == "unknown"
    assert statuses["ollama"].authentication == "not_required"
    assert statuses["ollama"].capabilities.local_only_eligible is True
    assert statuses["gemini"].installed is True
    assert statuses["gemini"].authentication == "unknown"
    assert statuses["gemini"].execution_supported is False
    assert "discovery-only" in " ".join(statuses["gemini"].limitations).lower()

    rendered = statuses["codex"].model_dump_json()
    assert "/private/bin" not in rendered
    assert "private_runtime_detail" not in rendered
    assert "API_KEY" not in rendered
    assert engine.calls == []


def test_unavailable_executable_does_not_claim_provider_readiness():
    adapters = _adapters()
    adapters["codex-cli"] = FakeAdapter("codex-cli", available=False)
    adapters["ollama"] = FakeAdapter(
        "ollama",
        available=False,
        requires_network=False,
        requires_credentials=False,
    )
    registry = ProviderRegistry(FakeEngine(), adapters=adapters, executable_finder=lambda _: None)

    codex = registry.get("codex").status()
    ollama = registry.get("ollama").status()

    assert codex.installed is False
    assert codex.execution_supported is False
    assert codex.health == "unavailable"
    assert codex.authentication == "unknown"
    assert ollama.execution_supported is False
    assert ollama.capabilities.local_only_eligible is False


def test_unavailable_generic_local_runtime_is_not_routable_as_local_only():
    adapters = _adapters()
    adapters["claude-code"] = FakeAdapter(
        "claude-code",
        available=False,
        requires_network=False,
    )
    registry = ProviderRegistry(FakeEngine(), adapters=adapters, executable_finder=lambda _: None)

    claude = registry.get("claude").status()

    assert claude.installed is False
    assert claude.execution_supported is False
    assert claude.capabilities.local_only_eligible is False


def test_engine_backed_execution_returns_normalized_content_usage_and_receipt():
    engine = FakeEngine(
        _outcome(
            stdout="bounded response",
            receipt_id="receipt-codex",
            usage={"input_tokens": 7, "output_tokens": 11},
        )
    )
    registry = ProviderRegistry(engine, adapters=_adapters(), executable_finder=lambda _: None)
    request = ProviderRequest(message="summarize this", model_id="model-x")

    result = registry.get("codex").execute(request)

    assert result.status == "complete"
    assert result.provider_id == "codex"
    assert result.content == "bounded response"
    assert result.receipt_id == "receipt-codex"
    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens == 11
    assert result.usage.total_tokens == 18
    assert result.error is None
    assert len(engine.calls) == 1
    task, kwargs = engine.calls[0]
    assert task == "summarize this"
    assert kwargs["runtime"] == "codex-cli"
    assert kwargs["execute"] is True
    assert kwargs["model"] == "model-x"
    assert kwargs["adapter"].runtime_id == "codex-cli"
    assert kwargs["unsafe_skip_permissions"] is False


def test_engine_policy_failure_stays_on_requested_provider_without_fallback():
    engine = FakeEngine(
        _outcome(
            status="not_executed",
            receipt_id="receipt-blocked",
            allowed=False,
            policy_reason="explicit approval required",
        )
    )
    registry = ProviderRegistry(engine, adapters=_adapters(), executable_finder=lambda _: None)

    result = registry.get("codex").execute(
        ProviderRequest(message="bounded request", allow_fallback=True)
    )

    assert result.provider_id == "codex"
    assert result.status == "blocked"
    assert result.receipt_id == "receipt-blocked"
    assert result.error is not None
    assert result.error.category == "policy_denied"
    assert len(engine.calls) == 1
    assert engine.calls[0][1]["runtime"] == "codex-cli"


def test_mock_execution_and_simulated_streaming_still_use_execution_engine():
    engine = FakeEngine(
        _outcome(
            stdout="Mock response: alpha beta gamma",
            receipt_id="receipt-mock",
            usage={"input_characters": 5, "output_characters": 31},
        )
    )
    provider = MockChatProvider(engine, chunk_size=8)

    events = list(
        provider.stream(
            ProviderRequest(
                message="alpha",
                model_id="mock-v1",
                system_policy="Interaction persona: analytical",
            )
        )
    )

    assert events[0].event_type == "started"
    assert [event.event_type for event in events[-2:]] == ["usage", "completed"]
    assert all(event.event_type == "text_delta" for event in events[1:-2])
    assert "".join(
        event.text_delta or "" for event in events if event.event_type == "text_delta"
    ) == "Mock response: alpha"
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[-1].receipt_id == "receipt-mock"
    assert len(engine.calls) == 1
    assert "Interaction persona: analytical" in engine.calls[0][0]
    assert "Current user request:\nalpha" in engine.calls[0][0]
    assert engine.calls[0][1]["runtime"] == "noop"
    assert engine.calls[0][1]["execute"] is True


def test_mock_stream_honors_cooperative_cancellation_between_normalized_chunks():
    engine = FakeEngine(_outcome(stdout="Mock response: cancellable output"))
    provider = MockChatProvider(engine, chunk_size=5)
    cancellation = CancellationToken()
    stream = iter(provider.stream(ProviderRequest(message="cancel me"), cancellation))

    assert next(stream).event_type == "started"
    first_delta = next(stream)
    assert first_delta.event_type == "text_delta"
    cancellation.cancel()
    remaining = list(stream)

    assert [event.event_type for event in remaining] == ["cancelled"]
    assert remaining[0].sequence == 3
    assert len(engine.calls) == 1


def test_ollama_models_come_from_engine_backed_discovery_without_fabrication():
    engine = FakeEngine(
        _outcome(
            stdout=(
                "NAME                     ID              SIZE      MODIFIED\n"
                "qwen2.5:7b               abc123          4.7 GB    2 hours ago\n"
                "nomic-embed-text:latest  def456          274 MB    3 days ago\n"
            ),
            receipt_id="receipt-models",
        )
    )
    registry = ProviderRegistry(
        engine,
        adapters=_adapters(),
        executable_finder=lambda _: None,
        ollama_endpoint="http://127.0.0.1:11434",
    )

    catalog = registry.get("ollama").discover_models(local_only=True)

    assert [model.model_id for model in catalog.models] == [
        "qwen2.5:7b",
        "nomic-embed-text:latest",
    ]
    assert catalog.receipt_id == "receipt-models"
    assert catalog.error is None
    assert "llama3" not in [model.model_id for model in catalog.models]
    assert len(engine.calls) == 1
    _, kwargs = engine.calls[0]
    command = kwargs["adapter"].build_command("ignored")
    assert command[-2:] == ["ollama", "list"]
    assert "OLLAMA_HOST=http://127.0.0.1:11434" in command
    assert kwargs["execute"] is True


def test_local_only_ollama_rejects_remote_endpoint_before_engine_execution():
    engine = FakeEngine()
    registry = ProviderRegistry(
        engine,
        adapters=_adapters(),
        executable_finder=lambda _: None,
        ollama_endpoint="https://models.example.test:11434",
    )

    result = registry.get("ollama").execute(
        ProviderRequest(message="private prompt", model_id="qwen2.5:7b", local_only=True)
    )

    assert result.status == "blocked"
    assert result.receipt_id is None
    assert result.error is not None
    assert result.error.category == "local_only_violation"
    assert "models.example.test" not in result.error.message
    assert engine.calls == []


def test_local_only_ollama_forces_loopback_endpoint_in_engine_owned_command():
    engine = FakeEngine(_outcome(stdout="local answer", receipt_id="receipt-local"))
    registry = ProviderRegistry(
        engine,
        adapters=_adapters(),
        executable_finder=lambda _: None,
        ollama_endpoint="http://localhost:11434",
    )

    result = registry.get("ollama").execute(
        ProviderRequest(message="local prompt", model_id="qwen2.5:7b", local_only=True)
    )

    assert result.status == "complete"
    assert result.receipt_id == "receipt-local"
    _, kwargs = engine.calls[0]
    command = kwargs["adapter"].build_command("local prompt", SimpleNamespace(model="qwen2.5:7b"))
    assert "OLLAMA_HOST=http://localhost:11434" in command
    assert command[-4:] == ["ollama", "run", "qwen2.5:7b", "local prompt"]
    assert not any("dangerously" in part for part in command)


@pytest.mark.parametrize("model_id", ["--help", "-qwen", "model name", "x" * 201])
def test_model_selector_rejects_flag_like_or_unbounded_values(model_id):
    with pytest.raises(ValueError, match="model id"):
        ProviderRequest(message="local prompt", model_id=model_id)


def test_gemini_is_discovery_only_and_never_executes_or_falls_back():
    engine = FakeEngine()
    registry = ProviderRegistry(
        engine,
        adapters=_adapters(),
        executable_finder=lambda name: "/private/bin/gemini" if name == "gemini" else None,
    )

    result = registry.get("gemini").execute(
        ProviderRequest(message="use gemini", allow_fallback=True)
    )

    assert result.status == "unavailable"
    assert result.provider_id == "gemini"
    assert result.receipt_id is None
    assert result.error is not None
    assert result.error.category == "execution_unsupported"
    assert engine.calls == []


def test_provider_failure_is_categorized_without_leaking_raw_secret_text():
    engine = FakeEngine(
        _outcome(
            status="failed",
            receipt_id="receipt-failed",
            error="authentication failed for sk-secretvalue1234567890",
        )
    )
    registry = ProviderRegistry(engine, adapters=_adapters(), executable_finder=lambda _: None)

    result = registry.get("codex").execute(ProviderRequest(message="hello"))

    assert result.status == "failed"
    assert result.receipt_id == "receipt-failed"
    assert result.error is not None
    assert result.error.category == "authentication"
    assert "secretvalue" not in result.error.message
    assert "[REDACTED]" in result.error.message


def test_successful_provider_output_is_redacted_before_crossing_normalized_boundary():
    engine = FakeEngine(
        _outcome(
            stdout="provider echoed sk-secretvalue1234567890",
            receipt_id="receipt-redacted",
        )
    )
    registry = ProviderRegistry(engine, adapters=_adapters(), executable_finder=lambda _: None)

    result = registry.get("codex").execute(ProviderRequest(message="hello"))

    assert result.status == "complete"
    assert "secretvalue" not in result.content
    assert "[REDACTED]" in result.content
