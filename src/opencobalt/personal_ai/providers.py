"""Normalized personal-AI provider discovery and execution boundary.

Provider adapters remain responsible for provider-specific argv and capability
evidence. This module exposes only normalized chat-facing records and routes
every real or simulated completion through :class:`ExecutionEngine`.
"""

from __future__ import annotations

import ipaddress
import json
import re
import shutil
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator

from opencobalt.execution.adapters import (
    AntigravityAdapter,
    ClaudeCodeAdapter,
    CodexCliAdapter,
    CursorAdapter,
    NoopAdapter,
    OllamaAdapter,
)
from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.models import RuntimeCapabilitySnapshot
from opencobalt.execution.runner import redact_text

AuthenticationState = Literal["unknown", "not_required", "verified"]
ProviderHealthState = Literal["ready", "unknown", "unavailable"]
ProviderResultStatus = Literal["complete", "failed", "blocked", "cancelled", "unavailable"]
StreamingMode = Literal["none", "simulated", "completion_only"]
CancellationMode = Literal["none", "normalized_stream_only"]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


class ProviderCapabilities(BaseModel):
    """Provider-neutral capabilities proven at the current boundary."""

    completion: bool = False
    streaming: StreamingMode = "none"
    cancellation: CancellationMode = "none"
    model_discovery: bool = False
    usage_reporting: bool = False
    receipt_linkage: bool = False
    local_only_eligible: bool = False
    requires_network: bool = True
    answer_only_isolation: bool = False
    acp: bool = False
    coding_analysis: bool = False
    coding_agent: bool = False


class ProviderRoutingProfile(BaseModel):
    """Declared routing contract, explicitly separate from live health evidence."""

    provider_family: str = "unknown"
    adapter_type: Literal["mock", "cli", "local_runtime", "discovery_only"] = (
        "discovery_only"
    )
    billing_classification: Literal[
        "local", "subscription_backed", "api_billed", "unknown"
    ] = "unknown"
    cost_category: Literal["free", "low", "standard", "high"] = "standard"
    quality_tier: Literal["weak", "standard", "strong"] = "standard"
    latency_category: Literal["low", "standard", "high"] = "standard"
    task_capabilities: list[str] = Field(default_factory=list)
    capability_roles: list[str] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)
    evidence: Literal["opencobalt_adapter_contract"] = "opencobalt_adapter_contract"
    statistically_calibrated: bool = False


class ProviderStatus(BaseModel):
    """Truthful distinction between installation, auth, and readiness."""

    provider_id: str
    display_name: str
    runtime_id: str | None = None
    installed: bool
    authentication: AuthenticationState = "unknown"
    health: ProviderHealthState
    execution_supported: bool
    capabilities: ProviderCapabilities
    routing_profile: ProviderRoutingProfile = Field(default_factory=ProviderRoutingProfile)
    limitations: list[str] = Field(default_factory=list)
    discovered_at: datetime = Field(default_factory=_now)


class ProviderHealth(BaseModel):
    provider_id: str
    state: ProviderHealthState
    authentication: AuthenticationState
    evidence: Literal["builtin", "capability_snapshot", "executable_only"]
    successful_invocation_proven: bool = False
    checked_at: datetime = Field(default_factory=_now)
    limitations: list[str] = Field(default_factory=list)


class ProviderModel(BaseModel):
    provider_id: str
    model_id: str
    display_name: str
    source: Literal["builtin", "runtime_discovered"]
    execution_location: Literal["local", "remote", "unknown"] = "unknown"
    locality_evidence: list[str] = Field(default_factory=list)
    reasoning_support: bool | None = None
    effort_levels: list[str] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)
    context_window: int | None = Field(default=None, ge=1)
    streaming_support: bool | None = None
    available: bool = True
    discovered_at: datetime | None = None
    quality_tier: Literal["weak", "standard", "strong"] | None = None
    cost_category: Literal["free", "low", "standard", "high"] | None = None
    latency_category: Literal["low", "standard", "high"] | None = None
    family: str | None = None
    profile_evidence: str | None = None


class ProviderError(BaseModel):
    category: Literal[
        "authentication",
        "cancelled",
        "configuration",
        "execution_unsupported",
        "invalid_request",
        "local_only_violation",
        "policy_denied",
        "provider_error",
        "rate_limited",
        "timeout",
        "unavailable",
    ]
    message: str
    retryable: bool = False


class ProviderUsage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    input_characters: int | None = Field(default=None, ge=0)
    output_characters: int | None = Field(default=None, ge=0)
    source: Literal["provider_reported", "deterministic_characters", "unavailable"] = (
        "unavailable"
    )


class ProviderRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: _uid("preq"))
    conversation_id: str | None = None
    message: str
    system_policy: str = Field(default="", max_length=50_000)
    model_id: str | None = None
    local_only: bool = False
    allow_fallback: bool = False
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    cwd: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provider request message cannot be blank")
        return value

    @field_validator("model_id")
    @classmethod
    def _model_id_is_argv_safe(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not value
            or value.startswith("-")
            or len(value) > 200
            or any(
                not (character.isalnum() or character in "._:/-")
                for character in value
            )
        ):
            raise ValueError("model id must be a bounded non-flag identifier")
        return value


class ProviderToolEvent(BaseModel):
    """Redacted provider-neutral evidence of a provider-side tool operation."""

    tool_call_id: str
    tool_name: str
    status: Literal["complete", "failed", "unknown"] = "unknown"
    summary: str = ""


class ProviderResult(BaseModel):
    request_id: str
    provider_id: str
    model_id: str | None = None
    status: ProviderResultStatus
    content: str = ""
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    receipt_id: str | None = None
    error: ProviderError | None = None
    limitations: list[str] = Field(default_factory=list)
    tool_events: list[ProviderToolEvent] = Field(default_factory=list)
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: _uid("pevt"))
    request_id: str
    provider_id: str
    sequence: int = Field(ge=1)
    event_type: Literal[
        "started",
        "text_delta",
        "tool_completed",
        "usage",
        "completed",
        "error",
        "cancelled",
        "approval_required",
        "approval_decided",
    ]
    text_delta: str | None = None
    usage: ProviderUsage | None = None
    error: ProviderError | None = None
    tool_event: ProviderToolEvent | None = None
    receipt_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class ProviderModelCatalog(BaseModel):
    provider_id: str
    models: list[ProviderModel] = Field(default_factory=list)
    receipt_id: str | None = None
    error: ProviderError | None = None
    limitations: list[str] = Field(default_factory=list)


_BROAD_READ_ONLY_CAPABILITIES = (
    "chat",
    "coding",
    "creative",
    "data_analysis",
    "decision_support",
    "file_analysis",
    "planning",
    "reflection",
    "repository",
    "research",
    "security",
    "tools",
    "writing",
)

_LOCAL_TEXT_CAPABILITIES = (
    "chat",
    "coding",
    "creative",
    "data_analysis",
    "decision_support",
    "file_analysis",
    "planning",
    "reflection",
    "research",
    "writing",
)

_ROUTING_PROFILES = {
    "mock": ProviderRoutingProfile(
        provider_family="mock",
        adapter_type="mock",
        billing_classification="local",
        cost_category="free",
        quality_tier="weak",
        latency_category="low",
        task_capabilities=_BROAD_READ_ONLY_CAPABILITIES,
        capability_roles=["cheap_local", "fast_general"],
    ),
    "codex": ProviderRoutingProfile(
        provider_family="openai",
        adapter_type="cli",
        billing_classification="subscription_backed",
        quality_tier="strong",
        task_capabilities=_BROAD_READ_ONLY_CAPABILITIES,
        capability_roles=["strong_reasoning"],
    ),
    "antigravity": ProviderRoutingProfile(
        provider_family="google",
        adapter_type="cli",
        billing_classification="subscription_backed",
        quality_tier="strong",
        task_capabilities=_BROAD_READ_ONLY_CAPABILITIES,
        capability_roles=["fast_general", "strong_reasoning", "research", "coding_analysis"],
    ),
    "claude": ProviderRoutingProfile(
        provider_family="anthropic",
        adapter_type="cli",
        billing_classification="subscription_backed",
        quality_tier="strong",
        task_capabilities=_BROAD_READ_ONLY_CAPABILITIES,
        capability_roles=["strong_reasoning"],
    ),
    "ollama": ProviderRoutingProfile(
        provider_family="local",
        adapter_type="local_runtime",
        billing_classification="local",
        cost_category="free",
        quality_tier="weak",
        latency_category="low",
        task_capabilities=_LOCAL_TEXT_CAPABILITIES,
        capability_roles=["cheap_local", "fast_general"],
    ),
    "gemini": ProviderRoutingProfile(
        provider_family="google",
        adapter_type="discovery_only",
        billing_classification="subscription_backed",
        quality_tier="strong",
        task_capabilities=_LOCAL_TEXT_CAPABILITIES,
        capability_roles=["strong_reasoning"],
    ),
    "cursor": ProviderRoutingProfile(
        provider_family="cursor",
        adapter_type="cli",
        billing_classification="subscription_backed",
        quality_tier="strong",
        cost_category="standard",
        latency_category="standard",
        task_capabilities=["coding", "file_analysis", "planning", "repository"],
        capability_roles=["coding_analysis", "coding_agent"],
        tool_names=["read", "edit", "terminal"],
    ),
}


def _routing_profile(name: str) -> ProviderRoutingProfile:
    """Return an isolated copy so provider instances cannot mutate shared templates."""
    return _ROUTING_PROFILES[name].model_copy(deep=True)


class CancellationToken:
    """Thread-safe cooperative cancellation for normalized event emission."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()


class _EngineLike(Protocol):
    def run_task(self, task: str, **kwargs: Any) -> Any: ...


class _AdapterLike(Protocol):
    runtime_id: str
    display_name: str
    executable: str

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot: ...

    def build_command(self, task: str, options: Any = None) -> list[str]: ...

    def supports_non_interactive(self) -> bool: ...

    def default_timeout_seconds(self) -> int: ...

    def risk_for_task(self, task: str) -> str: ...


class ChatProvider:
    """Provider-neutral interface used by routing and chat orchestration."""

    provider_id: str
    display_name: str

    def status(self) -> ProviderStatus:
        raise NotImplementedError

    def health(self) -> ProviderHealth:
        status = self.status()
        return ProviderHealth(
            provider_id=status.provider_id,
            state=status.health,
            authentication=status.authentication,
            evidence="capability_snapshot",
            successful_invocation_proven=False,
            limitations=list(status.limitations),
        )

    def discover_models(self, *, local_only: bool = False) -> ProviderModelCatalog:
        return ProviderModelCatalog(provider_id=self.provider_id)

    def execute(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> ProviderResult:
        raise NotImplementedError

    def stream(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[ProviderEvent]:
        result = self.execute(request, cancellation)
        yield from _events_from_result(result, cancellation, chunk_size=64)


class EngineBackedChatProvider(ChatProvider):
    """A normalized completion provider whose work is owned by ExecutionEngine."""

    def __init__(
        self,
        *,
        provider_id: str,
        display_name: str,
        engine: _EngineLike,
        adapter: _AdapterLike,
        supports_model_discovery: bool = False,
        routing_profile: ProviderRoutingProfile | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        self.engine = engine
        self.adapter = adapter
        self.supports_model_discovery = supports_model_discovery
        self.routing_profile = routing_profile or ProviderRoutingProfile()

    def status(self) -> ProviderStatus:
        snapshot = self.adapter.discover_capabilities()
        execution_supported = snapshot.available and snapshot.supports_noninteractive
        health: ProviderHealthState = "unknown" if snapshot.available else "unavailable"
        authentication: AuthenticationState = (
            "unknown" if snapshot.requires_credentials else "not_required"
        )
        limitations = [_public_error_text(item) for item in snapshot.limitations]
        limitations.append(
            "routing profile is an OpenCobalt adapter contract and heuristic, not live quality calibration"
        )
        if snapshot.available and snapshot.requires_credentials:
            limitations.append(
                "executable discovery does not prove authentication or successful invocation"
            )
        if execution_supported and not getattr(
            self.adapter, "isolates_answer_only_inference", False
        ):
            limitations.append(
                "Personal AI chat requires explicit approval for this non-isolated agent "
                "runtime; approval-and-resume is not implemented"
            )
        return ProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            runtime_id=self.adapter.runtime_id,
            installed=snapshot.available,
            authentication=authentication,
            health=health,
            execution_supported=execution_supported,
            capabilities=ProviderCapabilities(
                completion=execution_supported,
                streaming="completion_only" if execution_supported else "none",
                cancellation="none",
                model_discovery=self.supports_model_discovery,
                usage_reporting=False,
                receipt_linkage=execution_supported,
                local_only_eligible=execution_supported and not snapshot.requires_network,
                requires_network=snapshot.requires_network,
                answer_only_isolation=bool(
                    getattr(self.adapter, "isolates_answer_only_inference", False)
                ),
            ),
            routing_profile=self.routing_profile.model_copy(deep=True),
            limitations=list(dict.fromkeys(limitations)),
        )

    def execute(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> ProviderResult:
        return self._execute_through_engine(request, cancellation=cancellation)

    def _execute_through_engine(
        self,
        request: ProviderRequest,
        *,
        cancellation: CancellationToken | None = None,
        task: str | None = None,
        adapter: _AdapterLike | None = None,
        model_id: str | None = None,
        cwd: str | None = None,
    ) -> ProviderResult:
        if cancellation is not None and cancellation.cancelled:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="cancelled",
                message="request cancelled before execution",
                status="cancelled",
            )

        provider_status = self.status()
        if request.local_only and not provider_status.capabilities.local_only_eligible:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="local_only_violation",
                message="requested provider is not proven eligible for local-only execution",
                status="blocked",
            )
        if not provider_status.installed:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="unavailable",
                message="provider executable is unavailable",
                status="unavailable",
            )
        if not provider_status.execution_supported:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="execution_unsupported",
                message="safe non-interactive provider execution was not discovered",
                status="unavailable",
            )

        selected_adapter = adapter or self.adapter
        try:
            outcome = self.engine.run_task(
                task if task is not None else _provider_task(request),
                runtime=selected_adapter.runtime_id,
                model=model_id if model_id is not None else request.model_id,
                execute=True,
                approved=False,
                timeout_seconds=request.timeout_seconds,
                cwd=cwd if cwd is not None else request.cwd,
                unsafe_skip_permissions=False,
                execution_context="answer_only_inference",
                risk_subject=request.message,
                adapter=selected_adapter,
            )
        except (KeyError, ValueError) as exc:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="configuration",
                message=_public_error_text(str(exc)),
                status="failed",
            )
        return _normalize_outcome(
            request=request,
            provider_id=self.provider_id,
            model_id=model_id if model_id is not None else request.model_id,
            outcome=outcome,
        )


class MockChatProvider(EngineBackedChatProvider):
    """Deterministic development provider executed through the noop adapter."""

    def __init__(self, engine: _EngineLike, *, chunk_size: int = 16) -> None:
        super().__init__(
            provider_id="mock",
            display_name="Mock (deterministic local)",
            engine=engine,
            adapter=NoopAdapter(),
            routing_profile=_routing_profile("mock"),
        )
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        self.chunk_size = chunk_size

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            runtime_id="noop",
            installed=True,
            authentication="not_required",
            health="ready",
            execution_supported=True,
            capabilities=ProviderCapabilities(
                completion=True,
                streaming="simulated",
                cancellation="normalized_stream_only",
                model_discovery=True,
                usage_reporting=True,
                receipt_linkage=True,
                local_only_eligible=True,
                requires_network=False,
                answer_only_isolation=True,
            ),
            routing_profile=self.routing_profile.model_copy(deep=True),
            limitations=[
                "deterministic development provider; not a live model",
                "cancellation applies between simulated chunks after engine completion",
                "routing profile is an OpenCobalt adapter contract and heuristic, not live quality calibration",
            ],
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self.provider_id,
            state="ready",
            authentication="not_required",
            evidence="builtin",
            successful_invocation_proven=False,
            limitations=self.status().limitations,
        )

    def discover_models(self, *, local_only: bool = False) -> ProviderModelCatalog:
        return ProviderModelCatalog(
            provider_id=self.provider_id,
            models=[
                ProviderModel(
                    provider_id=self.provider_id,
                    model_id="mock-v1",
                    display_name="Mock v1",
                    source="builtin",
                    execution_location="local",
                    locality_evidence=["deterministic_builtin"],
                )
            ],
        )

    def execute(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> ProviderResult:
        model_id = request.model_id or "mock-v1"
        result = self._execute_through_engine(
            request,
            cancellation=cancellation,
            task=f"Mock response: {_provider_task(request)}",
            model_id=model_id,
        )
        if result.status == "complete":
            schema = request.metadata.get("json_schema")
            if isinstance(schema, dict):
                result.content = json.dumps(_mock_structured_payload(request.message, schema))
            else:
                result.content = f"Mock response: {request.message}"
            if result.usage.source == "unavailable":
                result.usage = ProviderUsage(
                    input_characters=len(request.message) + len(request.system_policy),
                    output_characters=len(result.content),
                    source="deterministic_characters",
                )
        return result

    def stream(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[ProviderEvent]:
        result = self.execute(request, cancellation)
        yield from _events_from_result(result, cancellation, chunk_size=self.chunk_size)


class _OllamaModelCatalogAdapter:
    """Read Ollama's loopback JSON catalog through an engine-owned curl command."""

    runtime_id = "ollama-model-catalog"
    display_name = "Ollama local model catalog"
    isolates_answer_only_inference = True

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.executable = shutil.which("curl") or "curl"
        self._available = shutil.which("curl") is not None and _is_loopback_url(endpoint)

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path=self.executable if self._available else None,
            available=self._available,
            capabilities=["loopback_model_catalog"] if self._available else [],
            supported_artifact_types=["stdout", "stderr"],
            supports_dry_run=True,
            supports_noninteractive=self._available,
            supports_json_output=True,
            requires_network=False,
            requires_credentials=False,
            max_safe_risk="green",
            limitations=(
                []
                if self._available
                else ["curl and an explicit loopback Ollama endpoint are required"]
            ),
            verifiability_level="full" if self._available else "unavailable",
            capability_details={
                "endpoint_scope": "loopback_only",
                "catalog_path": "/api/tags",
            },
        ).with_hash()

    def build_command(self, task: str, options: Any = None) -> list[str]:
        if not self._available:
            raise ValueError("Ollama model catalog adapter is unavailable")
        return _hermetic_loopback_curl_command(
            executable=self.executable,
            endpoint=self.endpoint,
            path="/api/tags",
            max_time_seconds=30,
        )

    def supports_non_interactive(self) -> bool:
        return self._available

    def default_timeout_seconds(self) -> int:
        return 30

    def risk_for_task(self, task: str) -> str:
        return "green"


class _OllamaGenerateAdapter:
    """Run one non-pulling completion through Ollama's loopback HTTP API."""

    runtime_id = "ollama-generate"
    display_name = "Ollama loopback generation API"
    isolates_answer_only_inference = True

    def __init__(
        self,
        *,
        endpoint: str,
        model_id: str,
        timeout_seconds: int,
    ) -> None:
        self.endpoint = endpoint
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds
        self.executable = shutil.which("curl") or "curl"
        self._available = shutil.which("curl") is not None and _is_loopback_url(endpoint)

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path=self.executable if self._available else None,
            available=self._available,
            capabilities=["loopback_generate_api"] if self._available else [],
            supported_artifact_types=["stdout", "stderr"],
            supports_dry_run=True,
            supports_noninteractive=self._available,
            supports_json_output=True,
            requires_network=False,
            requires_credentials=False,
            max_safe_risk="green",
            limitations=(
                []
                if self._available
                else ["curl and an explicit loopback Ollama endpoint are required"]
            ),
            verifiability_level="full" if self._available else "unavailable",
            capability_details={
                "endpoint_scope": "loopback_only",
                "generation_path": "/api/generate",
                "automatic_pull_requested": False,
            },
        ).with_hash()

    def build_command(self, task: str, options: Any = None) -> list[str]:
        if not self._available:
            raise ValueError("Ollama generation adapter is unavailable")
        payload = json.dumps(
            {
                # Ollama 0.20.x treats :local as a server-enforced source
                # constraint and rejects remote manifests for this request.
                "model": f"{self.model_id}:local",
                "prompt": task,
                "stream": False,
            },
            separators=(",", ":"),
        )
        return _hermetic_loopback_curl_command(
            executable=self.executable,
            endpoint=self.endpoint,
            path="/api/generate",
            max_time_seconds=self.timeout_seconds,
            method="POST",
            payload=payload,
        )

    def supports_non_interactive(self) -> bool:
        return self._available

    def default_timeout_seconds(self) -> int:
        return self.timeout_seconds

    def risk_for_task(self, task: str) -> str:
        return "green"


class OllamaChatProvider(EngineBackedChatProvider):
    """Ollama provider with engine-backed, loopback-only model discovery."""

    def __init__(
        self,
        engine: _EngineLike,
        adapter: _AdapterLike,
        endpoint: str,
    ) -> None:
        self.endpoint = _normalized_ollama_endpoint(endpoint)
        self._catalog_adapter = (
            _OllamaModelCatalogAdapter(self.endpoint) if self.endpoint is not None else None
        )
        super().__init__(
            provider_id="ollama",
            display_name="Ollama",
            engine=engine,
            adapter=adapter,
            supports_model_discovery=True,
            routing_profile=_routing_profile("ollama"),
        )

    @property
    def _loopback(self) -> bool:
        return self.endpoint is not None and _is_loopback_url(self.endpoint)

    def status(self) -> ProviderStatus:
        status = super().status()
        catalog_available = bool(
            self._catalog_adapter
            and self._catalog_adapter.discover_capabilities().available
        )
        status.capabilities.model_discovery = (
            status.installed and self._loopback and catalog_available
        )
        status.capabilities.local_only_eligible = (
            status.installed and self._loopback and catalog_available
        )
        status.capabilities.requires_network = not self._loopback
        if not self._loopback:
            status.execution_supported = False
            status.capabilities.completion = False
            status.capabilities.receipt_linkage = False
            status.limitations.append(
                "Ollama execution is disabled until an explicit loopback endpoint is configured"
            )
        elif not catalog_available:
            status.execution_supported = False
            status.capabilities.completion = False
            status.capabilities.receipt_linkage = False
            status.limitations.append(
                "Ollama execution is disabled because local model provenance cannot be read"
            )
        else:
            status.limitations.append(
                "only models admitted by bounded loopback catalog evidence are used; "
                "generation uses Ollama's server-enforced :local source constraint and "
                "does not request automatic model retrieval"
            )
        return status

    def execute(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> ProviderResult:
        if not self._loopback:
            category = "local_only_violation" if request.local_only else "configuration"
            return _pre_execution_error(
                request,
                self.provider_id,
                category=category,
                message="Ollama endpoint is not proven loopback; execution is disabled",
                status="blocked",
            )
        if request.model_id is None or not request.model_id.strip():
            return _pre_execution_error(
                request,
                self.provider_id,
                category="invalid_request",
                message="Ollama execution requires an explicitly discovered model id",
                status="blocked",
            )
        catalog = self.discover_models(local_only=request.local_only)
        admitted = {model.model_id for model in catalog.models}
        if catalog.error is not None:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="local_only_violation" if request.local_only else "unavailable",
                message="Ollama local model provenance could not be verified",
                status="blocked",
            )
        if request.model_id not in admitted:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="local_only_violation" if request.local_only else "invalid_request",
                message=(
                    "requested Ollama model was not admitted by local model discovery; "
                    "remote retrieval is disabled"
                ),
                status="blocked",
            )
        generate_adapter = _OllamaGenerateAdapter(
            endpoint=self.endpoint,
            model_id=request.model_id,
            timeout_seconds=request.timeout_seconds,
        )
        return self._execute_through_engine(
            request,
            cancellation=cancellation,
            adapter=generate_adapter,
        )

    def discover_models(self, *, local_only: bool = False) -> ProviderModelCatalog:
        request = ProviderRequest(
            message="discover installed Ollama models",
            local_only=local_only,
            timeout_seconds=30,
        )
        if not self._loopback:
            return ProviderModelCatalog(
                provider_id=self.provider_id,
                error=ProviderError(
                    category="local_only_violation" if local_only else "configuration",
                    message="Ollama model discovery requires an explicit loopback endpoint",
                ),
            )
        status = self.status()
        if (
            not status.installed
            or not self.adapter.supports_non_interactive()
            or self._catalog_adapter is None
            or not self._catalog_adapter.supports_non_interactive()
        ):
            return ProviderModelCatalog(
                provider_id=self.provider_id,
                error=ProviderError(
                    category="unavailable",
                    message="Ollama executable is unavailable",
                ),
            )
        outcome = self.engine.run_task(
            "inspect loopback Ollama model provenance",
            runtime="ollama-model-catalog",
            model=None,
            execute=True,
            approved=False,
            timeout_seconds=request.timeout_seconds,
            cwd=None,
            unsafe_skip_permissions=False,
            adapter=self._catalog_adapter,
        )
        normalized = _normalize_outcome(
            request=request,
            provider_id=self.provider_id,
            model_id=None,
            outcome=outcome,
        )
        if normalized.status != "complete":
            return ProviderModelCatalog(
                provider_id=self.provider_id,
                receipt_id=normalized.receipt_id,
                error=normalized.error,
            )
        try:
            models, limitations = _parse_ollama_models(normalized.content)
        except ValueError:
            return ProviderModelCatalog(
                provider_id=self.provider_id,
                receipt_id=normalized.receipt_id,
                error=ProviderError(
                    category="provider_error",
                    message="Ollama returned an invalid local model catalog",
                ),
            )
        return ProviderModelCatalog(
            provider_id=self.provider_id,
            models=models,
            receipt_id=normalized.receipt_id,
            limitations=limitations,
        )


class DiscoveryOnlyChatProvider(ChatProvider):
    """Installed-tool evidence that intentionally has no execution path."""

    def __init__(
        self,
        *,
        provider_id: str,
        display_name: str,
        executable: str,
        executable_finder: Callable[[str], str | None],
        routing_profile: ProviderRoutingProfile | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        self.executable = executable
        self.executable_finder = executable_finder
        self.routing_profile = routing_profile or ProviderRoutingProfile()

    def status(self) -> ProviderStatus:
        installed = self.executable_finder(self.executable) is not None
        return ProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            runtime_id=None,
            installed=installed,
            authentication="unknown",
            health="unknown" if installed else "unavailable",
            execution_supported=False,
            capabilities=ProviderCapabilities(
                completion=False,
                streaming="none",
                cancellation="none",
                model_discovery=False,
                usage_reporting=False,
                receipt_linkage=False,
                local_only_eligible=False,
                requires_network=True,
            ),
            routing_profile=self.routing_profile.model_copy(deep=True),
            limitations=[
                "discovery-only: executable presence does not prove authentication or safe execution",
                "routing profile is an OpenCobalt adapter contract and heuristic, not live quality calibration",
            ],
        )

    def health(self) -> ProviderHealth:
        status = self.status()
        return ProviderHealth(
            provider_id=self.provider_id,
            state=status.health,
            authentication="unknown",
            evidence="executable_only",
            successful_invocation_proven=False,
            limitations=status.limitations,
        )

    def execute(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> ProviderResult:
        return _pre_execution_error(
            request,
            self.provider_id,
            category="execution_unsupported",
            message="provider is discovery-only; no safe execution boundary is available",
            status="unavailable",
        )


class ProviderRegistry:
    """Stable registry for the bounded v1 provider set; it never falls back."""

    def __init__(
        self,
        engine: ExecutionEngine | _EngineLike,
        *,
        adapters: Mapping[str, _AdapterLike] | None = None,
        executable_finder: Callable[[str], str | None] = shutil.which,
        ollama_endpoint: str = "http://127.0.0.1:11434",
        approval_store: Any | None = None,
        approval_coordinator: Any | None = None,
    ) -> None:
        runtime_adapters: Mapping[str, _AdapterLike] = adapters or {
            "codex-cli": CodexCliAdapter(),
            "google-antigravity": AntigravityAdapter(),
            "claude-code": ClaudeCodeAdapter(),
            "ollama": OllamaAdapter(),
            "cursor": CursorAdapter(),
        }
        required = {"claude-code", "codex-cli", "google-antigravity", "ollama"}
        missing = sorted(required.difference(runtime_adapters))
        if missing:
            raise ValueError(f"missing provider adapters: {', '.join(missing)}")

        providers: list[ChatProvider] = [
            MockChatProvider(engine),
            EngineBackedChatProvider(
                provider_id="codex",
                display_name="Codex CLI",
                engine=engine,
                adapter=runtime_adapters["codex-cli"],
                routing_profile=_routing_profile("codex"),
            ),
            _antigravity_chat_provider(engine, runtime_adapters["google-antigravity"]),
            EngineBackedChatProvider(
                provider_id="claude",
                display_name="Claude Code",
                engine=engine,
                adapter=runtime_adapters["claude-code"],
                routing_profile=_routing_profile("claude"),
            ),
            OllamaChatProvider(
                engine,
                runtime_adapters["ollama"],
                ollama_endpoint,
            ),
            DiscoveryOnlyChatProvider(
                provider_id="gemini",
                display_name="Gemini CLI",
                executable="gemini",
                executable_finder=executable_finder,
                routing_profile=_routing_profile("gemini"),
            ),
        ]
        if "cursor" in runtime_adapters:
            providers.append(
                _cursor_chat_provider(
                    engine,
                    runtime_adapters["cursor"],
                    approval_store=approval_store,
                    approval_coordinator=approval_coordinator,
                )
            )
        self._providers = {provider.provider_id: provider for provider in providers}

    def discover(self) -> list[ProviderStatus]:
        return [provider.status() for provider in self._providers.values()]

    def get(self, provider_id: str) -> ChatProvider:
        try:
            return self._providers[provider_id]
        except KeyError:
            known = ", ".join(self._providers)
            raise KeyError(f"unknown provider '{provider_id}' (known: {known})") from None


def _provider_task(request: ProviderRequest) -> str:
    """Compose policy and user content at the provider boundary."""
    if not request.system_policy.strip():
        return request.message
    return (
        f"{request.system_policy.rstrip()}\n\n"
        f"Current user request:\n{request.message}"
    )


def _events_from_result(
    result: ProviderResult,
    cancellation: CancellationToken | None,
    *,
    chunk_size: int,
) -> Iterator[ProviderEvent]:
    sequence = 1
    if cancellation is not None and cancellation.cancelled:
        yield ProviderEvent(
            request_id=result.request_id,
            provider_id=result.provider_id,
            sequence=sequence,
            event_type="cancelled",
            error=ProviderError(category="cancelled", message="request cancelled"),
            receipt_id=result.receipt_id,
        )
        return

    yield ProviderEvent(
        request_id=result.request_id,
        provider_id=result.provider_id,
        sequence=sequence,
        event_type="started",
        receipt_id=result.receipt_id,
    )
    sequence += 1

    if result.status != "complete":
        event_type = "cancelled" if result.status == "cancelled" else "error"
        yield ProviderEvent(
            request_id=result.request_id,
            provider_id=result.provider_id,
            sequence=sequence,
            event_type=event_type,
            error=result.error,
            receipt_id=result.receipt_id,
        )
        return

    for tool_event in result.tool_events:
        yield ProviderEvent(
            request_id=result.request_id,
            provider_id=result.provider_id,
            sequence=sequence,
            event_type="tool_completed",
            tool_event=tool_event,
            receipt_id=result.receipt_id,
        )
        sequence += 1

    for offset in range(0, len(result.content), chunk_size):
        if cancellation is not None and cancellation.cancelled:
            yield ProviderEvent(
                request_id=result.request_id,
                provider_id=result.provider_id,
                sequence=sequence,
                event_type="cancelled",
                error=ProviderError(category="cancelled", message="stream cancelled"),
                receipt_id=result.receipt_id,
            )
            return
        yield ProviderEvent(
            request_id=result.request_id,
            provider_id=result.provider_id,
            sequence=sequence,
            event_type="text_delta",
            text_delta=result.content[offset : offset + chunk_size],
            receipt_id=result.receipt_id,
        )
        sequence += 1

    yield ProviderEvent(
        request_id=result.request_id,
        provider_id=result.provider_id,
        sequence=sequence,
        event_type="usage",
        usage=result.usage,
        receipt_id=result.receipt_id,
    )
    sequence += 1
    yield ProviderEvent(
        request_id=result.request_id,
        provider_id=result.provider_id,
        sequence=sequence,
        event_type="completed",
        receipt_id=result.receipt_id,
        session_id=result.session_id,
        metadata=dict(result.metadata),
    )


def _normalize_outcome(
    *,
    request: ProviderRequest,
    provider_id: str,
    model_id: str | None,
    outcome: Any,
) -> ProviderResult:
    receipt = getattr(outcome, "receipt", None)
    receipt_id = getattr(receipt, "receipt_id", None)
    limitations = [
        _public_error_text(str(item)) for item in (getattr(receipt, "limitations", []) or [])
    ]
    result = getattr(outcome, "result", None)
    policy = getattr(outcome, "policy", None)

    if result is None:
        if policy is not None and not getattr(policy, "allowed", False):
            error = ProviderError(
                category="policy_denied",
                message=_public_error_text(str(getattr(policy, "reason", "execution blocked"))),
            )
            status: ProviderResultStatus = "blocked"
        else:
            error = ProviderError(
                category="unavailable",
                message="provider execution did not start",
            )
            status = "unavailable"
        return ProviderResult(
            request_id=request.request_id,
            provider_id=provider_id,
            model_id=model_id,
            status=status,
            receipt_id=receipt_id,
            error=error,
            limitations=limitations,
        )

    result_status = str(getattr(result, "status", "failed"))
    raw_content = _engine_result_output(result)
    if provider_id == "ollama" and _ollama_remote_execution_disclosed(raw_content):
        return ProviderResult(
            request_id=request.request_id,
            provider_id=provider_id,
            model_id=model_id,
            status="failed",
            receipt_id=receipt_id,
            error=ProviderError(
                category=(
                    "local_only_violation" if request.local_only else "provider_error"
                ),
                message=(
                    "Ollama response disclosed remote execution metadata; content was rejected"
                ),
            ),
            limitations=limitations,
        )
    parsed_content, parsed_usage, tool_events = _normalize_provider_payload(
        provider_id, raw_content
    )
    session_id = None
    extra_limitations: list[str] = []
    if provider_id == "antigravity":
        from opencobalt.personal_ai.antigravity import parse_antigravity_payload

        parsed_content, parsed_usage, tool_events, session_id, extra_limitations = (
            parse_antigravity_payload(raw_content)
        )
    content = _public_output_text(parsed_content)
    if extra_limitations:
        limitations.extend(_public_error_text(item) for item in extra_limitations)
    usage = _normalize_usage(getattr(result, "usage", None))
    if usage.source == "unavailable" and parsed_usage is not None:
        usage = _normalize_usage(parsed_usage)
    envelope_error = _antigravity_envelope_error(provider_id, raw_content)
    if result_status == "succeeded" and envelope_error is None:
        return ProviderResult(
            request_id=request.request_id,
            provider_id=provider_id,
            model_id=model_id,
            status="complete",
            content=content,
            usage=usage,
            receipt_id=receipt_id,
            limitations=limitations,
            tool_events=tool_events,
            session_id=session_id,
        )

    raw_error = str(
        envelope_error
        or getattr(result, "error", None)
        or getattr(result, "stderr_preview", None)
        or f"provider execution {result_status}"
    )
    category, retryable = _categorize_error(raw_error, result_status)
    return ProviderResult(
        request_id=request.request_id,
        provider_id=provider_id,
        model_id=model_id,
        status="cancelled" if category == "cancelled" else "failed",
        content=content,
        usage=usage,
        receipt_id=receipt_id,
        error=ProviderError(
            category=category,
            message=_public_error_text(raw_error),
            retryable=retryable,
        ),
        limitations=limitations,
        tool_events=tool_events,
        session_id=session_id,
    )


def _engine_result_output(result: Any, *, limit: int = 200_000) -> str:
    """Read bounded engine-owned output instead of truncating chat to its preview."""
    direct = getattr(result, "content", "")
    if direct:
        return str(direct)[:limit]
    output_path = getattr(result, "stdout_path", None)
    if output_path:
        try:
            with Path(output_path).open("r", encoding="utf-8", errors="replace") as handle:
                return handle.read(limit)
        except OSError:
            pass
    return str(getattr(result, "stdout_preview", ""))[:limit]


def _antigravity_chat_provider(engine: _EngineLike, adapter: _AdapterLike) -> ChatProvider:
    from opencobalt.personal_ai.antigravity import AntigravityChatProvider

    return AntigravityChatProvider(engine, adapter)


def _cursor_chat_provider(
    engine: _EngineLike,
    adapter: _AdapterLike,
    *,
    approval_store: Any | None = None,
    approval_coordinator: Any | None = None,
) -> ChatProvider:
    from opencobalt.personal_ai.cursor_acp import CursorACPProvider

    return CursorACPProvider(
        engine,
        adapter,
        approval_store=approval_store,
        coordinator=approval_coordinator,
    )


def _antigravity_envelope_error(provider_id: str, raw_content: str) -> str | None:
    if provider_id != "antigravity":
        return None
    from opencobalt.personal_ai.antigravity import parse_antigravity_payload

    _content, _usage, _tools, _session, limitations = parse_antigravity_payload(raw_content)
    for item in limitations:
        lowered = item.lower()
        if "status error" in lowered or "invalid model" in lowered or "authentication" in lowered:
            return item
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and str(payload.get("status", "")).upper() in {
        "ERROR",
        "CANCELED",
        "INTERRUPTED",
        "INVALID",
    }:
        error = payload.get("error")
        return str(error) if error else f"Antigravity status {payload.get('status')}"
    return None


def _normalize_provider_payload(
    provider_id: str,
    raw_content: str,
) -> tuple[str, dict[str, Any] | None, list[ProviderToolEvent]]:
    if provider_id == "ollama":
        return _parse_ollama_generate_payload(raw_content)
    if provider_id == "antigravity":
        from opencobalt.personal_ai.antigravity import parse_antigravity_payload

        content, usage, tool_events, _session_id, _limitations = parse_antigravity_payload(
            raw_content
        )
        return content, usage, tool_events
    if provider_id != "codex":
        return raw_content, None, []
    return _parse_codex_jsonl(raw_content)


def _parse_ollama_generate_payload(
    raw_content: str,
) -> tuple[str, dict[str, Any] | None, list[ProviderToolEvent]]:
    """Extract text and usage from one non-streaming Ollama generation response."""
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return raw_content, None, []
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), str):
        # Model catalog discovery also normalizes through this provider id.
        return raw_content, None, []
    prompt_tokens = _nonnegative_int(payload.get("prompt_eval_count"))
    output_tokens = _nonnegative_int(payload.get("eval_count"))
    usage: dict[str, Any] = {
        "input_tokens": prompt_tokens,
        "output_tokens": output_tokens,
    }
    if prompt_tokens is not None and output_tokens is not None:
        usage["total_tokens"] = prompt_tokens + output_tokens
    return str(payload["response"]), usage, []


def _ollama_remote_execution_disclosed(raw_content: str) -> bool:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return any(payload.get(field) not in (None, "") for field in ("remote_host", "remote_model"))


def _parse_codex_jsonl(
    raw_content: str,
) -> tuple[str, dict[str, Any] | None, list[ProviderToolEvent]]:
    """Extract assistant text, usage, and bounded tool evidence from Codex JSONL."""
    messages: list[str] = []
    usage: dict[str, Any] | None = None
    tool_events: list[ProviderToolEvent] = []
    parsed_events = 0
    for line in raw_content.splitlines()[:2_000]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        parsed_events += 1
        raw_usage = event.get("usage")
        if isinstance(raw_usage, Mapping):
            usage = dict(raw_usage)
        item = event.get("item")
        if not isinstance(item, Mapping):
            item = event if event.get("role") == "assistant" else None
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type", ""))
        if item_type in {"agent_message", "message"}:
            text = item.get("text")
            if isinstance(text, str) and text:
                messages.append(text)
                continue
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                        messages.append(str(part["text"]))
            continue
        if item_type not in {
            "command_execution",
            "file_change",
            "mcp_tool_call",
            "tool_call",
            "web_search",
        }:
            continue
        call_id = str(item.get("id") or item.get("call_id") or _uid("ptool"))
        status_value = str(item.get("status", "unknown")).lower()
        normalized_status: Literal["complete", "failed", "unknown"]
        if status_value in {"completed", "complete", "succeeded"}:
            normalized_status = "complete"
        elif status_value in {"failed", "error"}:
            normalized_status = "failed"
        else:
            normalized_status = "unknown"
        raw_summary = (
            item.get("command")
            or item.get("name")
            or item.get("path")
            or item_type
        )
        tool_events.append(
            ProviderToolEvent(
                tool_call_id=call_id[:200],
                tool_name=item_type[:100],
                status=normalized_status,
                summary=_public_output_text(str(raw_summary))[:500],
            )
        )
    if parsed_events == 0:
        return raw_content, None, []
    return "\n\n".join(messages), usage, tool_events


def _normalize_usage(raw: Any) -> ProviderUsage:
    if not isinstance(raw, Mapping):
        return ProviderUsage()
    input_tokens = _nonnegative_int(raw.get("input_tokens"))
    output_tokens = _nonnegative_int(raw.get("output_tokens"))
    total_tokens = _nonnegative_int(raw.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    input_characters = _nonnegative_int(raw.get("input_characters"))
    output_characters = _nonnegative_int(raw.get("output_characters"))
    known = any(
        value is not None
        for value in (
            input_tokens,
            output_tokens,
            total_tokens,
            input_characters,
            output_characters,
        )
    )
    return ProviderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        input_characters=input_characters,
        output_characters=output_characters,
        source="provider_reported" if known else "unavailable",
    )


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _categorize_error(raw_error: str, result_status: str) -> tuple[str, bool]:
    lowered = raw_error.lower()
    if result_status == "timeout" or "timed out" in lowered or "timeout" in lowered:
        return "timeout", True
    if result_status == "cancelled" or "cancelled" in lowered or "canceled" in lowered:
        return "cancelled", False
    if any(word in lowered for word in ("authentication", "credential", "unauthorized", "login")):
        return "authentication", False
    if "rate limit" in lowered or "too many requests" in lowered:
        return "rate_limited", True
    if "unavailable" in lowered or "executable not found" in lowered:
        return "unavailable", True
    return "provider_error", False


def _pre_execution_error(
    request: ProviderRequest,
    provider_id: str,
    *,
    category: str,
    message: str,
    status: ProviderResultStatus,
) -> ProviderResult:
    return ProviderResult(
        request_id=request.request_id,
        provider_id=provider_id,
        model_id=request.model_id,
        status=status,
        error=ProviderError(category=category, message=_public_error_text(message)),  # type: ignore[arg-type]
    )


def _public_error_text(value: str) -> str:
    return _public_output_text(value)[:500]


_ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_ANSI_CSI_RE = re.compile(r"\x1b\[([0-?]*)([ -/]*)([@-~])")
_ANSI_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)", re.DOTALL)


def _render_terminal_text(value: str) -> str:
    """Apply bounded cursor/erase controls emitted by terminal-oriented CLIs."""
    value = _ANSI_OSC_RE.sub("", value)
    lines: list[list[str]] = [[]]
    row = 0
    column = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\x1b":
            match = _ANSI_CSI_RE.match(value, index)
            if match is not None:
                raw_parameters, _, command = match.groups()
                first_parameter = raw_parameters.split(";", 1)[0]
                amount = int(first_parameter) if first_parameter.isdigit() else 1
                line = lines[row]
                if command == "D":
                    column = max(0, column - max(amount, 1))
                elif command == "C":
                    column = min(len(line), column + max(amount, 1))
                elif command == "G":
                    column = min(len(line), max(amount - 1, 0))
                elif command == "K":
                    mode = amount if first_parameter.isdigit() else 0
                    if mode == 0:
                        del line[column:]
                    elif mode == 1:
                        del line[: min(column + 1, len(line))]
                        column = 0
                    elif mode == 2:
                        line.clear()
                        column = 0
                index = match.end()
                continue
            unsupported = _ANSI_ESCAPE_RE.match(value, index)
            if unsupported is not None:
                index = unsupported.end()
                continue
        if character == "\n":
            row += 1
            if row == len(lines):
                lines.append([])
            column = 0
        elif character == "\r":
            column = 0
        elif character == "\b":
            column = max(0, column - 1)
        elif character == "\t":
            spaces = 4 - (column % 4)
            line = lines[row]
            for _ in range(spaces):
                if column < len(line):
                    line[column] = " "
                else:
                    line.append(" ")
                column += 1
        elif ord(character) >= 32 and ord(character) != 127:
            line = lines[row]
            if column < len(line):
                line[column] = character
            else:
                if column > len(line):
                    line.extend(" " for _ in range(column - len(line)))
                line.append(character)
            column += 1
        index += 1
    return "\n".join("".join(line) for line in lines)


def _public_output_text(value: str) -> str:
    rendered = _render_terminal_text(value)
    return redact_text(rendered).replace("<redacted>", "[REDACTED]")


def _normalized_ollama_endpoint(endpoint: str) -> str | None:
    try:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            return None
        port = parsed.port
    except ValueError:
        return None
    netloc = parsed.hostname
    if ":" in netloc and not netloc.startswith("["):
        netloc = f"[{netloc}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit(("http", netloc, "", "", ""))


def _is_loopback_url(endpoint: str) -> bool:
    host = urlsplit(endpoint).hostname
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _loopback_env_prefix(endpoint: str) -> list[str]:
    if not _is_loopback_url(endpoint):
        raise ValueError("Ollama endpoint must be loopback")
    return [
        "env",
        "-u",
        "HTTP_PROXY",
        "-u",
        "HTTPS_PROXY",
        "-u",
        "ALL_PROXY",
        "-u",
        "http_proxy",
        "-u",
        "https_proxy",
        "-u",
        "all_proxy",
        f"OLLAMA_HOST={endpoint}",
        "NO_PROXY=localhost,127.0.0.1,::1",
        "no_proxy=localhost,127.0.0.1,::1",
    ]


def _hermetic_loopback_curl_command(
    *,
    executable: str,
    endpoint: str,
    path: str,
    max_time_seconds: int,
    method: Literal["GET", "POST"] = "GET",
    payload: str | None = None,
) -> list[str]:
    """Build a config-free, proxy-free curl request confined to loopback HTTP."""
    if not _is_loopback_url(endpoint):
        raise ValueError("Ollama endpoint must be loopback")
    if not path.startswith("/") or ".." in path:
        raise ValueError("Ollama API path must be absolute and bounded")
    command = _loopback_env_prefix(endpoint) + [
        executable,
        # curl requires --disable to be its first option to ignore ~/.curlrc.
        "--disable",
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--noproxy",
        "*",
        "--proto",
        "=http",
        "--proto-redir",
        "=http",
        "--max-redirs",
        "0",
        "--connect-timeout",
        "5",
        "--max-time",
        str(max_time_seconds),
        "--request",
        method,
        "--header",
        "Accept: application/json",
    ]
    if method == "POST":
        if payload is None:
            raise ValueError("Ollama POST payload is required")
        command.extend(
            [
                "--header",
                "Content-Type: application/json",
                "--data-binary",
                payload,
            ]
        )
    elif payload is not None:
        raise ValueError("Ollama GET request cannot include a payload")
    command.append(f"{endpoint}{path}")
    return command


def _parse_ollama_models(output: str) -> tuple[list[ProviderModel], list[str]]:
    """Admit only catalog entries with positive local-disk provenance.

    Modern Ollama exposes remote/cloud models through the same loopback API as
    local models. The catalog's ``remote_host``/``remote_model`` fields mark a
    remote entry; catalog-reported size, digest, and format are required for the
    remaining entries. This is runtime evidence, not an independent blob audit.
    """
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid Ollama model catalog JSON") from exc
    raw_models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        raise ValueError("invalid Ollama model catalog shape")

    models: list[ProviderModel] = []
    seen: set[str] = set()
    remote_count = 0
    unverifiable_count = 0
    for raw in raw_models[:500]:
        if not isinstance(raw, dict):
            unverifiable_count += 1
            continue
        model_id = raw.get("model") or raw.get("name")
        details = raw.get("details")
        size = raw.get("size")
        digest = raw.get("digest")
        remote_host = raw.get("remote_host")
        remote_model = raw.get("remote_model")
        if not isinstance(model_id, str) or not _safe_model_identifier(model_id):
            unverifiable_count += 1
            continue
        malformed_remote_metadata = (
            remote_host is not None
            and not isinstance(remote_host, str)
            or remote_model is not None
            and not isinstance(remote_model, str)
        )
        if malformed_remote_metadata:
            unverifiable_count += 1
            continue
        if remote_host or remote_model or _looks_like_ollama_cloud_model(model_id):
            remote_count += 1
            continue
        model_format = details.get("format") if isinstance(details, dict) else None
        local_proven = (
            isinstance(size, int)
            and not isinstance(size, bool)
            and size > 0
            and isinstance(digest, str)
            and bool(re.fullmatch(r"[0-9a-fA-F]{64}", digest))
            and isinstance(model_format, str)
            and bool(model_format.strip())
            and model_format.casefold() not in {"cloud", "remote"}
        )
        if not local_proven:
            unverifiable_count += 1
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        models.append(
            ProviderModel(
                provider_id="ollama",
                model_id=model_id,
                display_name=model_id,
                source="runtime_discovered",
                execution_location="local",
                locality_evidence=[
                    "loopback_api_tags",
                    "catalog_reported_positive_size",
                    "catalog_reported_sha256_digest",
                    "catalog_reported_local_format",
                    "catalog_no_remote_metadata",
                ],
            )
        )

    limitations: list[str] = []
    if remote_count:
        limitations.append(
            f"excluded {remote_count} remote/cloud Ollama model(s) from Personal AI execution"
        )
    if unverifiable_count:
        limitations.append(
            f"excluded {unverifiable_count} Ollama model(s) without complete local catalog evidence"
        )
    if models:
        limitations.append(
            "model locality is based on bounded Ollama catalog metadata, not an independent blob audit"
        )
    return models, limitations


def _safe_model_identifier(value: str) -> bool:
    return (
        bool(value)
        and not value.startswith("-")
        and len(value) <= 200
        and all(character.isalnum() or character in "._:/-" for character in value)
    )


def _looks_like_ollama_cloud_model(model_id: str) -> bool:
    lowered = model_id.casefold()
    tag = lowered.rsplit(":", 1)[-1]
    return tag == "cloud" or tag.endswith("-cloud") or lowered.endswith("-cloud")


def _mock_structured_payload(message: str, schema: dict[str, Any]) -> dict[str, Any]:
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    if "candidate_urls" in required:
        return {
            "research_question": message[:200],
            "subquestions": ["What primary sources exist?", "What claims are causal vs associative?"],
            "queries": [{"query": "medicare oral health screening older adults", "purpose": "policy"}],
            "candidate_urls": [
                {
                    "url": "https://www.cms.gov/",
                    "why": "authoritative Medicare/CMS host",
                    "source_type": "government_policy",
                }
            ],
            "limitations": ["mock research payload; not live evidence"],
        }
    if "evidence" in required:
        return {
            "evidence": [
                {
                    "source_url": "https://www.cms.gov/",
                    "claim": "CMS publishes Medicare coverage and screening policy material.",
                    "passage": "Medicare coverage determinations are published by CMS.",
                    "summary": "Policy host, not a causal trial.",
                    "evidence_strength": "policy_document",
                    "causal_class": "association",
                    "relation": "neutral",
                    "study_design": "government document",
                    "limitations": "Does not establish periodontal causation.",
                }
            ],
            "disagreements": [
                {
                    "topic": "systemic causal claims",
                    "positions": ["association is documented", "causation is not established by this source"],
                }
            ],
        }
    if "synthesis" in required:
        return {
            "synthesis": (
                "Mock research synthesis: treat CMS material as policy context and do not "
                "convert oral-health association into Medicare-entry causation. [ev-mock]"
            ),
            "citations": [{"claim_span": "policy context", "evidence_id": "ev-mock"}],
            "unresolved": ["Live literature retrieval was not used in this mock payload"],
            "causal_caution": "Association is not causation.",
        }
    return {"mock": True, "message": message[:200]}


__all__ = [
    "CancellationToken",
    "ChatProvider",
    "DiscoveryOnlyChatProvider",
    "EngineBackedChatProvider",
    "MockChatProvider",
    "OllamaChatProvider",
    "ProviderCapabilities",
    "ProviderError",
    "ProviderEvent",
    "ProviderHealth",
    "ProviderModel",
    "ProviderModelCatalog",
    "ProviderRegistry",
    "ProviderRequest",
    "ProviderResult",
    "ProviderRoutingProfile",
    "ProviderStatus",
    "ProviderToolEvent",
    "ProviderUsage",
]
