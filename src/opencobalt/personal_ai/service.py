"""Traceable chat request lifecycle for OpenCobalt's personal-AI control plane.

The service owns orchestration, never provider-specific argv.  Provider work is
delegated to :mod:`opencobalt.personal_ai.providers`, whose executable paths all
flow through ``ExecutionEngine``.  Routing and execution remain deliberately
separate so a failed or denied request still leaves an inspectable route record.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from opencobalt.execution.runner import redact_text

from .models import (
    ChatExecution,
    ChatMessage,
    Conversation,
    MemoryEntry,
    PersonaVersion,
    RouteCandidate,
    RouteRecord,
    StreamEvent,
)
from .personas import ensure_builtin_personas, render_persona_policy
from .providers import (
    CancellationToken,
    ProviderError,
    ProviderRegistry,
    ProviderRequest,
    ProviderUsage,
)
from .router import (
    NoEligibleRouteError,
    PersonalAIRouter,
    ProviderSnapshot,
    RoutingRequest,
    approval_requirements,
    classify_complexity,
    classify_privacy,
    classify_risk,
    classify_task,
)
from .store import PersonalAIStore


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


_FALLBACK_ERROR_CATEGORIES = {
    "authentication",
    "provider_error",
    "rate_limited",
    "timeout",
    "unavailable",
}

class ChatRequest(BaseModel):
    """User and policy inputs for one routed chat request."""

    conversation_id: str
    message: str = Field(min_length=1, max_length=100_000)
    persona_id: str = "analytical"
    cognitive_policy: str | None = None
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "medium"
    privacy_mode: Literal["standard", "private", "sensitive"] | None = None
    local_only: bool | None = None
    provider_override: str | None = None
    model_override: str | None = None
    requested_tools: list[str] = Field(default_factory=list, max_length=50)
    requested_skills: list[str] = Field(default_factory=list, max_length=50)
    allow_fallback: bool = False
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message cannot be blank")
        return value

    @field_validator("conversation_id", "persona_id", "provider_override", "model_override")
    @classmethod
    def _bounded_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or len(value) > 200 or value.startswith("-"):
            raise ValueError("identifier must be a bounded non-flag value")
        return value

    @field_validator("requested_tools", "requested_skills")
    @classmethod
    def _bounded_capability_ids(cls, value: list[str]) -> list[str]:
        if any(
            not item
            or len(item) > 100
            or item.startswith("-")
            or any(
                not (character.isalnum() or character in "._:/-")
                for character in item
            )
            for item in value
        ):
            raise ValueError("tool and skill identifiers must be bounded non-flag values")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _model_override_requires_provider(self) -> ChatRequest:
        if self.model_override is not None and self.provider_override is None:
            raise ValueError("model override requires a provider override")
        return self


class ChatLifecycleEvent(BaseModel):
    """Stable NDJSON-facing event shape emitted by the lifecycle service."""

    event_type: str
    request_id: str
    conversation_id: str
    route_id: str | None = None
    execution_id: str | None = None
    sequence: int = Field(ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class ChatService:
    """Classify, route, execute, persist, and explain one chat request."""

    def __init__(
        self,
        *,
        store: PersonalAIStore,
        providers: ProviderRegistry,
        router: PersonalAIRouter | None = None,
        enable_mock: bool = False,
    ) -> None:
        self.store = store
        self.providers = providers
        self.router = router or PersonalAIRouter()
        self.enable_mock = enable_mock
        self._cancellations: dict[str, CancellationToken] = {}
        self._cancellation_lock = threading.Lock()
        ensure_builtin_personas(self.store)

    def create_conversation(
        self,
        *,
        title: str = "New conversation",
        project_path: str | None = None,
    ) -> Conversation:
        return self.store.create_conversation(title=title, project_path=project_path)

    def stream_request(self, request: ChatRequest) -> Iterator[ChatLifecycleEvent]:
        """Execute the complete durable lifecycle and yield normalized events."""
        conversation = self.store.get_conversation(request.conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {request.conversation_id}")
        persona_version = self._persona_version(request.persona_id)
        cognitive_policy = self._cognitive_policy(persona_version, request.cognitive_policy)
        settings = self.store.get_settings()
        request_id = _uid("req")
        user_message = self.store.add_message(
            conversation.conversation_id,
            role="user",
            content=request.message,
            persona_version_id=persona_version.persona_version_id,
            metadata={
                "requested_persona_id": request.persona_id,
                "cognitive_policy": cognitive_policy,
                **request.metadata,
            },
        )
        routing_request = RoutingRequest(
            request_id=request_id,
            conversation_id=conversation.conversation_id,
            request_message_id=user_message.message_id,
            prompt=request.message,
            requested_persona_id=request.persona_id,
            settings=settings,
            privacy_mode=request.privacy_mode,
            cognitive_policy=cognitive_policy,
            reasoning_effort=request.reasoning_effort,
            local_only=request.local_only,
            provider_override=request.provider_override,
            model_override=request.model_override,
            requested_tools=tuple(request.requested_tools),
            requested_skills=tuple(request.requested_skills),
        )
        snapshots = self._provider_snapshots(routing_request)

        try:
            plan = self.router.route(
                routing_request,
                snapshots,
                persona_version=persona_version,
            )
        except NoEligibleRouteError as exc:
            route = self._persist_denied_route(
                routing_request,
                persona_version,
                exc.candidates,
                metadata=request.metadata,
            )
            self.store.update_message(user_message.message_id, route_id=route.route_id)
            yield ChatLifecycleEvent(
                event_type="request_accepted",
                request_id=request_id,
                conversation_id=conversation.conversation_id,
                route_id=route.route_id,
                sequence=1,
                payload={"message_id": user_message.message_id},
            )
            yield ChatLifecycleEvent(
                event_type="route_failed",
                request_id=request_id,
                conversation_id=conversation.conversation_id,
                route_id=route.route_id,
                sequence=2,
                payload={
                    "error": {
                        "category": "policy_denied",
                        "message": "No eligible route satisfies the current provider and policy constraints.",
                    },
                    "reasons": route.reasons,
                },
            )
            return

        route = plan.record.model_copy(
            update={"metadata": {**plan.record.metadata, **request.metadata}}
        )
        self.store.save_route(route)
        for candidate in plan.candidates:
            self.store.save_route_candidate(candidate)
        self.store.update_message(user_message.message_id, route_id=route.route_id)

        eligible_candidates = [candidate for candidate in plan.candidates if candidate.eligible]
        yield from self._execute_route(
            request=request,
            routing_request=routing_request,
            route=route,
            candidates=eligible_candidates,
            persona_version=persona_version,
            cognitive_policy=cognitive_policy,
            conversation=conversation,
            user_message=user_message,
        )

    def cancel(self, execution_id: str) -> bool:
        """Request cooperative cancellation and persist the request state."""
        with self._cancellation_lock:
            cancellation = self._cancellations.pop(execution_id, None)
        if cancellation is None:
            return False
        cancellation.cancel()
        execution = self.store.get_execution(execution_id)
        if execution is not None and execution.status in {"queued", "running"}:
            now = _now()
            self.store.save_execution(
                execution.model_copy(
                    update={"status": "cancel_requested", "updated_at": now}
                )
            )
        return True

    def rerun(
        self,
        route_id: str,
        *,
        persona_id: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None,
        cognitive_policy: str | None = None,
        local_only: bool | None = None,
        allow_fallback: bool = False,
    ) -> Iterator[ChatLifecycleEvent]:
        route = self.store.get_route(route_id)
        if route is None:
            raise KeyError(f"unknown route: {route_id}")
        source = self.store.get_message(route.request_message_id)
        if source is None:
            raise RuntimeError(f"route request message is missing: {route.request_message_id}")
        selected_persona = persona_id or route.requested_persona_id
        preserve_policy = persona_id is None or selected_persona == route.requested_persona_id
        inherited_policy = route.metadata.get("cognitive_policy") if preserve_policy else None
        selected_provider = provider_id or route.selected_provider
        inherited_model = (
            route.selected_model
            if provider_id is None or provider_id == route.selected_provider
            else None
        )
        return self.stream_request(
            ChatRequest(
                conversation_id=route.conversation_id,
                message=source.content,
                persona_id=selected_persona,
                cognitive_policy=cognitive_policy or inherited_policy,
                reasoning_effort=reasoning_effort or route.metadata.get("reasoning_effort", "medium"),
                privacy_mode=route.metadata.get("privacy_mode"),
                local_only=local_only,
                provider_override=selected_provider,
                model_override=model_id if model_id is not None else inherited_model,
                allow_fallback=allow_fallback,
                metadata={"rerun_of_route_id": route_id},
            )
        )

    def compare(self, first_message_id: str, second_message_id: str) -> list[dict[str, Any]]:
        """Return two completed responses with their independently stored routes."""
        result: list[dict[str, Any]] = []
        for message_id in (first_message_id, second_message_id):
            message = self.store.get_message(message_id)
            if message is None:
                raise KeyError(f"unknown message: {message_id}")
            if message.role != "assistant" or message.route_id is None:
                raise ValueError("comparison requires routed assistant messages")
            route = self.store.get_route(message.route_id)
            if route is None:
                raise RuntimeError(f"message route is missing: {message.route_id}")
            result.append(
                {
                    "message": message.model_dump(mode="json"),
                    "route": route.model_dump(mode="json"),
                }
            )
        return result

    def _execute_route(
        self,
        *,
        request: ChatRequest,
        routing_request: RoutingRequest,
        route: RouteRecord,
        candidates: Sequence[RouteCandidate],
        persona_version: PersonaVersion,
        cognitive_policy: str,
        conversation: Conversation,
        user_message: ChatMessage,
    ) -> Iterator[ChatLifecycleEvent]:
        stream_sequence = 0

        def lifecycle(
            event_type: str,
            *,
            execution: ChatExecution | None,
            payload: dict[str, Any] | None = None,
        ) -> ChatLifecycleEvent:
            nonlocal stream_sequence
            stream_sequence += 1
            return ChatLifecycleEvent(
                event_type=event_type,
                request_id=routing_request.request_id,
                conversation_id=conversation.conversation_id,
                route_id=route.route_id,
                execution_id=execution.execution_id if execution else None,
                sequence=stream_sequence,
                payload=payload or {},
            )

        ordered = list(candidates)
        selected_index = next(
            (
                index
                for index, candidate in enumerate(ordered)
                if candidate.provider_id == route.selected_provider
                and candidate.model_id == route.selected_model
            ),
            0,
        )
        ordered = ordered[selected_index:] + ordered[:selected_index]
        if not ordered:
            raise RuntimeError("selected route has no eligible candidate")

        current: ChatExecution | None = None
        final_content = ""
        final_usage = ProviderUsage()
        final_receipt_id: str | None = None
        final_error: ProviderError | None = None
        attempt_index = 0

        while attempt_index < len(ordered):
            candidate = ordered[attempt_index]
            current = ChatExecution(
                request_id=routing_request.request_id,
                route_id=route.route_id,
                conversation_id=conversation.conversation_id,
                provider_id=candidate.provider_id,
                model_id=candidate.model_id,
                status="running",
                started_at=_now(),
            )
            self.store.save_execution(current)
            cancellation = CancellationToken()
            with self._cancellation_lock:
                self._cancellations[current.execution_id] = cancellation

            if attempt_index == 0:
                accepted = lifecycle(
                    "request_accepted",
                    execution=current,
                    payload={"message_id": user_message.message_id},
                )
                self._persist_lifecycle_event(current, accepted)
                yield accepted
                selected = lifecycle(
                    "route_selected",
                    execution=current,
                    payload={
                        "route": route.model_dump(mode="json"),
                        "candidate_count": len(candidates),
                    },
                )
                self._persist_lifecycle_event(current, selected)
                yield selected
            else:
                fallback = route.fallback_events[-1]
                event = lifecycle(
                    "fallback_started",
                    execution=current,
                    payload=fallback,
                )
                self._persist_lifecycle_event(current, event)
                yield event

            started = lifecycle(
                "execution_started",
                execution=current,
                payload={
                    "provider_id": candidate.provider_id,
                    "model_id": candidate.model_id,
                    "attempt": attempt_index + 1,
                },
            )
            self._persist_lifecycle_event(current, started)
            yield started

            provider = self.providers.get(candidate.provider_id)
            rendered_policy = render_persona_policy(persona_version, cognitive_policy)
            provider_request = ProviderRequest(
                request_id=routing_request.request_id,
                conversation_id=conversation.conversation_id,
                message=request.message,
                system_policy=self._provider_policy(
                    conversation,
                    user_message,
                    rendered_policy,
                    route,
                ),
                model_id=candidate.model_id,
                local_only=bool(route.metadata.get("local_only", False)),
                allow_fallback=False,
                timeout_seconds=request.timeout_seconds,
                cwd=conversation.project_path,
                metadata={
                    "route_id": route.route_id,
                    "persona_version_id": persona_version.persona_version_id,
                },
            )
            attempt_content = ""
            attempt_usage = ProviderUsage()
            attempt_receipt: str | None = None
            attempt_error: ProviderError | None = None
            terminal_type: str | None = None
            try:
                provider_events = provider.stream(provider_request, cancellation)
                for provider_event in provider_events:
                    attempt_receipt = provider_event.receipt_id or attempt_receipt
                    if provider_event.event_type == "started":
                        normalized_type = "provider_started"
                        payload = {
                            "provider_id": provider_event.provider_id,
                            "receipt_id": provider_event.receipt_id,
                        }
                    elif provider_event.event_type == "text_delta":
                        delta = provider_event.text_delta or ""
                        attempt_content += delta
                        normalized_type = "text_delta"
                        payload = {"text_delta": delta}
                    elif provider_event.event_type == "usage":
                        attempt_usage = provider_event.usage or ProviderUsage()
                        normalized_type = "usage"
                        payload = {"usage": attempt_usage.model_dump(mode="json")}
                    elif provider_event.event_type == "tool_completed":
                        normalized_type = "tool_completed"
                        payload = {
                            "tool_event": (
                                provider_event.tool_event.model_dump(mode="json")
                                if provider_event.tool_event
                                else {"status": "unknown"}
                            )
                        }
                    elif provider_event.event_type == "completed":
                        terminal_type = "completed"
                        normalized_type = "provider_completed"
                        payload = {"receipt_id": provider_event.receipt_id}
                    else:
                        terminal_type = provider_event.event_type
                        attempt_error = provider_event.error or ProviderError(
                            category=(
                                "cancelled"
                                if provider_event.event_type == "cancelled"
                                else "provider_error"
                            ),
                            message=(
                                "request cancelled"
                                if provider_event.event_type == "cancelled"
                                else "provider execution failed"
                            ),
                        )
                        normalized_type = provider_event.event_type
                        payload = {
                            "error": attempt_error.model_dump(mode="json"),
                            "receipt_id": provider_event.receipt_id,
                        }
                    event = lifecycle(normalized_type, execution=current, payload=payload)
                    self._persist_lifecycle_event(current, event)
                    yield event
            except Exception as exc:  # provider boundary must become inspectable
                terminal_type = "error"
                attempt_error = ProviderError(
                    category="provider_error",
                    message=redact_text(str(exc))[:500] or "provider execution failed",
                )

            if terminal_type == "completed" and attempt_content.strip():
                final_content = attempt_content
                final_usage = attempt_usage
                final_receipt_id = attempt_receipt
                final_error = None
                break
            if terminal_type == "completed" and not attempt_content.strip():
                attempt_error = ProviderError(
                    category="provider_error",
                    message="provider completed without a usable response",
                )
                terminal_type = "error"

            final_receipt_id = attempt_receipt
            final_error = attempt_error or ProviderError(
                category="provider_error", message="provider execution failed"
            )
            is_cancelled = terminal_type == "cancelled" or final_error.category == "cancelled"
            current = self._finish_execution(
                current,
                status="cancelled" if is_cancelled else "failed",
                receipt_id=attempt_receipt,
                usage=attempt_usage,
                error=final_error,
            )
            with self._cancellation_lock:
                self._cancellations.pop(current.execution_id, None)
            if is_cancelled:
                route = self._finish_route(
                    route,
                    status="cancelled",
                    receipt_id=attempt_receipt,
                    usage=attempt_usage,
                )
                cancelled = lifecycle(
                    "cancelled",
                    execution=current,
                    payload={"error": final_error.model_dump(mode="json")},
                )
                self._persist_lifecycle_event(current, cancelled)
                yield cancelled
                return

            next_candidate = ordered[attempt_index + 1] if attempt_index + 1 < len(ordered) else None
            can_fallback = (
                request.allow_fallback
                and next_candidate is not None
                and final_error.category in _FALLBACK_ERROR_CATEGORIES
            )
            if not can_fallback:
                route = self._finish_route(
                    route,
                    status="failed",
                    receipt_id=attempt_receipt,
                    usage=attempt_usage,
                )
                error_event = lifecycle(
                    "error",
                    execution=current,
                    payload={
                        "error": final_error.model_dump(mode="json"),
                        "fallback_allowed": request.allow_fallback,
                        "fallback_used": False,
                    },
                )
                self._persist_lifecycle_event(current, error_event)
                yield error_event
                return

            fallback_event = {
                "from_provider": candidate.provider_id,
                "from_model": candidate.model_id,
                "to_provider": next_candidate.provider_id,
                "to_model": next_candidate.model_id,
                "reason_category": final_error.category,
                "reason": final_error.message,
                "failed_receipt_id": attempt_receipt,
                "created_at": _now().isoformat(),
            }
            route = route.model_copy(
                update={
                    "fallback_events": [*route.fallback_events, fallback_event],
                    "updated_at": _now(),
                }
            )
            self.store.save_route(route)
            attempt_index += 1

        if current is None or not final_content.strip():
            raise RuntimeError("route execution ended without a terminal result")

        assistant = self.store.add_message(
            conversation.conversation_id,
            role="assistant",
            content=final_content,
            status="complete",
            persona_version_id=route.actual_persona_version_id,
            route_id=route.route_id,
            parent_message_id=user_message.message_id,
            metadata={
                "requested_persona_id": route.requested_persona_id,
                "actual_persona_id": route.actual_persona_id,
                "provider_id": current.provider_id,
                "model_id": current.model_id,
                "persona_provider_mismatch": route.persona_provider_mismatch,
            },
        )
        current = self._finish_execution(
            current,
            status="complete",
            receipt_id=final_receipt_id,
            usage=final_usage,
            assistant_message_id=assistant.message_id,
        )
        with self._cancellation_lock:
            self._cancellations.pop(current.execution_id, None)
        route = self._finish_route(
            route,
            status="complete",
            receipt_id=final_receipt_id,
            usage=final_usage,
            actual_provider_id=current.provider_id,
            actual_model_id=current.model_id,
            verification=self._verification_record(
                route.verification_strategy,
                content=final_content,
                receipt_id=final_receipt_id,
            ),
        )
        memory = self._propose_explicit_memory(request, user_message)
        completed = lifecycle(
            "completed",
            execution=current,
            payload={
                "message": assistant.model_dump(mode="json"),
                "route": route.model_dump(mode="json"),
                "receipt_id": final_receipt_id,
                "memory_proposal_id": memory.memory_id if memory else None,
            },
        )
        self._persist_lifecycle_event(current, completed)
        yield completed

    def _provider_snapshots(self, request: RoutingRequest) -> list[ProviderSnapshot]:
        preferences = {
            preference.provider_id: preference
            for preference in self.store.list_provider_preferences()
        }
        settings_order = {
            provider_id: max(-10, 10 - index)
            for index, provider_id in enumerate(request.settings.provider_priority[:20])
        }
        historical_signals = self._historical_success_signals()
        snapshots: list[ProviderSnapshot] = []
        statuses = self.providers.discover()
        real_provider_available = any(
            status.provider_id != "mock" and status.execution_supported
            for status in statuses
        )
        for status in statuses:
            profile = status.routing_profile
            preference = preferences.get(status.provider_id)
            available = status.execution_supported
            if status.provider_id == "mock":
                available = self.enable_mock and (
                    request.provider_override == "mock" or not real_provider_available
                )
            if preference is not None:
                available = available and preference.enabled
                if (
                    preference.cost_policy == "free_only"
                    and profile.cost_category != "free"
                ):
                    available = False

            models: list[str | None] = [None]
            if available and status.capabilities.model_discovery:
                catalog = self.providers.get(status.provider_id).discover_models(
                    local_only=bool(request.local_only)
                )
                discovered = [model.model_id for model in catalog.models]
                if discovered:
                    models = discovered
                elif status.provider_id == "ollama":
                    available = False
            if request.model_override and status.provider_id == request.provider_override:
                models = [request.model_override]

            preference_score = 0
            if preference is not None:
                preference_score = max(-10, min(10, round((preference.priority - 50) / 5)))
            priority = max(preference_score, settings_order.get(status.provider_id, 0))
            for model_id in models:
                snapshots.append(
                    ProviderSnapshot(
                        provider_id=status.provider_id,
                        model_id=model_id,
                        runtime_id=status.runtime_id,
                        provider_family=profile.provider_family,
                        available=available,
                        local=status.capabilities.local_only_eligible,
                        requires_network=status.capabilities.requires_network,
                        cost_category=profile.cost_category,
                        quality_tier=profile.quality_tier,
                        capabilities=frozenset(profile.task_capabilities),
                        tool_names=frozenset(profile.tool_names),
                        latency_category=profile.latency_category,
                        historical_success_signal=historical_signals.get(
                            status.provider_id, 0
                        ),
                        provider_priority=priority,
                    )
                )
        return snapshots

    def _historical_success_signals(self) -> dict[str, int]:
        """Derive a small bounded routing signal from local outcome history."""
        grouped: dict[str, list[str]] = {}
        for execution in self.store.list_executions(limit=200):
            outcomes = grouped.setdefault(execution.provider_id, [])
            if len(outcomes) < 20 and execution.status in {
                "complete",
                "failed",
                "cancelled",
            }:
                outcomes.append(execution.status)
        signals: dict[str, int] = {}
        for provider_id, outcomes in grouped.items():
            successes = outcomes.count("complete")
            failures = len(outcomes) - successes
            signals[provider_id] = max(-10, min(10, 2 * (successes - failures)))
        return signals

    def _persist_denied_route(
        self,
        request: RoutingRequest,
        persona_version: PersonaVersion,
        candidates: Sequence[RouteCandidate],
        *,
        metadata: dict[str, Any],
    ) -> RouteRecord:
        task_class = classify_task(request.prompt, request.cognitive_policy)
        complexity = classify_complexity(
            request.prompt,
            task_class,
            request.cognitive_policy,
            request.reasoning_effort,
        )
        privacy = classify_privacy(
            request.prompt,
            task_class,
            request.privacy_mode,
            request.settings.privacy_policy,
        )
        risk = classify_risk(request.prompt, task_class)
        rejection_reasons = list(
            dict.fromkeys(
                candidate.rejection_reason
                for candidate in candidates
                if candidate.rejection_reason
            )
        )
        route = RouteRecord(
            route_id=f"route-{request.request_id}",
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            request_message_id=request.request_message_id,
            task_class=task_class,
            task_complexity=complexity,
            selected_provider="none",
            requested_persona_id=request.requested_persona_id,
            requested_persona_version_id=persona_version.persona_version_id,
            actual_persona_id=request.requested_persona_id,
            actual_persona_version_id=persona_version.persona_version_id,
            privacy_classification=privacy,
            autonomy_level={
                "green": "answer_only",
                "yellow": "review_before_action",
                "red": "approval_required",
            }[risk],
            approval_requirements=approval_requirements(risk),
            estimated_cost_category="unknown",
            expected_latency_category={
                "simple": "low",
                "moderate": "standard",
                "complex": "high",
            }[complexity],
            route_score=max((candidate.score for candidate in candidates), default=0),
            reasons=["no eligible route", *rejection_reasons],
            verification_strategy="not_executed",
            outcome_status="policy_denied",
            metadata={
                "routing": "deterministic_snapshot_v1",
                "risk_classification": risk,
                "local_only": (
                    request.settings.local_only_default
                    if request.local_only is None
                    else request.local_only
                ),
                "privacy_mode": request.privacy_mode,
                "privacy_policy": request.settings.privacy_policy,
                "cognitive_policy": request.cognitive_policy,
                "reasoning_effort": request.reasoning_effort,
                **metadata,
            },
        )
        self.store.save_route(route)
        for candidate in candidates:
            self.store.save_route_candidate(candidate)
        return route

    def _persona_version(self, persona_id: str) -> PersonaVersion:
        version = self.store.get_active_persona_version(persona_id)
        if version is None:
            raise KeyError(f"unknown or unversioned persona: {persona_id}")
        return version

    @staticmethod
    def _cognitive_policy(version: PersonaVersion, requested: str | None) -> str:
        if requested is not None:
            if requested not in version.allowed_cognitive_policies:
                raise ValueError(
                    f"cognitive policy {requested!r} is not allowed by persona {version.persona_id}"
                )
            return requested
        preferred = {
            "analytical": "fast_answer",
            "reflective": "emotional_reflection",
            "exploratory": "creative_divergence",
            "builder": "implementation",
        }.get(version.persona_id, "fast_answer")
        if preferred in version.allowed_cognitive_policies:
            return preferred
        if not version.allowed_cognitive_policies:
            raise ValueError(f"persona {version.persona_id} allows no cognitive policies")
        return version.allowed_cognitive_policies[0]

    def _provider_policy(
        self,
        conversation: Conversation,
        user_message: ChatMessage,
        persona_policy: str,
        route: RouteRecord,
    ) -> str:
        prior = [
            message
            for message in self.store.list_messages(conversation.conversation_id, limit=30)
            if message.message_id != user_message.message_id
        ][-10:]
        history = "\n".join(
            f"{message.role.title()}: {message.content[:3000]}" for message in prior
        )
        sections = [
            "OpenCobalt interaction policy:",
            persona_policy,
            "",
            "Execution constraints:",
            "Answer the request only. Do not modify files, run tools, or take external actions unless the route explicitly selected those capabilities and the user explicitly requested the action.",
            f"Privacy classification: {route.privacy_classification}",
            f"Local-only: {bool(route.metadata.get('local_only', False))}",
        ]
        if route.persona_provider_mismatch:
            sections.append(f"Persona/provider disclosure: {route.persona_provider_mismatch}")
        if history:
            sections.extend(["", "Recent conversation context:", history])
        return "\n".join(sections)

    def _persist_lifecycle_event(
        self, execution: ChatExecution, event: ChatLifecycleEvent
    ) -> None:
        sequence = len(self.store.list_stream_events(execution.execution_id)) + 1
        self.store.append_stream_event(
            StreamEvent(
                execution_id=execution.execution_id,
                sequence=sequence,
                event_type=event.event_type,
                payload=event.payload,
            )
        )

    def _finish_execution(
        self,
        execution: ChatExecution,
        *,
        status: Literal["complete", "failed", "cancelled"],
        receipt_id: str | None,
        usage: ProviderUsage,
        error: ProviderError | None = None,
        assistant_message_id: str | None = None,
    ) -> ChatExecution:
        now = _now()
        finished = execution.model_copy(
            update={
                "status": status,
                "provider_error_type": error.category if error else None,
                "provider_error_message": error.message if error else None,
                "work_receipt_id": receipt_id,
                "assistant_message_id": assistant_message_id,
                "usage": usage.model_dump(mode="json"),
                "finished_at": now,
                "updated_at": now,
            }
        )
        self.store.save_execution(finished)
        return finished

    def _finish_route(
        self,
        route: RouteRecord,
        *,
        status: str,
        receipt_id: str | None,
        usage: ProviderUsage,
        actual_provider_id: str | None = None,
        actual_model_id: str | None = None,
        verification: dict[str, Any] | None = None,
    ) -> RouteRecord:
        metadata = dict(route.metadata)
        if verification is not None:
            metadata["verification"] = verification
        if actual_provider_id is not None:
            metadata["actual_provider_id"] = actual_provider_id
            metadata["actual_model_id"] = actual_model_id
        finished = route.model_copy(
            update={
                "outcome_status": status,
                "receipt_id": receipt_id,
                "actual_usage": usage.model_dump(mode="json"),
                "metadata": metadata,
                "updated_at": _now(),
            }
        )
        self.store.save_route(finished)
        return finished

    def _propose_explicit_memory(
        self, request: ChatRequest, user_message: ChatMessage
    ) -> MemoryEntry | None:
        prefix = "remember that "
        stripped = request.message.strip()
        if not stripped.lower().startswith(prefix):
            return None
        if self.store.get_settings().memory_behavior == "off":
            return None
        content = stripped[len(prefix) :].strip().rstrip(".")
        if not content:
            return None
        memory = MemoryEntry(
            content=content,
            source_type="explicit_user_request",
            source_ref=user_message.message_id,
            reason="User explicitly asked OpenCobalt to remember this fact",
            scope="user",
            status="proposed",
            sensitivity=(
                "sensitive"
                if any(term in content.lower() for term in ("secret", "password", "token"))
                else "normal"
            ),
            conversation_id=user_message.conversation_id,
            source_message_id=user_message.message_id,
            metadata={"activation_requires_user_review": True},
        )
        self.store.save_memory(memory)
        return memory

    @staticmethod
    def _verification_record(
        strategy: str,
        *,
        content: str,
        receipt_id: str | None,
    ) -> dict[str, Any]:
        integrity_passed = bool(content.strip() and receipt_id)
        if strategy == "response_integrity":
            return {
                "strategy": strategy,
                "status": "passed" if integrity_passed else "failed",
                "checks_performed": ["nonempty_response", "execution_receipt_linked"],
                "limitations": [],
            }
        return {
            "strategy": strategy,
            "status": "not_performed",
            "checks_performed": ["nonempty_response", "execution_receipt_linked"],
            "integrity_check": "passed" if integrity_passed else "failed",
            "limitations": [
                f"the requested {strategy} verifier was not executed by this completion-only route"
            ],
        }


__all__ = ["ChatLifecycleEvent", "ChatRequest", "ChatService"]
