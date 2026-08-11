"""Typed local HTTP boundary for the personal-AI control plane."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from opencobalt.core.approval_bridge import ApprovalError
from opencobalt.core.ledger import Ledger
from opencobalt.core.mission_engine import Mission, MissionStep, MissionStore
from opencobalt.core.models import SessionEvent
from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.models import WorkReceipt
from opencobalt.execution.runner import ProcessRunner, redact_text
from opencobalt.execution.store import ExecutionStore
from opencobalt.skills.registry import list_skills as list_builtin_skills

from .models import (
    AISettings,
    ChatExecution,
    ChatMessage,
    CommunicationControls,
    ControlLevel,
    Conversation,
    MemoryEntry,
    Persona,
    PersonaVersion,
    ProviderPreference,
    RouteCandidate,
    RouteRecord,
    SkillRecord,
    SkillVersion,
    StreamEvent,
)
from .personas import duplicate_persona, render_persona_policy
from .providers import (
    ProviderHealth,
    ProviderModel,
    ProviderModelCatalog,
    ProviderRegistry,
    ProviderStatus,
)
from .service import ChatLifecycleEvent, ChatRequest, ChatService
from .skill_import import (
    InstalledSkill,
    SkillActionApproval,
    SkillImportPreview,
    SkillImportService,
)
from .store import PersonalAIStore

router = APIRouter(prefix="/api/v1", tags=["personal-ai"])


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class APIContext:
    """One coherent service graph for one resolved local ledger."""

    db_path: Path
    store: PersonalAIStore
    execution_store: ExecutionStore
    engine: ExecutionEngine
    providers: ProviderRegistry
    service: ChatService
    ledger: Ledger
    missions: MissionStore
    skill_import: SkillImportService


_CONTEXTS: dict[Path, APIContext] = {}
_CONTEXT_LOCK = threading.RLock()


def _api_context() -> APIContext:
    """Resolve context at request time so changed working directories stay isolated."""
    db_path = (Path.cwd() / ".opencobalt" / "ledger.db").resolve()
    with _CONTEXT_LOCK:
        existing = _CONTEXTS.get(db_path)
        if existing is not None:
            return existing
        store = PersonalAIStore(db_path)
        ledger = Ledger(db_path)
        execution_store = ExecutionStore(db_path)
        state_root = db_path.parent
        engine = ExecutionEngine(
            store=execution_store,
            runner=ProcessRunner(artifact_dir=state_root / "artifacts"),
            events_path=state_root / "events" / "execution.jsonl",
        )
        providers = ProviderRegistry(engine)
        service = ChatService(store=store, providers=providers, enable_mock=True)
        context = APIContext(
            db_path=db_path,
            store=store,
            execution_store=execution_store,
            engine=engine,
            providers=providers,
            service=service,
            ledger=ledger,
            missions=MissionStore(db_path),
            skill_import=SkillImportService(
                store=store,
                ledger=ledger,
                install_root=state_root / "skills" / "imported",
            ),
        )
        _CONTEXTS[db_path] = context
        return context


def _not_found(kind: str, identifier: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown {kind}: {identifier}"
    )


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


def _safe_text(value: str) -> str:
    """Redact credential shapes and private home prefixes before UI exposure."""
    return redact_text(value).replace(str(Path.home()), "<home>")


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=200)
    project_path: str | None = Field(default=None, max_length=4096)

    @field_validator("title")
    @classmethod
    def _valid_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("conversation title cannot be blank")
        return value.strip()

    @field_validator("project_path")
    @classmethod
    def _valid_project_path(cls, value: str | None) -> str | None:
        if value is not None and "\x00" in value:
            raise ValueError("project path cannot contain a null byte")
        return value


class RouteListItem(RouteRecord):
    actual_provider: str | None = None
    actual_model: str | None = None
    verification: dict[str, Any] | None = None
    candidate_count: int = 0
    execution_count: int = 0


class ChatExecutionView(ChatExecution):
    """Frontend-safe execution attempt with redacted provider diagnostics."""


def _execution_view(execution: ChatExecution) -> ChatExecutionView:
    payload = execution.model_dump()
    if execution.provider_error_message is not None:
        payload["provider_error_message"] = _safe_text(execution.provider_error_message)
    return ChatExecutionView.model_validate(payload)


class StreamEventView(BaseModel):
    event_id: str
    execution_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


def _safe_event_identifier(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return _safe_text(value)[:500]


def _stream_event_payload(event: StreamEvent) -> dict[str, Any]:
    payload = event.payload
    if event.event_type == "text_delta":
        delta = payload.get("text_delta")
        return {
            "content_redacted": True,
            "text_characters": len(delta) if isinstance(delta, str) else 0,
        }

    if event.event_type == "completed":
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
        result: dict[str, Any] = {}
        for key, value in (
            ("message_id", message.get("message_id")),
            ("receipt_id", payload.get("receipt_id")),
            ("route_id", route.get("route_id")),
            ("memory_proposal_id", payload.get("memory_proposal_id")),
        ):
            safe = _safe_event_identifier(value)
            if safe is not None:
                result[key] = safe
        return result

    if event.event_type == "route_selected":
        route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
        result = {}
        for key in (
            "route_id",
            "selected_provider",
            "selected_model",
            "requested_persona_id",
        ):
            safe = _safe_event_identifier(route.get(key))
            if safe is not None:
                result[key] = safe
        candidate_count = payload.get("candidate_count")
        if isinstance(candidate_count, int) and not isinstance(candidate_count, bool):
            result["candidate_count"] = max(candidate_count, 0)
        return result

    if event.event_type == "usage":
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        result = {
            key: value
            for key, value in usage.items()
            if key
            in {
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "input_characters",
                "output_characters",
            }
            and (value is None or isinstance(value, int))
        }
        source = _safe_event_identifier(usage.get("source"))
        if source is not None:
            result["source"] = source
        return {"usage": result}

    if event.event_type == "tool_completed":
        tool = payload.get("tool_event") if isinstance(payload.get("tool_event"), dict) else {}
        result = {}
        for key in ("tool_call_id", "tool_name", "status"):
            safe = _safe_event_identifier(tool.get(key))
            if safe is not None:
                result[key] = safe
        summary = tool.get("summary")
        if isinstance(summary, str):
            result["summary_characters"] = len(summary)
            result["summary_redacted"] = True
        return {"tool_event": result}

    if event.event_type in {"error", "cancelled"}:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        safe_error: dict[str, Any] = {}
        for key in ("category", "message"):
            safe = _safe_event_identifier(error.get(key))
            if safe is not None:
                safe_error[key] = safe
        if isinstance(error.get("retryable"), bool):
            safe_error["retryable"] = error["retryable"]
        result: dict[str, Any] = {"error": safe_error}
        receipt_id = _safe_event_identifier(payload.get("receipt_id"))
        if receipt_id is not None:
            result["receipt_id"] = receipt_id
        for key in ("fallback_allowed", "fallback_used"):
            if isinstance(payload.get(key), bool):
                result[key] = payload[key]
        return result

    allowed_keys = {
        "request_accepted": ("message_id",),
        "execution_started": ("provider_id", "model_id", "attempt"),
        "provider_started": ("provider_id", "receipt_id"),
        "provider_completed": ("receipt_id",),
        "fallback_started": (
            "from_provider",
            "from_model",
            "to_provider",
            "to_model",
            "reason_category",
            "reason",
            "failed_receipt_id",
            "created_at",
        ),
    }.get(event.event_type)
    if allowed_keys is None:
        return {"payload_redacted": True}
    result = {}
    for key in allowed_keys:
        value = payload.get(key)
        if key == "attempt" and isinstance(value, int) and not isinstance(value, bool):
            result[key] = max(value, 0)
            continue
        safe = _safe_event_identifier(value)
        if safe is not None:
            result[key] = safe
    return result


def _stream_event_view(event: StreamEvent) -> StreamEventView:
    return StreamEventView(
        event_id=event.event_id,
        execution_id=event.execution_id,
        sequence=event.sequence,
        event_type=_safe_text(event.event_type)[:100],
        payload=_stream_event_payload(event),
        created_at=event.created_at,
    )


class RouteDetail(BaseModel):
    route: RouteRecord
    candidates: list[RouteCandidate]
    executions: list[ChatExecutionView]
    stream_events: list[StreamEventView]
    verification: dict[str, Any] | None = None
    selected_provider: str
    selected_model: str | None = None
    actual_provider: str | None = None
    actual_model: str | None = None
    receipt_id: str | None = None


class RouteRerunRequest(BaseModel):
    persona_id: str | None = Field(default=None, max_length=200)
    provider_id: str | None = Field(default=None, max_length=200)
    model_id: str | None = Field(default=None, max_length=200)
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None
    cognitive_policy: str | None = Field(default=None, max_length=100)
    local_only: bool | None = None
    allow_fallback: bool = False


class RouteRerunResponse(BaseModel):
    status: str
    request_id: str
    route_id: str
    events: list[ChatLifecycleEvent]


class CancellationResponse(BaseModel):
    execution_id: str
    status: Literal["cancel_requested"]


class MessageCompareRequest(BaseModel):
    first_message_id: str = Field(min_length=1, max_length=200)
    second_message_id: str = Field(min_length=1, max_length=200)


class MessageComparisonItem(BaseModel):
    message: ChatMessage
    route: RouteRecord


class MessageCompareResponse(BaseModel):
    responses: list[MessageComparisonItem]


class ControlsPatch(BaseModel):
    directness: ControlLevel | None = None
    warmth: ControlLevel | None = None
    formality: ControlLevel | None = None
    verbosity: ControlLevel | None = None
    challenge_level: ControlLevel | None = None
    emotional_attunement: ControlLevel | None = None
    speculation_tolerance: ControlLevel | None = None
    question_frequency: ControlLevel | None = None
    citation_preference: ControlLevel | None = None
    uncertainty_explicitness: ControlLevel | None = None


class PersonaView(Persona):
    active_version: PersonaVersion


class PersonaDuplicateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("persona name cannot be blank")
        return value.strip()


class PersonaUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=400)
    controls: ControlsPatch | None = None
    provider_affinities: dict[str, int] | None = None
    custom_instructions: str | None = Field(default=None, max_length=2000)
    allowed_cognitive_policies: list[str] | None = Field(default=None, min_length=1, max_length=20)

    @field_validator("name")
    @classmethod
    def _optional_name_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("persona name cannot be blank")
        return value.strip() if value is not None else None


class PersonaTestRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10_000)
    cognitive_policy: str | None = Field(default=None, max_length=100)

    @field_validator("prompt")
    @classmethod
    def _prompt_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sample prompt cannot be blank")
        return value


class PersonaTestResponse(BaseModel):
    persona_id: str
    persona_version_id: str
    cognitive_policy: str
    sample_prompt: str
    rendered_policy: str
    executed: Literal[False] = False


class ProviderView(ProviderStatus):
    enabled: bool = True
    priority: int = 50
    cost_policy: Literal["free_only", "prefer_subscription", "allow_billed"] = "prefer_subscription"
    models: list[ProviderModel] = Field(default_factory=list)
    last_successful_invocation: datetime | None = None
    recent_errors: list[dict[str, str]] = Field(default_factory=list)


class ProviderPreferenceView(BaseModel):
    provider_id: str
    enabled: bool
    priority: int
    cost_policy: Literal["free_only", "prefer_subscription", "allow_billed"]


class ProviderPreferenceUpdateRequest(BaseModel):
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    cost_policy: Literal["free_only", "prefer_subscription", "allow_billed"] | None = None


class MemoryCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    source_type: str = Field(min_length=1, max_length=100)
    source_ref: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)
    scope: Literal["user", "project", "conversation", "temporary"]
    status: Literal["proposed", "active", "rejected"] = "proposed"
    sensitivity: Literal["normal", "sensitive"] = "normal"
    pinned: bool = False
    conversation_id: str | None = Field(default=None, max_length=200)
    source_message_id: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content", "source_type", "reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("memory text fields cannot be blank")
        return value.strip()


class MemoryUpdateRequest(BaseModel):
    content: str | None = Field(default=None, max_length=20_000)
    reason: str | None = Field(default=None, max_length=1000)
    scope: Literal["user", "project", "conversation", "temporary"] | None = None
    status: Literal["proposed", "active", "rejected"] | None = None
    sensitivity: Literal["normal", "sensitive"] | None = None
    pinned: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("content", "reason")
    @classmethod
    def _optional_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("memory text fields cannot be blank")
        return value.strip() if value is not None else None


class SettingsUpdateRequest(BaseModel):
    default_routing_mode: Literal["automatic", "manual"] | None = None
    default_persona_id: str | None = Field(default=None, max_length=200)
    local_only_default: bool | None = None
    privacy_policy: Literal["standard", "private", "sensitive"] | None = None
    approval_policy: Literal["ask_for_risk", "always_ask", "deny_tools"] | None = None
    cost_ceiling_category: Literal["free", "low", "standard", "high"] | None = None
    provider_priority: list[str] | None = Field(default=None, max_length=20)
    memory_behavior: Literal["off", "propose", "explicit_only"] | None = None
    skill_permissions: Literal["deny", "ask", "allow_builtin"] | None = None
    verification_preference: Literal["minimal", "task_appropriate", "strict"] | None = None
    theme: Literal["system", "dark", "light"] | None = None


class SafeSkillVersion(BaseModel):
    skill_version_id: str
    skill_id: str
    version: str
    content_hash: str
    manifest: dict[str, Any] = Field(default_factory=dict)
    installed: bool
    receipt_id: str | None = None
    created_at: datetime


class SkillView(SkillRecord):
    versions: list[SafeSkillVersion] = Field(default_factory=list)


class InstalledSkillView(BaseModel):
    skill: SkillRecord
    version: SafeSkillVersion
    receipt_id: str
    approval_decision_id: str | None = None


class SkillPreviewRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=4096)

    @field_validator("source_path")
    @classmethod
    def _safe_source_path(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("source path cannot contain a null byte")
        return value


class SkillInstallRequest(BaseModel):
    preview_id: str = Field(min_length=1, max_length=200)
    approval_request_id: str | None = Field(default=None, max_length=200)


class ApprovalDecisionRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class ApprovalDecisionResponse(BaseModel):
    approval_request_id: str
    approved_step_ids: list[str]
    status: Literal["approved"] = "approved"


class SkillActionRequest(BaseModel):
    action: Literal["rollback", "remove"]


class SkillUpdateRequest(BaseModel):
    enabled: bool


class SkillApprovedActionRequest(BaseModel):
    approval_request_id: str = Field(min_length=1, max_length=200)


class SkillRemovalResponse(BaseModel):
    receipt_id: str
    status: Literal["removed"] = "removed"


class MissionRecordView(BaseModel):
    mission_id: str
    goal: str
    mission_type: str
    status: str
    max_risk: str
    run_id: str | None = None
    evolve_mission_id: str | None = None
    selected_track_id: str | None = None
    selected_candidate_id: str | None = None
    active_plan_id: str | None = None
    approval_request_id: str | None = None
    last_receipt_id: str | None = None
    outcome: str | None = None
    outcome_id: str | None = None
    summary: str = ""
    auto_plan_id: str | None = None
    auto_plan_hash: str | None = None
    auto_intent: str | None = None
    autonomy_envelope: str | None = None
    cognitive_budget: str | None = None
    auto_next_action: str | None = None
    auto_required_approvals: list[str] = Field(default_factory=list)
    auto_expected_receipts: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class MissionStepView(BaseModel):
    step_id: str
    mission_id: str
    title: str
    command_or_action: str = ""
    risk_level: str
    approval_state: str
    execution_state: str
    source_track_id: str | None = None
    source_candidate_id: str | None = None
    source_plan_id: str | None = None
    approval_request_id: str | None = None
    approval_step_id: str | None = None
    execution_plan_id: str | None = None
    receipt_id: str | None = None
    auto_step_order: int | None = None
    auto_primitive: str | None = None
    auto_step_why: str = ""
    auto_promotion_classification: str = ""
    auto_promotion_reason: str = ""
    uses_execution_engine: bool
    requires_approval: bool
    expected_receipt: bool
    blocked_authority: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class MissionListItem(MissionRecordView):
    route_id: str | None = None
    conversation_id: str | None = None
    steps: list[MissionStepView] = Field(default_factory=list)


class MissionPromotionResponse(BaseModel):
    mission: MissionRecordView
    steps: list[MissionStepView]


class RedactedReceipt(BaseModel):
    receipt_id: str
    plan_id: str
    execution_id: str | None = None
    selected_runtime: str
    route_reason: str | None = None
    risk_level: str
    approval_required: bool
    artifact_ids: list[str]
    verification_status: str
    adapter_id: str | None = None
    capability_snapshot_hash: str | None = None
    limitations: list[str]
    provenance_refs: list[str]
    created_at: datetime


class PersonalAIExport(BaseModel):
    schema_version: Literal[1] = 1
    exported_at: datetime
    conversations: list[Conversation]
    messages: list[ChatMessage]
    personas: list[PersonaView]
    routes: list[RouteListItem]
    executions: list[ChatExecutionView]
    memories: list[MemoryEntry]
    skills: list[SkillView]
    missions: list[MissionListItem]
    receipts: list[RedactedReceipt]
    settings: AISettings
    provider_preferences: list[ProviderPreference]


class RetentionLimitations(BaseModel):
    bulk_deletion_available: Literal[False] = False
    conversation_deletion_available: Literal[False] = False
    memory_deletion_endpoint: str = "/api/v1/memory/{memory_id}"
    reason: str


@router.get("/conversations", response_model=list[Conversation])
def list_conversations(
    limit: int = Query(default=100, ge=1, le=500),
    include_archived: bool = False,
) -> list[Conversation]:
    return _api_context().store.list_conversations(
        limit=limit,
        include_archived=include_archived,
    )


@router.post(
    "/conversations",
    response_model=Conversation,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(request: ConversationCreate) -> Conversation:
    project_path = _canonical_project_path(request.project_path)
    return _api_context().service.create_conversation(
        title=request.title,
        project_path=project_path,
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[ChatMessage],
)
def list_messages(
    conversation_id: str,
    limit: int = Query(default=500, ge=1, le=500),
) -> list[ChatMessage]:
    context = _api_context()
    if context.store.get_conversation(conversation_id) is None:
        raise _not_found("conversation", conversation_id)
    return context.store.list_messages(conversation_id, limit=limit)


@router.post("/messages/compare", response_model=MessageCompareResponse)
def compare_messages(request: MessageCompareRequest) -> MessageCompareResponse:
    context = _api_context()
    try:
        compared = context.service.compare(
            request.first_message_id,
            request.second_message_id,
        )
    except KeyError as exc:
        raise _not_found("message", _error_text(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise _conflict(_error_text(exc)) from exc
    return MessageCompareResponse(
        responses=[MessageComparisonItem.model_validate(item) for item in compared]
    )


def _canonical_project_path(project_path: str | None) -> str | None:
    if project_path is None:
        return None
    workspace_root = Path.cwd().resolve()
    try:
        resolved = Path(project_path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise _unprocessable("Project path must be an existing directory") from exc
    if not resolved.is_dir():
        raise _unprocessable("Project path must be an existing directory")
    if resolved != workspace_root and not resolved.is_relative_to(workspace_root):
        raise _unprocessable("Project path must stay within the current workspace root")
    return str(resolved)


_RESERVED_CHAT_METADATA_KEYS = frozenset(
    {
        "actual_model_id",
        "actual_provider_id",
        "cognitive_policy",
        "local_only",
        "privacy_mode",
        "privacy_policy",
        "reasoning_effort",
        "requested_persona_id",
        "rerun_of_route_id",
        "risk_classification",
        "routing",
        "verification",
    }
)


def _enforce_answer_only_chat_policy(
    context: APIContext,
    *,
    requested_tools: list[str] | None = None,
    requested_skills: list[str] | None = None,
) -> None:
    settings = context.store.get_settings()
    if settings.approval_policy == "always_ask":
        raise _conflict(
            "The always-ask approval policy blocks chat execution until a chat approval "
            "resume lifecycle is available"
        )
    if requested_tools or requested_skills:
        raise _conflict(
            "Tool and skill execution requires an approval lifecycle and is not enabled "
            "through this answer-only chat API"
        )


def _validate_chat_request(context: APIContext, request: ChatRequest) -> ChatRequest:
    if context.store.get_conversation(request.conversation_id) is None:
        raise _not_found("conversation", request.conversation_id)
    persona = context.store.get_active_persona_version(request.persona_id)
    if persona is None:
        raise _not_found("persona", request.persona_id)
    if (
        request.cognitive_policy is not None
        and request.cognitive_policy not in persona.allowed_cognitive_policies
    ):
        raise _unprocessable(
            f"Cognitive policy {request.cognitive_policy!r} is not allowed by persona "
            f"{request.persona_id}"
        )
    if request.provider_override is not None:
        try:
            context.providers.get(request.provider_override)
        except KeyError as exc:
            raise _not_found("provider", request.provider_override) from exc
    reserved = sorted(_RESERVED_CHAT_METADATA_KEYS.intersection(request.metadata))
    if reserved:
        raise _unprocessable(
            "Chat metadata contains reserved authoritative key(s): " + ", ".join(reserved)
        )
    _enforce_answer_only_chat_policy(
        context,
        requested_tools=request.requested_tools,
        requested_skills=request.requested_skills,
    )
    if not request.metadata:
        return request
    return request.model_copy(update={"metadata": {"user_metadata": request.metadata}})


def _stream_ndjson(service: ChatService, request: ChatRequest):
    """Serialize lifecycle events and cancel a still-active execution on disconnect."""
    active_execution_id: str | None = None
    try:
        for event in service.stream_request(request):
            if event.event_type == "execution_started":
                active_execution_id = event.execution_id
            elif event.event_type in {"completed", "cancelled", "error"}:
                active_execution_id = None
            yield event.model_dump_json() + "\n"
    finally:
        if active_execution_id is not None:
            service.cancel(active_execution_id)


@router.post("/chat/stream")
def stream_chat(request: ChatRequest) -> StreamingResponse:
    context = _api_context()
    request = _validate_chat_request(context, request)
    return StreamingResponse(
        _stream_ndjson(context.service, request),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/executions/{execution_id}/cancel",
    response_model=CancellationResponse,
)
def cancel_execution(execution_id: str) -> CancellationResponse:
    context = _api_context()
    if context.service.cancel(execution_id):
        return CancellationResponse(execution_id=execution_id, status="cancel_requested")
    execution = context.store.get_execution(execution_id)
    if execution is None:
        raise _not_found("execution", execution_id)
    if execution.status == "cancel_requested":
        return CancellationResponse(execution_id=execution_id, status="cancel_requested")
    if execution.status in {"complete", "failed", "cancelled"}:
        raise _conflict(f"Execution {execution_id} is already {execution.status}")
    raise _conflict(
        "Execution is not cancellable in this process; its in-memory cancellation token "
        "is unavailable"
    )


def _route_detail(context: APIContext, route: RouteRecord) -> RouteDetail:
    candidates = context.store.list_route_candidates(route.route_id)
    executions = [
        execution
        for execution in context.store.list_executions(request_id=route.request_id, limit=500)
        if execution.route_id == route.route_id
    ]
    stream_events = [
        event
        for execution in executions
        for event in context.store.list_stream_events(execution.execution_id)
    ]
    stream_events.sort(
        key=lambda event: (
            event.created_at,
            event.execution_id,
            event.sequence,
            event.event_id,
        )
    )
    attempted = executions[0] if executions else None
    actual_provider = route.metadata.get("actual_provider_id")
    actual_model = route.metadata.get("actual_model_id")
    if actual_provider is None and attempted is not None:
        actual_provider = attempted.provider_id
        actual_model = attempted.model_id
    return RouteDetail(
        route=route,
        candidates=candidates,
        executions=[_execution_view(execution) for execution in executions],
        stream_events=[_stream_event_view(event) for event in stream_events],
        verification=route.metadata.get("verification"),
        selected_provider=route.selected_provider,
        selected_model=route.selected_model,
        actual_provider=actual_provider,
        actual_model=actual_model,
        receipt_id=route.receipt_id,
    )


@router.get("/routes", response_model=list[RouteListItem])
def list_routes(
    conversation_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RouteListItem]:
    context = _api_context()
    result: list[RouteListItem] = []
    for route in context.store.list_routes(conversation_id=conversation_id, limit=limit):
        detail = _route_detail(context, route)
        result.append(
            RouteListItem(
                **route.model_dump(),
                actual_provider=detail.actual_provider,
                actual_model=detail.actual_model,
                verification=detail.verification,
                candidate_count=len(detail.candidates),
                execution_count=len(detail.executions),
            )
        )
    return result


@router.get("/routes/{route_id}", response_model=RouteDetail)
def get_route(route_id: str) -> RouteDetail:
    context = _api_context()
    route = context.store.get_route(route_id)
    if route is None:
        raise _not_found("route", route_id)
    return _route_detail(context, route)


@router.post("/routes/{route_id}/rerun", response_model=RouteRerunResponse)
def rerun_route(route_id: str, request: RouteRerunRequest) -> RouteRerunResponse:
    context = _api_context()
    source_route = context.store.get_route(route_id)
    if source_route is None:
        raise _not_found("route", route_id)
    _enforce_answer_only_chat_policy(
        context,
        requested_tools=source_route.selected_tools,
        requested_skills=source_route.selected_skills,
    )
    if request.persona_id is not None and context.store.get_persona(request.persona_id) is None:
        raise _not_found("persona", request.persona_id)
    if request.provider_id is not None:
        try:
            context.providers.get(request.provider_id)
        except KeyError as exc:
            raise _not_found("provider", request.provider_id) from exc
    try:
        events = list(
            context.service.rerun(
                route_id,
                persona_id=request.persona_id,
                provider_id=request.provider_id,
                model_id=request.model_id,
                reasoning_effort=request.reasoning_effort,
                cognitive_policy=request.cognitive_policy,
                local_only=request.local_only,
                allow_fallback=request.allow_fallback,
            )
        )
    except ValueError as exc:
        raise _unprocessable(_error_text(exc)) from exc
    if not events or events[-1].route_id is None:
        raise _conflict("Rerun ended without a persisted route")
    terminal = events[-1].event_type
    outcome = {
        "completed": "complete",
        "cancelled": "cancelled",
        "route_failed": "policy_denied",
        "error": "failed",
    }.get(terminal, terminal)
    return RouteRerunResponse(
        status=outcome,
        request_id=events[-1].request_id,
        route_id=events[-1].route_id,
        events=events,
    )


def _mission_record(mission: Mission) -> MissionRecordView:
    return MissionRecordView.model_validate(asdict(mission))


def _mission_steps(context: APIContext, mission_id: str) -> list[MissionStepView]:
    return [
        MissionStepView.model_validate(asdict(step))
        for step in context.missions.list_steps(mission_id)
    ]


@router.post(
    "/routes/{route_id}/promote",
    response_model=MissionPromotionResponse,
    status_code=status.HTTP_201_CREATED,
)
def promote_route(route_id: str) -> MissionPromotionResponse:
    context = _api_context()
    route = context.store.get_route(route_id)
    if route is None:
        raise _not_found("route", route_id)
    source = context.store.get_message(route.request_message_id)
    if source is None:
        raise _conflict(f"Route {route_id} has no source user message")

    suffix = route.request_id.removeprefix("req-")
    mission_id = f"mis-chat-{suffix}"
    existing = context.missions.get_mission(mission_id)
    if existing is not None:
        return MissionPromotionResponse(
            mission=_mission_record(existing),
            steps=_mission_steps(context, existing.mission_id),
        )

    mission = Mission(
        mission_id=mission_id,
        goal=source.content,
        mission_type="opportunity",
        status="plan_proposed",
        active_plan_id=route.route_id,
        last_receipt_id=route.receipt_id,
        summary=(
            f"Promoted from personal-AI route {route.route_id} in conversation "
            f"{route.conversation_id}; selected provider {route.selected_provider}."
        ),
    )
    step = MissionStep(
        step_id=f"mst-chat-{suffix}",
        mission_id=mission.mission_id,
        title="Review the promoted request and define the next bounded action",
        command_or_action="Planning only; continue through the supervised mission workflow.",
        risk_level="green",
        approval_state="pending",
        execution_state="not_started",
        source_plan_id=route.route_id,
        receipt_id=route.receipt_id,
        uses_execution_engine=False,
        requires_approval=False,
        expected_receipt=False,
    )
    context.missions.save_mission(mission)
    context.missions.save_step(step)
    context.missions.append_mission_event(
        mission.mission_id,
        "mission.chat_route_promoted",
        {
            "route_id": route.route_id,
            "conversation_id": route.conversation_id,
            "request_message_id": route.request_message_id,
            "receipt_id": route.receipt_id,
            "planning_only": True,
        },
    )
    return MissionPromotionResponse(
        mission=_mission_record(mission),
        steps=[MissionStepView.model_validate(asdict(step))],
    )


def _persona_view(context: APIContext, persona: Persona) -> PersonaView:
    version = context.store.get_active_persona_version(persona.persona_id)
    if version is None:
        raise _conflict(f"Persona {persona.persona_id} has no active version")
    return PersonaView(**persona.model_dump(), active_version=version)


@router.get("/personas", response_model=list[PersonaView])
def list_personas() -> list[PersonaView]:
    context = _api_context()
    return [_persona_view(context, persona) for persona in context.store.list_personas()]


@router.post(
    "/personas/{persona_id}/duplicate",
    response_model=PersonaView,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_persona_endpoint(
    persona_id: str,
    request: PersonaDuplicateRequest,
) -> PersonaView:
    context = _api_context()
    try:
        persona = duplicate_persona(context.store, persona_id, request.name)
    except KeyError as exc:
        raise _not_found("persona", persona_id) from exc
    return _persona_view(context, persona)


@router.patch("/personas/{persona_id}", response_model=PersonaView)
def update_persona(persona_id: str, request: PersonaUpdateRequest) -> PersonaView:
    context = _api_context()
    persona = context.store.get_persona(persona_id)
    active = context.store.get_active_persona_version(persona_id)
    if persona is None or active is None:
        raise _not_found("persona", persona_id)
    if persona.built_in:
        raise _conflict("Duplicate a built-in persona before editing it")

    controls = active.controls
    if request.controls is not None:
        controls = CommunicationControls.model_validate(
            {
                **active.controls.model_dump(),
                **request.controls.model_dump(exclude_none=True),
            }
        )
    try:
        version = PersonaVersion(
            persona_id=persona.persona_id,
            version=active.version + 1,
            controls=controls,
            allowed_cognitive_policies=(
                request.allowed_cognitive_policies
                if request.allowed_cognitive_policies is not None
                else list(active.allowed_cognitive_policies)
            ),
            provider_affinities=(
                request.provider_affinities
                if request.provider_affinities is not None
                else dict(active.provider_affinities)
            ),
            custom_instructions=(
                request.custom_instructions
                if request.custom_instructions is not None
                else active.custom_instructions
            ),
            native_provider_family=active.native_provider_family,
        )
    except ValueError as exc:
        raise _unprocessable(_error_text(exc)) from exc
    updated = persona.model_copy(
        update={
            "name": request.name if request.name is not None else persona.name,
            "description": (
                request.description if request.description is not None else persona.description
            ),
            "updated_at": _now(),
        }
    )
    context.store.save_persona(updated)
    context.store.add_persona_version(version)
    saved = context.store.get_persona(persona_id)
    if saved is None:
        raise _conflict("Persona update was not persisted")
    return _persona_view(context, saved)


@router.post("/personas/{persona_id}/test", response_model=PersonaTestResponse)
def test_persona(persona_id: str, request: PersonaTestRequest) -> PersonaTestResponse:
    context = _api_context()
    version = context.store.get_active_persona_version(persona_id)
    if version is None:
        raise _not_found("persona", persona_id)
    cognitive_policy = request.cognitive_policy or version.allowed_cognitive_policies[0]
    try:
        rendered = render_persona_policy(version, cognitive_policy)
    except ValueError as exc:
        raise _unprocessable(_error_text(exc)) from exc
    return PersonaTestResponse(
        persona_id=persona_id,
        persona_version_id=version.persona_version_id,
        cognitive_policy=cognitive_policy,
        sample_prompt=request.prompt,
        rendered_policy=rendered,
    )


@router.post("/personas/{persona_id}/reset", response_model=PersonaView)
def reset_persona(persona_id: str) -> PersonaView:
    context = _api_context()
    persona = context.store.get_persona(persona_id)
    active = context.store.get_active_persona_version(persona_id)
    baseline = context.store.get_persona_version(f"pver-{persona_id}-v1")
    if persona is None or active is None:
        raise _not_found("persona", persona_id)
    if not persona.built_in or baseline is None:
        raise _conflict("Only built-in personas have an OpenCobalt default to reset")
    reset_version = PersonaVersion(
        persona_id=persona.persona_id,
        version=active.version + 1,
        controls=baseline.controls.model_copy(deep=True),
        allowed_cognitive_policies=list(baseline.allowed_cognitive_policies),
        provider_affinities=dict(baseline.provider_affinities),
        custom_instructions=baseline.custom_instructions,
        native_provider_family=baseline.native_provider_family,
    )
    context.store.add_persona_version(reset_version)
    saved = context.store.get_persona(persona_id)
    if saved is None:
        raise _conflict("Persona reset was not persisted")
    return _persona_view(context, saved)


@router.get("/providers", response_model=list[ProviderView])
def list_providers() -> list[ProviderView]:
    context = _api_context()
    preferences = {item.provider_id: item for item in context.store.list_provider_preferences()}
    executions = context.store.list_executions(limit=500)
    result: list[ProviderView] = []
    for provider_status in context.providers.discover():
        preference = preferences.get(provider_status.provider_id)
        successful = next(
            (
                execution.finished_at
                for execution in executions
                if execution.provider_id == provider_status.provider_id
                and execution.status == "complete"
            ),
            None,
        )
        recent_errors = [
            {
                "category": execution.provider_error_type or "provider_error",
                "message": _safe_text(execution.provider_error_message or "Provider failed"),
            }
            for execution in executions
            if execution.provider_id == provider_status.provider_id and execution.status == "failed"
        ][:3]
        models: list[ProviderModel] = []
        if provider_status.provider_id == "mock":
            models = context.providers.get("mock").discover_models().models
        result.append(
            ProviderView(
                **provider_status.model_dump(),
                enabled=preference.enabled if preference is not None else True,
                priority=preference.priority if preference is not None else 50,
                cost_policy=(
                    preference.cost_policy if preference is not None else "prefer_subscription"
                ),
                models=models,
                last_successful_invocation=successful,
                recent_errors=recent_errors,
            )
        )
    return result


def _provider(context: APIContext, provider_id: str):
    try:
        return context.providers.get(provider_id)
    except KeyError as exc:
        raise _not_found("provider", provider_id) from exc


@router.post("/providers/{provider_id}/health", response_model=ProviderHealth)
def provider_health(provider_id: str) -> ProviderHealth:
    return _provider(_api_context(), provider_id).health()


@router.get("/providers/{provider_id}/models", response_model=ProviderModelCatalog)
def provider_models(provider_id: str, local_only: bool = False) -> ProviderModelCatalog:
    return _provider(_api_context(), provider_id).discover_models(local_only=local_only)


def _provider_preference(context: APIContext, provider_id: str) -> ProviderPreference:
    _provider(context, provider_id)
    stored = next(
        (
            preference
            for preference in context.store.list_provider_preferences()
            if preference.provider_id == provider_id
        ),
        None,
    )
    return stored or ProviderPreference(provider_id=provider_id)


def _preference_view(preference: ProviderPreference) -> ProviderPreferenceView:
    return ProviderPreferenceView(
        provider_id=preference.provider_id,
        enabled=preference.enabled,
        priority=preference.priority,
        cost_policy=preference.cost_policy,
    )


@router.get(
    "/providers/{provider_id}/preference",
    response_model=ProviderPreferenceView,
)
def get_provider_preference(provider_id: str) -> ProviderPreferenceView:
    return _preference_view(_provider_preference(_api_context(), provider_id))


@router.patch(
    "/providers/{provider_id}/preference",
    response_model=ProviderPreferenceView,
)
def update_provider_preference(
    provider_id: str,
    request: ProviderPreferenceUpdateRequest,
) -> ProviderPreferenceView:
    context = _api_context()
    current = _provider_preference(context, provider_id)
    preference = current.model_copy(
        update={**request.model_dump(exclude_none=True), "updated_at": _now()}
    )
    context.store.save_provider_preference(preference)
    return _preference_view(preference)


@router.get("/memory", response_model=list[MemoryEntry])
def list_memory(
    memory_status: Literal["proposed", "active", "rejected"] | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[MemoryEntry]:
    return _api_context().store.list_memory(status=memory_status, limit=limit)


@router.get("/memory/{memory_id}", response_model=MemoryEntry)
def get_memory(memory_id: str) -> MemoryEntry:
    memory = _api_context().store.get_memory(memory_id)
    if memory is None:
        raise _not_found("memory", memory_id)
    return memory


def _validate_memory_references(context: APIContext, request: MemoryCreateRequest) -> None:
    conversation = None
    if request.conversation_id is not None:
        conversation = context.store.get_conversation(request.conversation_id)
        if conversation is None:
            raise _not_found("conversation", request.conversation_id)
    if request.source_message_id is not None:
        message = context.store.get_message(request.source_message_id)
        if message is None:
            raise _not_found("message", request.source_message_id)
        if conversation is not None and message.conversation_id != conversation.conversation_id:
            raise _conflict("Memory conversation and source message do not match")


@router.post("/memory", response_model=MemoryEntry, status_code=status.HTTP_201_CREATED)
def create_memory(request: MemoryCreateRequest) -> MemoryEntry:
    context = _api_context()
    _validate_memory_references(context, request)
    memory = MemoryEntry(**request.model_dump())
    context.store.save_memory(memory)
    return memory


@router.patch("/memory/{memory_id}", response_model=MemoryEntry)
def update_memory(memory_id: str, request: MemoryUpdateRequest) -> MemoryEntry:
    context = _api_context()
    memory = context.store.get_memory(memory_id)
    if memory is None:
        raise _not_found("memory", memory_id)
    updated = memory.model_copy(
        update={**request.model_dump(exclude_none=True), "updated_at": _now()}
    )
    context.store.save_memory(updated)
    saved = context.store.get_memory(memory_id)
    if saved is None:
        raise _conflict("Memory update was not persisted")
    return saved


@router.delete("/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: str) -> Response:
    if not _api_context().store.delete_memory(memory_id):
        raise _not_found("memory", memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _safe_skill_version(version: SkillVersion) -> SafeSkillVersion:
    return SafeSkillVersion(
        skill_version_id=version.skill_version_id,
        skill_id=version.skill_id,
        version=version.version,
        content_hash=version.content_hash,
        manifest=version.manifest,
        installed=(version.install_path is not None and Path(version.install_path).is_dir()),
        receipt_id=version.receipt_id,
        created_at=version.created_at,
    )


def _installed_skill_view(installed: InstalledSkill) -> InstalledSkillView:
    return InstalledSkillView(
        skill=installed.skill,
        version=_safe_skill_version(installed.version),
        receipt_id=installed.receipt_id,
        approval_decision_id=installed.approval_decision_id,
    )


@router.get("/skills", response_model=list[SkillView])
def list_skills() -> list[SkillView]:
    context = _api_context()
    result = [
        SkillView(
            skill_id=f"builtin:{item['name']}",
            name=item["name"],
            description=item["description"],
            source_kind="builtin",
            source_ref="opencobalt.skills.registry",
            enabled=True,
            trust_level="builtin",
        )
        for item in list_builtin_skills()
    ]
    for skill in context.store.list_skills():
        result.append(
            SkillView(
                **skill.model_dump(),
                versions=[
                    _safe_skill_version(version)
                    for version in context.store.list_skill_versions(skill.skill_id)
                ],
            )
        )
    return result


@router.get("/skills/discovery")
def skill_discovery() -> dict[str, bool | str]:
    return SkillImportService.online_discovery_status()


def _skill_view(context: APIContext, skill: SkillRecord) -> SkillView:
    return SkillView(
        **skill.model_dump(),
        versions=[
            _safe_skill_version(version)
            for version in context.store.list_skill_versions(skill.skill_id)
        ],
    )


@router.get("/skills/{skill_id}", response_model=SkillView)
def get_skill(skill_id: str) -> SkillView:
    context = _api_context()
    skill = context.store.get_skill(skill_id)
    if skill is None:
        raise _not_found("imported or user skill", skill_id)
    return _skill_view(context, skill)


@router.patch("/skills/{skill_id}", response_model=SkillView)
def update_skill(skill_id: str, request: SkillUpdateRequest) -> SkillView:
    context = _api_context()
    skill = context.store.get_skill(skill_id)
    if skill is None:
        raise _not_found("imported or user skill", skill_id)
    if request.enabled and skill.source_kind == "imported":
        if skill.active_version_id is None:
            raise _conflict("Imported skill has no pinned active version")
        version = context.store.get_skill_version(skill.active_version_id)
        if version is None:
            raise _conflict("Imported skill active version is missing")
        try:
            context.skill_import._verified_install_path(skill, version)
        except ValueError as exc:
            raise _conflict(_error_text(exc)) from exc
    updated = skill.model_copy(update={"enabled": request.enabled, "updated_at": _now()})
    context.store.save_skill(updated)
    context.store.record_event(
        SessionEvent(
            project="opencobalt",
            source="personal-ai-skill-registry",
            event_type="skill.enabled" if request.enabled else "skill.disabled",
            summary=(
                f"{'Enabled' if request.enabled else 'Disabled'} skill {updated.name} "
                "after explicit local user action"
            ),
            metadata={
                "skill_id": updated.skill_id,
                "active_version_id": updated.active_version_id,
                "source_kind": updated.source_kind,
            },
        )
    )
    return _skill_view(context, updated)


@router.post("/skills/import/preview", response_model=SkillImportPreview)
def preview_skill(request: SkillPreviewRequest) -> SkillImportPreview:
    try:
        return _api_context().skill_import.preview(request.source_path)
    except ValueError as exc:
        raise _unprocessable(_error_text(exc)) from exc


@router.post(
    "/skills/import/install",
    response_model=InstalledSkillView,
    status_code=status.HTTP_201_CREATED,
)
def install_skill(request: SkillInstallRequest) -> InstalledSkillView:
    try:
        installed = _api_context().skill_import.install(
            request.preview_id,
            approval_request_id=request.approval_request_id,
        )
    except KeyError as exc:
        raise _not_found("skill preview", request.preview_id) from exc
    except (PermissionError, ValueError) as exc:
        raise _conflict(_error_text(exc)) from exc
    return _installed_skill_view(installed)


@router.post(
    "/skills/approvals/{approval_request_id}/approve",
    response_model=ApprovalDecisionResponse,
)
def approve_skill_action(
    approval_request_id: str,
    request: ApprovalDecisionRequest,
) -> ApprovalDecisionResponse:
    context = _api_context()
    approval_request = context.skill_import.approval_bridge.store.get_request(approval_request_id)
    if approval_request is None:
        raise _not_found("approval request", approval_request_id)
    allowed_actions = {"import", "rollback", "remove"}
    if (
        approval_request.source_type != "personal_ai_skill"
        or approval_request.metadata.get("action") not in allowed_actions
        or any(
            step.source_type != "personal_ai_skill"
            or step.metadata.get("action") not in allowed_actions
            for step in approval_request.steps
        )
    ):
        raise _conflict("Approval request is outside the personal-AI skill boundary")
    try:
        approved = context.skill_import.approval_bridge.approve(
            approval_request_id,
            reason=request.reason,
            decided_by="human-local-ui",
        )
    except KeyError as exc:
        raise _not_found("approval request", approval_request_id) from exc
    except ApprovalError as exc:
        raise _conflict(_error_text(exc)) from exc
    if not approved:
        raise _conflict("Approval request has no approvable pending steps")
    return ApprovalDecisionResponse(
        approval_request_id=approval_request_id,
        approved_step_ids=[step.step_id for step in approved],
    )


@router.post(
    "/skills/{skill_id}/versions/{skill_version_id}/actions",
    response_model=SkillActionApproval,
    status_code=status.HTTP_201_CREATED,
)
def request_skill_action(
    skill_id: str,
    skill_version_id: str,
    request: SkillActionRequest,
) -> SkillActionApproval:
    try:
        return _api_context().skill_import.request_version_action(
            skill_id,
            skill_version_id,
            action=request.action,
        )
    except KeyError as exc:
        raise _not_found("imported skill or version", skill_version_id) from exc
    except ValueError as exc:
        raise _conflict(_error_text(exc)) from exc


@router.post(
    "/skills/{skill_id}/versions/{skill_version_id}/rollback",
    response_model=SkillRecord,
)
def rollback_skill(
    skill_id: str,
    skill_version_id: str,
    request: SkillApprovedActionRequest,
) -> SkillRecord:
    try:
        return _api_context().skill_import.rollback(
            skill_id,
            skill_version_id,
            approval_request_id=request.approval_request_id,
        )
    except KeyError as exc:
        raise _not_found("imported skill or version", skill_version_id) from exc
    except (PermissionError, ValueError) as exc:
        raise _conflict(_error_text(exc)) from exc


@router.post(
    "/skills/{skill_id}/versions/{skill_version_id}/remove",
    response_model=SkillRemovalResponse,
)
def remove_skill_version(
    skill_id: str,
    skill_version_id: str,
    request: SkillApprovedActionRequest,
) -> SkillRemovalResponse:
    try:
        receipt_id = _api_context().skill_import.remove_version(
            skill_id,
            skill_version_id,
            approval_request_id=request.approval_request_id,
        )
    except KeyError as exc:
        raise _not_found("imported skill or version", skill_version_id) from exc
    except (PermissionError, ValueError) as exc:
        raise _conflict(_error_text(exc)) from exc
    return SkillRemovalResponse(receipt_id=receipt_id)


@router.get("/missions", response_model=list[MissionListItem])
def list_missions(limit: int = Query(default=100, ge=1, le=500)) -> list[MissionListItem]:
    context = _api_context()
    result: list[MissionListItem] = []
    for summary in context.missions.list_missions(limit=limit):
        mission = context.missions.get_mission(summary["mission_id"])
        if mission is None:
            continue
        route_id = None
        conversation_id = None
        for event in context.missions.list_mission_events(mission.mission_id):
            if event["event_type"] == "mission.chat_route_promoted":
                route_id = event["payload"].get("route_id")
                conversation_id = event["payload"].get("conversation_id")
        result.append(
            MissionListItem(
                **asdict(mission),
                route_id=route_id,
                conversation_id=conversation_id,
                steps=_mission_steps(context, mission.mission_id),
            )
        )
    return result


def _redacted_receipt(receipt: WorkReceipt) -> RedactedReceipt:
    return RedactedReceipt(
        receipt_id=receipt.receipt_id,
        plan_id=receipt.plan_id,
        execution_id=receipt.execution_id,
        selected_runtime=receipt.selected_runtime,
        route_reason=_safe_text(receipt.route_reason) if receipt.route_reason else None,
        risk_level=receipt.risk_level,
        approval_required=receipt.approval_required,
        artifact_ids=list(receipt.artifact_ids),
        verification_status=receipt.verification_status,
        adapter_id=receipt.adapter_id,
        capability_snapshot_hash=receipt.capability_snapshot_hash,
        limitations=[_safe_text(item) for item in receipt.limitations],
        provenance_refs=[_safe_text(item) for item in receipt.provenance_refs],
        created_at=receipt.created_at,
    )


@router.get("/ledger/receipts", response_model=list[RedactedReceipt])
def list_receipts(
    runtime: str | None = None,
    verification_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RedactedReceipt]:
    receipts = _api_context().execution_store.list_receipts(
        runtime=runtime,
        verification_status=verification_status,
        limit=limit,
    )
    return [_redacted_receipt(receipt) for receipt in receipts]


@router.get("/settings", response_model=AISettings)
def get_settings() -> AISettings:
    return _api_context().store.get_settings()


@router.put("/settings", response_model=AISettings)
def update_settings(request: SettingsUpdateRequest) -> AISettings:
    context = _api_context()
    updates = request.model_dump(exclude_none=True)
    persona_id = updates.get("default_persona_id")
    if persona_id is not None and context.store.get_persona(persona_id) is None:
        raise _not_found("persona", persona_id)
    priorities = updates.get("provider_priority")
    if priorities is not None and len(priorities) != len(set(priorities)):
        raise _unprocessable("Provider priority cannot contain duplicates")
    settings = context.store.get_settings().model_copy(update=updates)
    context.store.save_settings(settings)
    return settings


@router.get("/data/export", response_model=PersonalAIExport)
def export_personal_ai_data(response: Response) -> PersonalAIExport:
    """Return an explicit in-memory download without writing an export file."""
    context = _api_context()
    conversations = context.store.list_conversations(
        limit=500,
        include_archived=True,
    )
    messages = [
        message
        for conversation in conversations
        for message in context.store.list_messages(conversation.conversation_id, limit=500)
    ]
    response.headers["Content-Disposition"] = (
        'attachment; filename="opencobalt-personal-ai-export.json"'
    )
    response.headers["Cache-Control"] = "no-store"
    return PersonalAIExport(
        exported_at=_now(),
        conversations=conversations,
        messages=messages,
        personas=list_personas(),
        routes=list_routes(limit=500),
        executions=[
            _execution_view(execution) for execution in context.store.list_executions(limit=500)
        ],
        memories=context.store.list_memory(limit=1000),
        skills=list_skills(),
        missions=list_missions(limit=500),
        receipts=list_receipts(limit=500),
        settings=context.store.get_settings(),
        provider_preferences=context.store.list_provider_preferences(),
    )


@router.get("/data/retention", response_model=RetentionLimitations)
def get_retention_limitations() -> RetentionLimitations:
    return RetentionLimitations(
        reason=(
            "Bulk and conversation deletion are unavailable because conversations can be "
            "linked to append-only routes, execution receipts, artifacts, approvals, and "
            "mission provenance. Curated memory can be deleted individually."
        )
    )


__all__ = ["APIContext", "_api_context", "_stream_ndjson", "router"]
