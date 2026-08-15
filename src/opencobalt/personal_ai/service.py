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
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from opencobalt.execution.runner import redact_text

from .conversation_routing import ConversationRoutingUpdate
from .lifecycle import RequestLifecycle, outcome_status_for_phase, phase_label
from .models import (
    ChatExecution,
    ChatMessage,
    Conversation,
    ConversationRoutingSettings,
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
    classify_capability_role,
    classify_complexity,
    classify_privacy,
    classify_requirements,
    classify_risk,
    classify_task,
    has_explicit_format_constraint,
    resolve_persona_for_provider,
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


def _safe_diagnostic(value: str) -> str:
    """Bound and redact provider diagnostics before persistence or streaming."""
    return redact_text(value).replace(str(Path.home()), "<home>")[:500]


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
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)
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

    @field_validator("requested_tools", "requested_skills", "attachment_ids")
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
            raise ValueError("tool, skill, and attachment identifiers must be bounded non-flag values")
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
        missions: Any | None = None,
        engine: Any | None = None,
        approval_coordinator: Any | None = None,
    ) -> None:
        self.store = store
        self.providers = providers
        self.router = router or PersonalAIRouter()
        self.enable_mock = enable_mock
        self.missions = missions
        self.engine = engine
        self.approval_coordinator = approval_coordinator
        self._cancellations: dict[str, CancellationToken] = {}
        self._request_tokens: dict[str, CancellationToken] = {}
        self._cancellation_lock = threading.Lock()
        ensure_builtin_personas(self.store)

    def create_conversation(
        self,
        *,
        title: str = "New conversation",
        project_path: str | None = None,
    ) -> Conversation:
        from .conversation_routing import (
            default_conversation_routing,
            merge_routing_metadata,
        )

        routing = default_conversation_routing(self.store.get_settings())
        return self.store.create_conversation(
            title=title,
            project_path=project_path,
            metadata=merge_routing_metadata({}, routing),
        )

    def conversation_routing(self, conversation_id: str) -> ConversationRoutingSettings:
        from .conversation_routing import parse_conversation_routing

        conversation = self.store.get_conversation(conversation_id)
        if conversation is None:
            raise KeyError(conversation_id)
        return parse_conversation_routing(conversation.metadata, self.store.get_settings())

    def update_conversation_routing(
        self, conversation_id: str, update: ConversationRoutingUpdate
    ) -> ConversationRoutingSettings:
        return self.store.apply_conversation_routing_update(
            conversation_id,
            update,
            self.store.get_settings(),
        )

    def stream_request(self, request: ChatRequest) -> Iterator[ChatLifecycleEvent]:
        """Execute the complete durable lifecycle and yield normalized events."""
        conversation = self.store.get_conversation(request.conversation_id)
        if conversation is None:
            raise KeyError(f"unknown conversation: {request.conversation_id}")
        persona_version = self._persona_version(request.persona_id)
        cognitive_policy = self._cognitive_policy(persona_version, request.cognitive_policy)
        settings = self.store.get_settings()
        request_id = _uid("req")
        lifecycle = RequestLifecycle(request_id)
        user_message = self.store.add_message(
            conversation.conversation_id,
            role="user",
            content=request.message,
            persona_version_id=persona_version.persona_version_id,
            metadata={
                "requested_persona_id": request.persona_id,
                "cognitive_policy": cognitive_policy,
                "attachment_ids": list(request.attachment_ids),
                **request.metadata,
            },
        )
        accepted = ChatLifecycleEvent(
            event_type="request_accepted",
            request_id=request_id,
            conversation_id=conversation.conversation_id,
            sequence=1,
            payload={
                "message_id": user_message.message_id,
                "lifecycle": lifecycle.snapshot(),
                "phase_label": phase_label(lifecycle.phase),
            },
        )
        yield accepted
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
            attachment_ids=tuple(request.attachment_ids),
            project_path=conversation.project_path,
        )
        cancellation = CancellationToken()
        with self._cancellation_lock:
            self._request_tokens[request_id] = cancellation
        lifecycle.enter("checking_capabilities")
        yield ChatLifecycleEvent(
            event_type="phase_changed",
            request_id=request_id,
            conversation_id=conversation.conversation_id,
            sequence=2,
            payload={
                "lifecycle": lifecycle.snapshot(),
                "phase_label": phase_label(lifecycle.phase),
            },
        )
        snapshots = self._provider_snapshots(routing_request, persona_version)

        lifecycle.enter("routing")
        try:
            plan = self.router.route(
                routing_request,
                snapshots,
                persona_version=persona_version,
            )
        except NoEligibleRouteError as exc:
            lifecycle.enter("blocked")
            route = self._persist_denied_route(
                routing_request,
                persona_version,
                exc.candidates,
                metadata={**request.metadata, "lifecycle": lifecycle.snapshot()},
            )
            self.store.update_message(user_message.message_id, route_id=route.route_id)
            denied_message = self.store.add_message(
                conversation.conversation_id,
                role="assistant",
                content=(
                    "OpenCobalt did not execute this request: no eligible provider route "
                    "satisfies the current provider and policy constraints."
                ),
                status="failed",
                persona_version_id=route.actual_persona_version_id,
                route_id=route.route_id,
                parent_message_id=user_message.message_id,
                metadata={
                    "requested_persona_id": route.requested_persona_id,
                    "actual_persona_id": route.actual_persona_id,
                    "provider_id": None,
                    "model_id": None,
                    "error_category": "policy_denied",
                    "receipt_id": None,
                    "persona_provider_mismatch": route.persona_provider_mismatch,
                },
            )
            yield ChatLifecycleEvent(
                event_type="route_failed",
                request_id=request_id,
                conversation_id=conversation.conversation_id,
                route_id=route.route_id,
                sequence=3,
                payload={
                    "error": {
                        "category": "policy_denied",
                        "message": "No eligible route satisfies the current provider and policy constraints.",
                    },
                    "reasons": route.reasons,
                    "message": denied_message.model_dump(mode="json"),
                    "lifecycle": lifecycle.snapshot(),
                },
            )
            with self._cancellation_lock:
                self._request_tokens.pop(request_id, None)
            return

        lifecycle.enter("starting_provider")
        route = plan.record.model_copy(
            update={
                "metadata": {
                    **plan.record.metadata,
                    **request.metadata,
                    "lifecycle": lifecycle.snapshot(),
                },
                "outcome_status": outcome_status_for_phase(lifecycle.phase),
            }
        )
        self.store.save_route(route)
        for candidate in plan.candidates:
            self.store.save_route_candidate(candidate)
        self.store.update_message(user_message.message_id, route_id=route.route_id)

        eligible_candidates = [candidate for candidate in plan.candidates if candidate.eligible]
        try:
            yield from self._execute_route(
                request=request,
                routing_request=routing_request,
                route=route,
                candidates=eligible_candidates,
                persona_version=persona_version,
                cognitive_policy=cognitive_policy,
                conversation=conversation,
                user_message=user_message,
                snapshots=snapshots,
                lifecycle=lifecycle,
                cancellation=cancellation,
                stream_sequence=2,
            )
        except Exception as exc:
            current_route = self.store.get_route(route.route_id) or route
            if current_route.outcome_status in {
                "complete",
                "failed",
                "cancelled",
                "blocked",
                "policy_denied",
            }:
                raise
            lifecycle.enter("failed")
            error = ProviderError(
                category="provider_error",
                message=_safe_diagnostic(str(exc)) or "request failed before completion",
            )
            current_route = self._finish_route(
                current_route,
                status="failed",
                receipt_id=None,
                usage=ProviderUsage(),
                actual_provider_id=current_route.selected_provider,
                actual_model_id=current_route.selected_model,
            )
            failed_message = self._persist_terminal_assistant_message(
                route=current_route,
                execution=ChatExecution(
                    request_id=request_id,
                    route_id=current_route.route_id,
                    conversation_id=conversation.conversation_id,
                    provider_id=current_route.selected_provider,
                    model_id=current_route.selected_model,
                    status="failed",
                ),
                user_message=user_message,
                status="failed",
                content=f"OpenCobalt could not complete this request: {error.message}",
                error=error,
            )
            yield ChatLifecycleEvent(
                event_type="error",
                request_id=request_id,
                conversation_id=conversation.conversation_id,
                route_id=current_route.route_id,
                sequence=3,
                payload={
                    "error": error.model_dump(mode="json"),
                    "message": failed_message.model_dump(mode="json"),
                    "lifecycle": lifecycle.snapshot(),
                },
            )
        finally:
            with self._cancellation_lock:
                self._request_tokens.pop(request_id, None)

    def has_live_pending_approval(self, execution_id: str) -> bool:
        coordinator = self.approval_coordinator
        return bool(coordinator is not None and coordinator.has_live_pending(execution_id))

    def cancel(self, execution_id: str) -> bool:
        """Request cooperative cancellation and persist the request state."""
        with self._cancellation_lock:
            cancellation = self._cancellations.pop(execution_id, None)
            if cancellation is None:
                cancellation = self._request_tokens.pop(execution_id, None)
        if cancellation is None:
            return False
        cancellation.cancel()
        if self.approval_coordinator is not None:
            self.approval_coordinator.cancel_execution(execution_id)
        execution = self.store.get_execution(execution_id)
        if execution is not None and execution.status in {"queued", "running"}:
            now = _now()
            self.store.save_execution(
                execution.model_copy(
                    update={"status": "cancel_requested", "updated_at": now}
                )
            )
        return True

    def cancel_all(self) -> int:
        """Cancel every in-flight request token. Used on API shutdown."""
        with self._cancellation_lock:
            tokens = list(self._cancellations.items()) + [
                (key, token) for key, token in self._request_tokens.items()
            ]
        cancelled = 0
        seen: set[int] = set()
        for key, token in tokens:
            if id(token) in seen:
                continue
            seen.add(id(token))
            token.cancel()
            cancelled += 1
            execution = self.store.get_execution(key)
            if execution is not None and execution.status in {"queued", "running"}:
                now = _now()
                self.store.save_execution(
                    execution.model_copy(
                        update={"status": "cancel_requested", "updated_at": now}
                    )
                )
        return cancelled

    def abandon(self, execution_id: str) -> bool:
        """Finalize a disconnected stream without waiting for cooperative resumption.

        ``cancel`` is the user-facing cooperative path: the live generator resumes,
        observes its token, and writes its own terminal event. A disconnected HTTP
        stream cannot resume reliably, so abandonment owns the durable transition
        immediately and is deliberately idempotent.
        """
        if self.has_live_pending_approval(execution_id):
            return False
        with self._cancellation_lock:
            cancellation = self._cancellations.pop(execution_id, None)
            request_token = self._request_tokens.pop(execution_id, None)
        if cancellation is not None:
            cancellation.cancel()
        elif request_token is not None:
            request_token.cancel()

        execution = self.store.get_execution(execution_id)
        if execution is None:
            executions = self.store.list_executions(request_id=execution_id, limit=1)
            execution = executions[0] if executions else None
        if execution is None:
            return self._abandon_unstarted_request(execution_id)
        if execution.status in {"complete", "failed", "cancelled"}:
            return False

        cancellation_reason = (
            "user_requested" if execution.status == "cancel_requested" else "client_disconnect"
        )

        events = self.store.list_stream_events(execution.execution_id)
        receipt_id = execution.work_receipt_id
        try:
            usage = ProviderUsage.model_validate(execution.usage or {})
        except ValueError:
            usage = ProviderUsage()
        for event in reversed(events):
            event_receipt = event.payload.get("receipt_id")
            if receipt_id is None and isinstance(event_receipt, str) and event_receipt:
                receipt_id = event_receipt
            event_usage = event.payload.get("usage")
            if event_usage and usage == ProviderUsage():
                try:
                    usage = ProviderUsage.model_validate(event_usage)
                except ValueError:
                    usage = ProviderUsage()
            if receipt_id is not None and usage != ProviderUsage():
                break

        error = ProviderError(
            category="cancelled",
            message=(
                "user cancelled the request before the response completed"
                if cancellation_reason == "user_requested"
                else "client disconnected before the response completed"
            ),
        )
        route = self.store.get_route(execution.route_id)
        execution = self._finish_execution(
            execution,
            status="cancelled",
            receipt_id=receipt_id,
            usage=usage,
            error=error,
        )
        if route is not None:
            route = self._finish_route(
                route,
                status="cancelled",
                receipt_id=receipt_id,
                usage=usage,
                actual_provider_id=execution.provider_id,
                actual_model_id=execution.model_id,
            )
            source = self.store.get_message(route.request_message_id)
            if source is not None and execution.assistant_message_id is None:
                assistant = self._persist_terminal_assistant_message(
                    route=route,
                    execution=execution,
                    user_message=source,
                    status="cancelled",
                    content=(
                        "The request was cancelled before a response completed."
                        if cancellation_reason == "user_requested"
                        else "The request ended because the client disconnected before a response completed."
                    ),
                    error=error,
                )
                execution = self._finish_execution(
                    execution,
                    status="cancelled",
                    receipt_id=receipt_id,
                    usage=usage,
                    error=error,
                    assistant_message_id=assistant.message_id,
                )

        self.store.append_stream_event(
            StreamEvent(
                execution_id=execution.execution_id,
                sequence=self._next_stream_sequence(execution.execution_id),
                event_type="cancelled",
                payload={
                    "error": error.model_dump(mode="json"),
                    "reason": cancellation_reason,
                    "receipt_id": receipt_id,
                },
            )
        )
        return True

    def _abandon_unstarted_request(self, request_id: str) -> bool:
        """Cancel a request that disconnected before a provider execution existed."""
        route = self.store.get_route_by_request_id(request_id)
        if route is None:
            return False
        if route.outcome_status in {
            "complete",
            "failed",
            "cancelled",
            "blocked",
            "policy_denied",
        }:
            return False
        error = ProviderError(
            category="cancelled",
            message="client disconnected before the response completed",
        )
        route = self._finish_route(
            route,
            status="cancelled",
            receipt_id=None,
            usage=ProviderUsage(),
        )
        source = self.store.get_message(route.request_message_id)
        if source is not None:
            self._persist_terminal_assistant_message(
                route=route,
                execution=ChatExecution(
                    request_id=request_id,
                    route_id=route.route_id,
                    conversation_id=route.conversation_id,
                    provider_id=route.selected_provider,
                    model_id=route.selected_model,
                    status="cancelled",
                ),
                user_message=source,
                status="cancelled",
                content=(
                    "The request ended because the client disconnected before a "
                    "response completed."
                ),
                error=error,
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
                local_only=(
                    bool(route.metadata.get("local_only", False))
                    if local_only is None
                    else local_only
                ),
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
        snapshots: Sequence[Any] | None = None,
        lifecycle: RequestLifecycle | None = None,
        cancellation: CancellationToken | None = None,
        stream_sequence: int = 0,
    ) -> Iterator[ChatLifecycleEvent]:
        request_lifecycle = lifecycle or RequestLifecycle(routing_request.request_id)

        def emit(
            event_type: str,
            *,
            execution: ChatExecution | None,
            payload: dict[str, Any] | None = None,
        ) -> ChatLifecycleEvent:
            nonlocal stream_sequence
            stream_sequence += 1
            body = dict(payload or {})
            body.setdefault("lifecycle", request_lifecycle.snapshot())
            body.setdefault(
                "phase_label",
                phase_label(
                    request_lifecycle.phase,
                    provider_id=execution.provider_id if execution else route.selected_provider,
                    model_id=execution.model_id if execution else route.selected_model,
                ),
            )
            return ChatLifecycleEvent(
                event_type=event_type,
                request_id=routing_request.request_id,
                conversation_id=conversation.conversation_id,
                route_id=route.route_id,
                execution_id=execution.execution_id if execution else None,
                sequence=stream_sequence,
                payload=body,
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

        if route.task_class == "research":
            yield from self._execute_research_route(
                request=request,
                routing_request=routing_request,
                route=route,
                candidate=ordered[0],
                persona_version=persona_version,
                cognitive_policy=cognitive_policy,
                conversation=conversation,
                user_message=user_message,
                snapshots=snapshots or [],
                lifecycle=emit,
            )
            return

        if route.metadata.get("capability_role") == "coding_agent" and conversation.project_path:
            from opencobalt.core.mission_engine import MissionStore
            from opencobalt.personal_ai.coding import CodingMissionStore

            missions = self.missions or MissionStore(self.store.db_path)
            coding_store = CodingMissionStore(self.store, missions)
            existing = self.store.get_coding_mission_for_route(route.route_id)
            coding = existing or coding_store.create(
                objective=request.message,
                repository_path=conversation.project_path,
                conversation_id=conversation.conversation_id,
                route_id=route.route_id,
                capability_role="coding_agent",
                provider_id=route.selected_provider,
                acp_session_id=conversation.metadata.get("acp_session_id"),
            )
            route = route.model_copy(
                update={
                    "metadata": {
                        **route.metadata,
                        "coding_mission_id": coding["coding_id"],
                        "coding_mission": coding["mission_id"],
                    },
                    "updated_at": _now(),
                }
            )
            self.store.save_route(route)

        current: ChatExecution | None = None
        final_content = ""
        final_usage = ProviderUsage()
        final_receipt_id: str | None = None
        final_error: ProviderError | None = None
        attempt_index = 0
        captured_session_id: str | None = None
        captured_files: list[str] = []
        captured_terminals: list[str] = []
        captured_tests: list[str] = []
        captured_approvals: list[dict[str, Any]] = []
        captured_limitations: list[str] = []
        captured_changeset: dict[str, Any] | None = None

        while attempt_index < len(ordered):
            candidate = ordered[attempt_index]
            provider = self.providers.get(candidate.provider_id)
            actual_persona_id, mismatch = resolve_persona_for_provider(
                routing_request.requested_persona_id,
                persona_version,
                provider.status().routing_profile.provider_family,
            )
            route = route.model_copy(
                update={
                    "actual_persona_id": actual_persona_id,
                    "actual_persona_version_id": (
                        persona_version.persona_version_id
                        if actual_persona_id == routing_request.requested_persona_id
                        else None
                    ),
                    "persona_provider_mismatch": mismatch,
                    "updated_at": _now(),
                }
            )
            self.store.save_route(route)
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
            attempt_cancel = cancellation or CancellationToken()
            with self._cancellation_lock:
                self._cancellations[current.execution_id] = attempt_cancel

            if attempt_index == 0:
                selected = emit(
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
                event = emit(
                    "fallback_started",
                    execution=current,
                    payload=fallback,
                )
                self._persist_lifecycle_event(current, event)
                yield event

            if request_lifecycle.phase != "starting_provider":
                request_lifecycle.enter("starting_provider")
                route = self._touch_route_phase(route, request_lifecycle)
            started = emit(
                "execution_started",
                execution=current,
                payload={
                    "provider_id": candidate.provider_id,
                    "model_id": candidate.model_id,
                    "attempt": attempt_index + 1,
                    "phase_label": phase_label(
                        "starting_provider",
                        provider_id=candidate.provider_id,
                        model_id=candidate.model_id,
                    ),
                },
            )
            self._persist_lifecycle_event(current, started)
            yield started

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
                    "execution_id": current.execution_id,
                    "conversation_id": conversation.conversation_id,
                    "persona_version_id": persona_version.persona_version_id,
                    "reasoning_effort": request.reasoning_effort,
                    "cognitive_policy": cognitive_policy,
                    "capability_role": route.metadata.get("capability_role"),
                    "chat_surface": (
                        "coding_mission"
                        if route.metadata.get("coding_mission_id")
                        else "general_chat"
                    ),
                    "acp_session_id": conversation.metadata.get("acp_session_id"),
                    "mission_id": route.metadata.get("coding_mission")
                    or route.metadata.get("coding_mission_id"),
                    "coding_mission_id": route.metadata.get("coding_mission_id"),
                    "admitted_model_ids": [
                        item.model_id
                        for item in (snapshots or [])
                        if getattr(item, "provider_id", None) == candidate.provider_id
                        and getattr(item, "model_id", None)
                    ],
                },
            )
            attempt_content = ""
            attempt_usage = ProviderUsage()
            attempt_receipt: str | None = None
            attempt_error: ProviderError | None = None
            terminal_type: str | None = None
            try:
                provider_events = provider.stream(provider_request, attempt_cancel)
                for provider_event in provider_events:
                    attempt_receipt = provider_event.receipt_id or attempt_receipt
                    if provider_event.event_type == "started":
                        normalized_type = "provider_started"
                        if request_lifecycle.phase != "running":
                            request_lifecycle.enter("running")
                            route = self._touch_route_phase(route, request_lifecycle)
                        payload = {
                            "provider_id": provider_event.provider_id,
                            "receipt_id": provider_event.receipt_id,
                            "phase_label": phase_label(
                                "running",
                                provider_id=candidate.provider_id,
                                model_id=candidate.model_id,
                            ),
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
                        tool_payload = (
                            provider_event.tool_event.model_dump(mode="json")
                            if provider_event.tool_event
                            else {"status": "unknown"}
                        )
                        payload = {"tool_event": tool_payload}
                        tool_name = str(tool_payload.get("tool_name") or "").casefold()
                        summary = str(tool_payload.get("summary") or tool_payload.get("tool_name") or "")[:200]
                        if summary and any(token in tool_name for token in ("edit", "write", "apply")):
                            captured_files.append(summary)
                        elif summary and any(token in tool_name for token in ("terminal", "bash", "shell")):
                            captured_terminals.append(summary)
                            if "test" in tool_name or "pytest" in summary.casefold():
                                captured_tests.append(summary)
                    elif provider_event.event_type in {"approval_required", "approval_decided"}:
                        normalized_type = provider_event.event_type
                        payload = {
                            "approval": provider_event.metadata.get("approval") or {}
                        }
                        approval = payload["approval"]
                        if isinstance(approval, dict) and approval:
                            captured_approvals = [
                                *[
                                    item
                                    for item in captured_approvals
                                    if item.get("request_id") != approval.get("request_id")
                                ],
                                approval,
                            ]
                            route = route.model_copy(
                                update={
                                    "metadata": {
                                        **route.metadata,
                                        "acp_permissions": captured_approvals,
                                    },
                                    "updated_at": _now(),
                                }
                            )
                            self.store.save_route(route)
                            coding_id = route.metadata.get("coding_mission_id")
                            if coding_id:
                                record = self.store.get_coding_mission(str(coding_id))
                                if record is not None:
                                    record["approvals"] = captured_approvals
                                    record["updated_at"] = _now().isoformat()
                                    self.store.save_coding_mission(record)
                    elif provider_event.event_type == "completed":
                        terminal_type = "completed"
                        normalized_type = "provider_completed"
                        payload = {"receipt_id": provider_event.receipt_id}
                        if provider_event.session_id:
                            captured_session_id = provider_event.session_id
                        permissions = provider_event.metadata.get("acp_permissions")
                        if isinstance(permissions, list):
                            captured_approvals = [
                                item for item in permissions if isinstance(item, dict)
                            ]
                            if captured_approvals:
                                route = route.model_copy(
                                    update={
                                        "metadata": {
                                            **route.metadata,
                                            "acp_permissions": captured_approvals,
                                        },
                                        "updated_at": _now(),
                                    }
                                )
                                self.store.save_route(route)
                        files_changed = provider_event.metadata.get("files_changed")
                        if isinstance(files_changed, list):
                            captured_files.extend(
                                str(item)[:200] for item in files_changed if item
                            )
                        changeset = provider_event.metadata.get("changeset")
                        if isinstance(changeset, dict) and changeset.get("changeset_id"):
                            captured_changeset = changeset
                        limitations = provider_event.metadata.get("limitations")
                        if isinstance(limitations, list):
                            captured_limitations.extend(
                                str(item)[:400] for item in limitations if item
                            )
                    else:
                        terminal_type = provider_event.event_type
                        raw_error = provider_event.error or ProviderError(
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
                        attempt_error = raw_error.model_copy(
                            update={"message": _safe_diagnostic(raw_error.message)}
                        )
                        normalized_type = f"provider_{provider_event.event_type}"
                        payload = {
                            "error": attempt_error.model_dump(mode="json"),
                            "receipt_id": provider_event.receipt_id,
                        }
                    if provider_event.event_type in {"completed", "error", "cancelled"}:
                        self._persist_provider_terminal_event(
                            current,
                            event_type=normalized_type,
                            payload=payload,
                        )
                    else:
                        event = emit(normalized_type, execution=current, payload=payload)
                        self._persist_lifecycle_event(current, event)
                        yield event
            except Exception as exc:  # provider boundary must become inspectable
                terminal_type = "error"
                attempt_error = ProviderError(
                    category="provider_error",
                    message=_safe_diagnostic(str(exc)) or "provider execution failed",
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
                    actual_provider_id=current.provider_id,
                    actual_model_id=current.model_id,
                )
                terminal_message = self._persist_terminal_assistant_message(
                    route=route,
                    execution=current,
                    user_message=user_message,
                    status="cancelled",
                    content="The request was cancelled before a response completed.",
                    error=final_error,
                )
                current = self._finish_execution(
                    current,
                    status="cancelled",
                    receipt_id=attempt_receipt,
                    usage=attempt_usage,
                    error=final_error,
                    assistant_message_id=terminal_message.message_id,
                )
                cancelled = emit(
                    "cancelled",
                    execution=current,
                    payload={"error": final_error.model_dump(mode="json")},
                )
                self._persist_lifecycle_event(current, cancelled)
                self._finalize_coding_mission(
                    route,
                    status="cancelled",
                    outcome="Execution cancelled.",
                    receipt_id=attempt_receipt,
                    acp_session_id=captured_session_id,
                    model_id=current.model_id,
                    files_changed=captured_files,
                    terminal_operations=captured_terminals,
                    tests=captured_tests,
                    approvals=captured_approvals,
                    limitations=captured_limitations,
                    changeset=captured_changeset,
                )
                yield cancelled
                return

            next_candidate = next(
                (
                    candidate
                    for candidate in ordered[attempt_index + 1 :]
                    if candidate.provider_id != current.provider_id
                ),
                None,
            )
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
                    actual_provider_id=current.provider_id,
                    actual_model_id=current.model_id,
                )
                terminal_message = self._persist_terminal_assistant_message(
                    route=route,
                    execution=current,
                    user_message=user_message,
                    status="failed",
                    content=(
                        f"Provider {current.provider_id} did not complete the request: "
                        f"{final_error.message}"
                    ),
                    error=final_error,
                )
                current = self._finish_execution(
                    current,
                    status="failed",
                    receipt_id=attempt_receipt,
                    usage=attempt_usage,
                    error=final_error,
                    assistant_message_id=terminal_message.message_id,
                )
                error_event = emit(
                    "error",
                    execution=current,
                    payload={
                        "error": final_error.model_dump(mode="json"),
                        "fallback_allowed": request.allow_fallback,
                        "fallback_used": False,
                    },
                )
                self._persist_lifecycle_event(current, error_event)
                self._finalize_coding_mission(
                    route,
                    status="failed",
                    outcome=final_error.message,
                    receipt_id=attempt_receipt,
                    acp_session_id=captured_session_id,
                    model_id=current.model_id,
                    files_changed=captured_files,
                    terminal_operations=captured_terminals,
                    tests=captured_tests,
                    approvals=captured_approvals,
                    limitations=captured_limitations,
                    changeset=captured_changeset,
                )
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
            attempt_index = ordered.index(next_candidate)

        if current is None or not final_content.strip():
            raise RuntimeError("route execution ended without a terminal result")

        request_lifecycle.enter("verifying")
        verification = self._verification_record(
            route.verification_strategy,
            content=final_content,
            receipt_id=final_receipt_id,
        )
        request_lifecycle.enter("persisting")
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
                **(
                    {"changeset": captured_changeset}
                    if captured_changeset
                    else {}
                ),
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
            verification=verification,
        )
        if captured_session_id:
            conversation.metadata = self.store.merge_conversation_metadata(
                conversation.conversation_id,
                {"acp_session_id": captured_session_id},
            )
        coding_id = route.metadata.get("coding_mission_id")
        if coding_id:
            self._finalize_coding_mission(
                route,
                status="complete",
                outcome=final_content[:4000],
                receipt_id=final_receipt_id,
                acp_session_id=captured_session_id,
                model_id=current.model_id,
                files_changed=captured_files,
                terminal_operations=captured_terminals,
                tests=captured_tests,
                approvals=captured_approvals,
                limitations=captured_limitations,
                changeset=captured_changeset,
            )
        if final_receipt_id and captured_approvals and self.engine is not None:
            getter = getattr(getattr(self.engine, "store", None), "get_receipt", None)
            saver = getattr(getattr(self.engine, "store", None), "save_receipt", None)
            if callable(getter) and callable(saver):
                receipt = getter(final_receipt_id)
                if receipt is not None:
                    extra = [
                        f"approval:{item.get('request_id') or item.get('approval_request_id')}"
                        for item in captured_approvals
                        if isinstance(item, dict)
                        and (item.get("request_id") or item.get("approval_request_id"))
                    ]
                    receipt.provenance_refs = list(
                        dict.fromkeys([*list(receipt.provenance_refs or []), *extra])
                    )
                    saver(receipt)
        memory = self._propose_explicit_memory(request, user_message)
        request_lifecycle.enter("complete")
        route = self._touch_route_phase(route, request_lifecycle)
        completed = emit(
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

    def _finalize_coding_mission(
        self,
        route: RouteRecord,
        *,
        status: str,
        outcome: str,
        receipt_id: str | None,
        acp_session_id: str | None,
        model_id: str | None,
        files_changed: list[str],
        terminal_operations: list[str],
        tests: list[str],
        approvals: list[dict[str, Any]],
        limitations: list[str],
        changeset: dict[str, Any] | None = None,
    ) -> None:
        coding_id = route.metadata.get("coding_mission_id")
        if not coding_id:
            return
        from opencobalt.core.mission_engine import MissionStore
        from opencobalt.personal_ai.coding import CodingMissionStore

        record = self.store.get_coding_mission(str(coding_id))
        if record is None:
            return
        mission_status = status
        mission_outcome = outcome
        extra_limitations = list(limitations)
        extra_tests = list(tests)
        changed = list(files_changed)
        if changeset:
            record["metadata"] = {
                **(record.get("metadata") or {}),
                "changeset_id": changeset.get("changeset_id"),
                "workspace_id": changeset.get("workspace_id"),
                "promotion_state": changeset.get("promotion_state"),
                "starting_head": changeset.get("starting_head"),
                "verification": changeset.get("verification") or {},
            }
            extra_limitations.extend(str(item) for item in changeset.get("limitations") or [])
            extra_tests.extend(str(item) for item in changeset.get("tests") or [])
            if not changed:
                for item in changeset.get("files") or []:
                    if isinstance(item, dict) and item.get("path"):
                        changed.append(str(item["path"]))
            promotion_state = str(changeset.get("promotion_state") or "")
            verification_status = str((changeset.get("verification") or {}).get("status") or "")
            if status == "complete":
                if promotion_state == "pending":
                    mission_status = "awaiting_promotion"
                    mission_outcome = "Changes ready. Authoritative repository was not modified."
                elif promotion_state == "blocked":
                    mission_status = "blocked"
                    mission_outcome = "Staged changes were blocked by path policy."
                elif promotion_state == "empty":
                    mission_status = "complete"
                elif verification_status == "failed":
                    mission_status = "awaiting_promotion"
                    extra_limitations.append("Verification failed")
        CodingMissionStore(
            self.store, self.missions or MissionStore(self.store.db_path)
        ).complete(
            record,
            status=mission_status,
            outcome=mission_outcome[:4000],
            receipt_id=receipt_id,
            acp_session_id=acp_session_id,
            model_id=model_id,
            files_changed=changed,
            terminal_operations=terminal_operations,
            tests=list(dict.fromkeys(extra_tests)),
            approvals=approvals,
            limitations=list(dict.fromkeys(extra_limitations)),
        )
        if receipt_id and changeset and self.engine is not None:
            getter = getattr(getattr(self.engine, "store", None), "get_receipt", None)
            saver = getattr(getattr(self.engine, "store", None), "save_receipt", None)
            if callable(getter) and callable(saver):
                receipt = getter(receipt_id)
                if receipt is not None:
                    extra = [
                        f"changeset:{changeset.get('changeset_id')}",
                        f"workspace:{changeset.get('workspace_id')}" if changeset.get("workspace_id") else "",
                        f"head:{changeset.get('starting_head')}" if changeset.get("starting_head") else "",
                    ]
                    if changeset.get("promotion_request_id"):
                        extra.append(f"promotion:{changeset.get('promotion_request_id')}")
                    receipt.provenance_refs = list(
                        dict.fromkeys(
                            [
                                *list(receipt.provenance_refs or []),
                                *[item for item in extra if item],
                            ]
                        )
                    )
                    limitations = list(receipt.limitations or [])
                    for item in extra_limitations:
                        if item and item not in limitations:
                            limitations.append(item)
                    receipt.limitations = limitations
                    saver(receipt)

    def apply_coding_promotion(
        self,
        changeset_id: str,
        *,
        reason: str = "",
        coding_id: str | None = None,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        from opencobalt.personal_ai.staging import StagingController

        bridge = getattr(self.approval_coordinator, "bridge", None)
        controller = StagingController(
            self.store,
            staging_root=Path(self.store.db_path).parent / "staging",
            approval_store=getattr(bridge, "store", None),
        )
        changeset = controller.apply_changeset(
            changeset_id, reason=reason, coding_id=coding_id, mission_id=mission_id
        )
        self._record_promotion_outcome(
            changeset,
            status="promoted",
            outcome="Staged changes were applied to the authoritative repository.",
        )
        return changeset.public_view(include_diff=False)

    def reject_coding_promotion(
        self,
        changeset_id: str,
        *,
        reason: str = "",
        coding_id: str | None = None,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        from opencobalt.personal_ai.staging import StagingController

        bridge = getattr(self.approval_coordinator, "bridge", None)
        controller = StagingController(
            self.store,
            staging_root=Path(self.store.db_path).parent / "staging",
            approval_store=getattr(bridge, "store", None),
        )
        changeset = controller.reject_changeset(
            changeset_id, reason=reason, coding_id=coding_id, mission_id=mission_id
        )
        self._record_promotion_outcome(
            changeset,
            status="rejected",
            outcome="Staged changes were rejected. The authoritative repository was not modified.",
        )
        return changeset.public_view(include_diff=False)

    def _record_promotion_outcome(
        self,
        changeset,
        *,
        status: str,
        outcome: str,
    ) -> None:
        if not changeset.coding_id:
            return
        from opencobalt.core.mission_engine import MissionStore
        from opencobalt.personal_ai.coding import CodingMissionStore

        record = self.store.get_coding_mission(changeset.coding_id)
        if record is None:
            return
        record["metadata"] = {
            **(record.get("metadata") or {}),
            "changeset_id": changeset.changeset_id,
            "promotion_state": changeset.promotion_state,
            "apply_state": changeset.apply_state,
        }
        CodingMissionStore(
            self.store, self.missions or MissionStore(self.store.db_path)
        ).complete(
            record,
            status=status,
            outcome=outcome,
            receipt_id=record.get("receipt_id"),
            acp_session_id=record.get("acp_session_id"),
            model_id=record.get("model_id"),
            files_changed=record.get("files_changed") or [item.path for item in changeset.files],
            terminal_operations=record.get("terminal_operations") or [],
            tests=record.get("tests") or list(changeset.tests),
            approvals=record.get("approvals") or [],
            limitations=record.get("limitations") or list(changeset.limitations),
        )

    def _persist_terminal_assistant_message(
        self,
        *,
        route: RouteRecord,
        execution: ChatExecution,
        user_message: ChatMessage,
        status: Literal["failed", "cancelled"],
        content: str,
        error: ProviderError,
    ) -> ChatMessage:
        """Keep terminal provider failures visible after refresh and restart."""
        return self.store.add_message(
            route.conversation_id,
            role="assistant",
            content=_safe_diagnostic(content),
            status=status,
            persona_version_id=route.actual_persona_version_id,
            route_id=route.route_id,
            parent_message_id=user_message.message_id,
            metadata={
                "requested_persona_id": route.requested_persona_id,
                "actual_persona_id": route.actual_persona_id,
                "provider_id": execution.provider_id,
                "model_id": execution.model_id,
                "error_category": error.category,
                "receipt_id": execution.work_receipt_id,
                "persona_provider_mismatch": route.persona_provider_mismatch,
            },
        )

    def _execute_research_route(
        self,
        *,
        request: ChatRequest,
        routing_request: RoutingRequest,
        route: RouteRecord,
        candidate: RouteCandidate,
        persona_version: PersonaVersion,
        cognitive_policy: str,
        conversation: Conversation,
        user_message: ChatMessage,
        snapshots: Sequence[Any],
        lifecycle,
    ) -> Iterator[ChatLifecycleEvent]:
        from opencobalt.core.mission_engine import MissionStore
        from opencobalt.personal_ai.research import ResearchOrchestrator

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
            payload={"route": route.model_dump(mode="json"), "research": True},
        )
        self._persist_lifecycle_event(current, selected)
        yield selected

        engine = self.engine or getattr(self.providers.get(candidate.provider_id), "engine", None)
        missions = self.missions or MissionStore(self.store.db_path)
        if engine is None:
            error = ProviderError(
                category="configuration",
                message="Research execution requires ExecutionEngine",
            )
            yield lifecycle("error", execution=current, payload={"error": error.model_dump(mode="json")})
            return

        orchestrator = ResearchOrchestrator(
            store=self.store,
            providers=self.providers,
            missions=missions,
            engine=engine,
        )
        rendered_policy = render_persona_policy(persona_version, cognitive_policy)
        final_payload: dict[str, Any] = {}
        try:
            for step in orchestrator.run(
                question=request.message,
                conversation_id=conversation.conversation_id,
                route_id=route.route_id,
                snapshots=snapshots,
                local_only=bool(route.metadata.get("local_only", False)),
                timeout_seconds=max(request.timeout_seconds, 180),
                cancellation=cancellation,
                system_policy=rendered_policy,
                attachment_ids=request.attachment_ids,
            ):
                event = lifecycle(
                    f"research_{step.get('step', 'update')}",
                    execution=current,
                    payload=step,
                )
                self._persist_lifecycle_event(current, event)
                yield event
                final_payload = step
        except Exception as exc:
            error = ProviderError(
                category="provider_error",
                message=_safe_diagnostic(str(exc)) or "research workflow failed",
            )
            current = self._finish_execution(
                current, status="failed", receipt_id=None, usage=ProviderUsage(), error=error
            )
            route = self._finish_route(
                route,
                status="failed",
                receipt_id=None,
                usage=ProviderUsage(),
                actual_provider_id=current.provider_id,
                actual_model_id=current.model_id,
            )
            self._persist_terminal_assistant_message(
                route=route,
                execution=current,
                user_message=user_message,
                status="failed",
                content=f"Research workflow failed: {error.message}",
                error=error,
            )
            yield lifecycle("error", execution=current, payload={"error": error.model_dump(mode="json")})
            return

        synthesis = str(final_payload.get("synthesis") or "").strip()
        status = "complete" if synthesis and final_payload.get("step") == "complete" else "failed"
        if final_payload.get("step") == "blocked":
            status = "failed"
        error = None
        if status != "complete":
            error = ProviderError(
                category="policy_denied" if final_payload.get("step") == "blocked" else "provider_error",
                message=str(final_payload.get("error") or "research workflow did not complete"),
            )
            synthesis = synthesis or (
                "OpenCobalt did not complete this Research mission. "
                + (error.message)
            )
        receipt_id = final_payload.get("receipt_id")
        if isinstance(receipt_id, str) and receipt_id:
            pass
        else:
            receipt_id = None
        current = self._finish_execution(
            current,
            status="complete" if status == "complete" else "failed",
            receipt_id=receipt_id,
            usage=ProviderUsage(),
            error=error,
        )
        route = self._finish_route(
            route,
            status="complete" if status == "complete" else (
                "policy_denied" if error and error.category == "policy_denied" else "failed"
            ),
            receipt_id=receipt_id,
            usage=ProviderUsage(),
            actual_provider_id=current.provider_id,
            actual_model_id=current.model_id,
        )
        route = route.model_copy(
            update={
                "metadata": {
                    **route.metadata,
                    "research_id": final_payload.get("research_id"),
                    "mission_id": final_payload.get("mission_id"),
                    "research_source_count": final_payload.get("source_count"),
                    "research_evidence_count": final_payload.get("evidence_count"),
                }
            }
        )
        self.store.save_route(route)
        assistant_metadata = {
            "requested_persona_id": route.requested_persona_id,
            "actual_persona_id": route.actual_persona_id,
            "provider_id": current.provider_id,
            "model_id": current.model_id,
            "persona_provider_mismatch": route.persona_provider_mismatch,
            "research_id": final_payload.get("research_id"),
            "mission_id": final_payload.get("mission_id"),
            "receipt_id": receipt_id,
        }
        if error is not None:
            assistant_metadata["error_category"] = error.category
        assistant = self.store.add_message(
            route.conversation_id,
            role="assistant",
            content=synthesis if status == "complete" else _safe_diagnostic(synthesis),
            status="complete" if status == "complete" else "failed",
            persona_version_id=route.actual_persona_version_id,
            route_id=route.route_id,
            parent_message_id=user_message.message_id,
            metadata=assistant_metadata,
        )
        current = self._finish_execution(
            current,
            status=current.status,
            receipt_id=receipt_id,
            usage=ProviderUsage(),
            error=error,
            assistant_message_id=assistant.message_id,
        )
        terminal = lifecycle(
            "completed" if status == "complete" else "error",
            execution=current,
            payload={
                "research_id": final_payload.get("research_id"),
                "mission_id": final_payload.get("mission_id"),
                "receipt_id": receipt_id,
                **({"error": error.model_dump(mode="json")} if error else {}),
            },
        )
        self._persist_lifecycle_event(current, terminal)
        yield terminal
        with self._cancellation_lock:
            self._cancellations.pop(current.execution_id, None)

    def _provider_snapshots(
        self,
        request: RoutingRequest,
        persona_version: PersonaVersion,
    ) -> list[ProviderSnapshot]:
        preferences = {
            preference.provider_id: preference
            for preference in self.store.list_provider_preferences()
        }
        settings_order = {
            provider_id: max(-10, 10 - index)
            for index, provider_id in enumerate(request.settings.provider_priority[:20])
        }
        historical_signals = self._historical_outcome_signals()
        effective_local_only = (
            request.settings.local_only_default
            if request.local_only is None
            else request.local_only
        )
        snapshots: list[ProviderSnapshot] = []
        statuses = self.providers.discover()

        def append_status(status: Any, *, mock_allowed: bool | None = None) -> None:
            profile = status.routing_profile
            preference = preferences.get(status.provider_id)
            chat_isolated = status.capabilities.answer_only_isolation
            coding_runtime = "coding_agent" in getattr(profile, "capability_roles", [])
            available = status.execution_supported and (chat_isolated or coding_runtime)
            unavailable_reason = None
            if not status.execution_supported:
                unavailable_reason = "provider has no discovered executable completion boundary"
            elif not chat_isolated and not coding_runtime:
                unavailable_reason = (
                    "provider lacks a proven answer-only isolation boundary and Chat "
                    "approval-and-resume is unavailable"
                )
            if status.provider_id == "mock":
                available = self.enable_mock and bool(mock_allowed)
                if not self.enable_mock:
                    unavailable_reason = "development Mock provider is disabled"
                elif not mock_allowed:
                    unavailable_reason = (
                        "development Mock is suppressed because an eligible real Chat route exists"
                    )
            if preference is not None:
                if not preference.enabled:
                    available = False
                    unavailable_reason = "provider is disabled in local preferences"
                if (
                    preference.cost_policy == "free_only"
                    and profile.cost_category != "free"
                ):
                    available = False
                    unavailable_reason = "provider preference permits free routes only"

            models: list[str | None] = [None]
            discovered: list[str] = []
            model_catalog_checked = False
            discovery_receipt_id: str | None = None
            discovery_source: str | None = None
            discovery_age_ms: int | None = None
            model_locations: dict[str, str] = {}
            model_evidence: dict[str, tuple[str, ...]] = {}
            model_records: dict[str, Any] = {}
            if available and status.capabilities.model_discovery:
                catalog = self.providers.get(status.provider_id).discover_models(
                    local_only=bool(effective_local_only)
                )
                discovery_receipt_id = catalog.receipt_id
                discovery_source = catalog.cache_source
                discovery_age_ms = catalog.age_ms
                if catalog.error is not None:
                    available = False
                    unavailable_reason = (
                        f"{status.display_name} model discovery failed: "
                        f"{_safe_diagnostic(catalog.error.message)}"
                    )
                else:
                    model_catalog_checked = True
                discovered = [model.model_id for model in catalog.models]
                model_records = {model.model_id: model for model in catalog.models}
                model_locations = {
                    model.model_id: model.execution_location for model in catalog.models
                }
                model_evidence = {
                    model.model_id: tuple(model.locality_evidence)
                    for model in catalog.models
                }
                if discovered:
                    models = discovered
                elif status.provider_id in {"ollama", "antigravity"} and catalog.error is None:
                    available = False
                    evidence = "; ".join(
                        _safe_diagnostic(item) for item in catalog.limitations[:3]
                    )
                    unavailable_reason = (
                        "Ollama model catalog: no models passed local-provenance "
                        "admission"
                        if status.provider_id == "ollama"
                        else f"{status.display_name} model catalog returned no usable models"
                    )
                    if evidence:
                        unavailable_reason = f"{unavailable_reason}: {evidence}"
            if request.model_override and status.provider_id == request.provider_override:
                models = [request.model_override]
                if model_catalog_checked and request.model_override not in discovered:
                    available = False
                    unavailable_reason = (
                        "requested model was not reported by local model discovery; "
                        "automatic retrieval is disabled"
                    )

            preference_score = 0
            if preference is not None:
                preference_score = max(-10, min(10, round((preference.priority - 50) / 5)))
            priority = max(preference_score, settings_order.get(status.provider_id, 0))
            for model_id in models:
                record = model_records.get(model_id) if model_id else None
                snapshots.append(
                    ProviderSnapshot(
                        provider_id=status.provider_id,
                        model_id=model_id,
                        runtime_id=status.runtime_id,
                        provider_family=profile.provider_family,
                        available=available,
                        local=status.capabilities.local_only_eligible,
                        requires_network=status.capabilities.requires_network,
                        cost_category=(
                            getattr(record, "cost_category", None) or profile.cost_category
                        ),
                        quality_tier=(
                            getattr(record, "quality_tier", None) or profile.quality_tier
                        ),
                        capabilities=frozenset(profile.task_capabilities),
                        capability_roles=frozenset(getattr(profile, "capability_roles", []) or []),
                        tool_names=frozenset(
                            list(profile.tool_names) + list(getattr(record, "tool_names", []) or [])
                        ),
                        latency_category=(
                            getattr(record, "latency_category", None) or profile.latency_category
                        ),
                        historical_success_signal=historical_signals.get(
                            status.provider_id, {}
                        ).get("success", 0),
                        observed_latency_signal=historical_signals.get(
                            status.provider_id, {}
                        ).get("latency", 0),
                        cancellation_rate_signal=historical_signals.get(
                            status.provider_id, {}
                        ).get("cancel", 0),
                        provider_priority=priority,
                        readiness_state=status.health,
                        authentication_state=status.authentication,
                        unavailable_reason=unavailable_reason,
                        discovery_receipt_id=discovery_receipt_id,
                        discovery_source=discovery_source,
                        discovery_age_ms=discovery_age_ms,
                        execution_location=model_locations.get(model_id or "", "unknown"),
                        model_locality_evidence=model_evidence.get(model_id or "", ()),
                        display_name=getattr(record, "display_name", None),
                        model_family=getattr(record, "family", None),
                        profile_evidence=getattr(record, "profile_evidence", None),
                        billing_classification=profile.billing_classification,
                    )
                )

        for status in statuses:
            if status.provider_id != "mock":
                append_status(status)

        try:
            self.router.route(request, snapshots, persona_version=persona_version)
            eligible_real_route = True
        except NoEligibleRouteError:
            eligible_real_route = False

        for status in statuses:
            if status.provider_id == "mock":
                append_status(
                    status,
                    mock_allowed=(
                        request.provider_override == "mock" or not eligible_real_route
                    ),
                )
        return snapshots

    def _historical_success_signals(self) -> dict[str, int]:
        return {
            provider_id: values.get("success", 0)
            for provider_id, values in self._historical_outcome_signals().items()
        }

    def _historical_outcome_signals(self) -> dict[str, dict[str, int]]:
        """Bounded routing signals from local executions. Not quality scores."""
        grouped: dict[str, list[ChatExecution]] = {}
        for execution in self.store.list_executions(limit=200):
            outcomes = grouped.setdefault(execution.provider_id, [])
            if len(outcomes) < 20 and execution.status in {
                "complete",
                "failed",
            }:
                outcomes.append(execution)
        signals: dict[str, dict[str, int]] = {}
        for provider_id, executions in grouped.items():
            statuses = [item.status for item in executions]
            successes = statuses.count("complete")
            failures = statuses.count("failed")
            durations = []
            for item in executions:
                if item.status != "complete":
                    continue
                if item.started_at is None or item.finished_at is None:
                    continue
                durations.append(
                    max(0, int((item.finished_at - item.started_at).total_seconds() * 1000))
                )
            latency_signal = 0
            if durations:
                median = sorted(durations)[len(durations) // 2]
                if median < 1500:
                    latency_signal = 2
                elif median > 20_000:
                    latency_signal = -2
            signals[provider_id] = {
                "success": max(-10, min(10, 2 * (successes - failures))),
                "latency": latency_signal,
                "cancel": 0,
            }
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
                "capability_role": classify_capability_role(
                    request.prompt,
                    task_class,
                    complexity,
                    classify_requirements(
                        request.prompt, task_class, complexity, request.cognitive_policy
                    ),
                    project_path=request.project_path,
                ),
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
        allowed = list(version.allowed_cognitive_policies)
        if requested is not None:
            if requested == "research" and (
                "research" in allowed or "research_synthesis" in allowed
            ):
                return "research"
            if requested not in allowed:
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
        task_class = route.task_class
        answer_only = route.autonomy_level == "answer_only" and task_class not in {
            "coding",
            "repository_execution",
            "tool_operation",
        }
        sections: list[str] = []
        if has_explicit_format_constraint(user_message.content):
            sections.extend(
                [
                    "User output constraint (highest priority):",
                    "Obey the user's requested length and format exactly.",
                    "Do not add headings, admonition blocks such as [!NOTE], preamble, or assistant pleasantries.",
                    "Do not open with an offer to help. The requested format outranks persona warmth, verbosity, and cognitive-policy style.",
                    "",
                ]
            )
        sections.extend(
            [
                "OpenCobalt interaction policy:",
                persona_policy,
                "",
                "Execution constraints:",
            ]
        )
        if answer_only:
            sections.append(
                "This is an answer-only request. Do not produce tests, diffs, implementation plans, or engineering-report scaffolding unless the user asked for those."
            )
        sections.extend(
            [
                "Answer the request only. Do not modify files, run tools, or take external actions unless the route explicitly selected those capabilities and the user explicitly requested the action.",
                f"Privacy classification: {route.privacy_classification}",
                f"Local-only: {bool(route.metadata.get('local_only', False))}",
            ]
        )
        if route.persona_provider_mismatch:
            sections.append(f"Persona/provider disclosure: {route.persona_provider_mismatch}")
        from opencobalt.personal_ai.builtin_skills import skill_policy_addendum

        skill_text = skill_policy_addendum(list(route.selected_skills))
        if skill_text:
            sections.extend(["", skill_text])
        if history:
            sections.extend(["", "Recent conversation context:", history])
        from opencobalt.personal_ai.documents import render_attachment_context

        attachment_ids = [
            str(item)
            for item in (user_message.metadata or {}).get("attachment_ids", [])
            if str(item).strip()
        ]
        if not attachment_ids:
            attachment_ids = [
                item["attachment_id"]
                for item in self.store.list_attachments(conversation.conversation_id)
            ]
        records = [
            record
            for record in (self.store.get_attachment(item) for item in attachment_ids)
            if record is not None
        ]
        document_context = render_attachment_context(records, user_message.content)
        if document_context:
            sections.extend(["", document_context])
        if has_explicit_format_constraint(user_message.content):
            sections.extend(
                [
                    "",
                    "Reminder: the user's length and format constraint still has priority over the policy text above.",
                ]
            )
        return "\n".join(sections)

    def _next_stream_sequence(self, execution_id: str) -> int:
        events = self.store.list_stream_events(execution_id)
        return max((event.sequence for event in events), default=0) + 1

    def _persist_lifecycle_event(
        self, execution: ChatExecution, event: ChatLifecycleEvent
    ) -> None:
        self.store.append_stream_event(
            StreamEvent(
                execution_id=execution.execution_id,
                sequence=self._next_stream_sequence(execution.execution_id),
                event_type=event.event_type,
                payload=event.payload,
            )
        )

    def _touch_route_phase(
        self, route: RouteRecord, lifecycle: RequestLifecycle
    ) -> RouteRecord:
        snapshot = lifecycle.snapshot()
        finished = route.model_copy(
            update={
                "outcome_status": snapshot["outcome_status"],
                "metadata": {**route.metadata, "lifecycle": snapshot},
                "updated_at": _now(),
            }
        )
        self.store.save_route(finished)
        return finished

    def _persist_provider_terminal_event(
        self,
        execution: ChatExecution,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Record provider termination without exposing a premature client terminal."""
        sequence = self._next_stream_sequence(execution.execution_id)
        self.store.append_stream_event(
            StreamEvent(
                execution_id=execution.execution_id,
                sequence=sequence,
                event_type=event_type,
                payload=payload,
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
                "limitations": [
                    "response integrity does not verify factual correctness"
                ],
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
