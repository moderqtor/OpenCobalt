"""Typed records for the personal-AI chat, route, and configuration domain."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


ControlLevel = Literal["very_low", "low", "balanced", "high", "very_high"]
MessageRole = Literal["user", "assistant", "system", "tool"]


class CommunicationControls(BaseModel):
    directness: ControlLevel = "high"
    warmth: ControlLevel = "balanced"
    formality: ControlLevel = "balanced"
    verbosity: ControlLevel = "balanced"
    challenge_level: ControlLevel = "balanced"
    emotional_attunement: ControlLevel = "balanced"
    speculation_tolerance: ControlLevel = "low"
    question_frequency: ControlLevel = "low"
    citation_preference: ControlLevel = "high"
    uncertainty_explicitness: ControlLevel = "high"


class ConversationManualPreset(BaseModel):
    """Last manual execution selections. Kept when routing mode is Automatic."""

    provider_id: str | None = None
    model_id: str | None = None

    @field_validator("provider_id", "model_id")
    @classmethod
    def _bounded_override(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            return None
        if len(clean) > 200 or clean.startswith("-"):
            raise ValueError("override identifier must be a bounded non-flag value")
        return clean


class ConversationRoutingSettings(BaseModel):
    """Durable per-conversation routing controls.

    Automatic mode and the last manual preset are independent. Switching to
    Automatic must not destroy provider/model selections for later restoration.
    Persona and cognitive policy are not stored here.
    """

    mode: Literal["automatic", "manual"] = "automatic"
    manual_preset: ConversationManualPreset = Field(default_factory=ConversationManualPreset)
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "medium"
    allow_fallback: bool = False
    privacy_mode: Literal["standard", "private", "sensitive"] = "standard"
    local_only: bool = False
    write_seq: int = Field(default=0, ge=0)


class Conversation(BaseModel):
    conversation_id: str = Field(default_factory=lambda: _uid("conv"))
    title: str = "New conversation"
    project_path: str | None = None
    archived: bool = False
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("conversation title cannot be blank")
        return clean[:200]


class ChatMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: _uid("msg"))
    conversation_id: str
    role: MessageRole
    content: str
    status: Literal["pending", "streaming", "complete", "failed", "cancelled"] = "complete"
    persona_version_id: str | None = None
    route_id: str | None = None
    parent_message_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def _content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message content cannot be blank")
        return value


class Persona(BaseModel):
    persona_id: str = Field(default_factory=lambda: _uid("per"))
    name: str
    description: str = ""
    built_in: bool = False
    active_version_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PersonaVersion(BaseModel):
    persona_version_id: str = Field(default_factory=lambda: _uid("pver"))
    persona_id: str
    version: int = Field(ge=1)
    controls: CommunicationControls = Field(default_factory=CommunicationControls)
    allowed_cognitive_policies: list[str] = Field(default_factory=list)
    provider_affinities: dict[str, int] = Field(default_factory=dict)
    custom_instructions: str = Field(default="", max_length=2000)
    native_provider_family: str | None = None
    created_at: datetime = Field(default_factory=_now)

    @field_validator("provider_affinities")
    @classmethod
    def _bounded_affinities(cls, value: dict[str, int]) -> dict[str, int]:
        if any(score < -10 or score > 10 for score in value.values()):
            raise ValueError("provider affinities must be between -10 and 10")
        return value


class AISettings(BaseModel):
    default_routing_mode: Literal["automatic", "manual"] = "automatic"
    default_persona_id: str = "analytical"
    local_only_default: bool = False
    privacy_policy: Literal["standard", "private", "sensitive"] = "standard"
    approval_policy: Literal["ask_for_risk", "always_ask", "deny_tools"] = "ask_for_risk"
    cost_ceiling_category: Literal["free", "low", "standard", "high"] = "standard"
    provider_priority: list[str] = Field(default_factory=list)
    memory_behavior: Literal["off", "propose", "explicit_only"] = "propose"
    skill_permissions: Literal["deny", "ask", "allow_builtin"] = "ask"
    verification_preference: Literal["minimal", "task_appropriate", "strict"] = (
        "task_appropriate"
    )
    theme: Literal["system", "dark", "light"] = "system"


class ProviderPreference(BaseModel):
    provider_id: str
    enabled: bool = True
    priority: int = 50
    cost_policy: Literal["free_only", "prefer_subscription", "allow_billed"] = (
        "prefer_subscription"
    )
    updated_at: datetime = Field(default_factory=_now)


class RouteRecord(BaseModel):
    route_id: str = Field(default_factory=lambda: _uid("route"))
    request_id: str
    conversation_id: str
    request_message_id: str
    task_class: str
    task_complexity: str = "moderate"
    selected_provider: str
    selected_model: str | None = None
    selected_runtime: str | None = None
    requested_persona_id: str
    requested_persona_version_id: str | None = None
    actual_persona_id: str
    actual_persona_version_id: str | None = None
    selected_tools: list[str] = Field(default_factory=list)
    selected_skills: list[str] = Field(default_factory=list)
    privacy_classification: str
    autonomy_level: str
    approval_requirements: list[str] = Field(default_factory=list)
    estimated_cost_category: str = "unknown"
    actual_usage: dict[str, Any] = Field(default_factory=dict)
    expected_latency_category: str = "unknown"
    route_score: int
    reasons: list[str] = Field(default_factory=list)
    fallback_events: list[dict[str, Any]] = Field(default_factory=list)
    verification_strategy: str = "response_integrity"
    persona_provider_mismatch: str | None = None
    outcome_status: str = "planned"
    receipt_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RouteCandidate(BaseModel):
    candidate_id: str = Field(default_factory=lambda: _uid("cand"))
    route_id: str
    provider_id: str
    model_id: str | None = None
    runtime_id: str | None = None
    rank: int = Field(ge=1)
    score: int
    score_components: dict[str, int] = Field(default_factory=dict)
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None
    created_at: datetime = Field(default_factory=_now)


class ChatExecution(BaseModel):
    execution_id: str = Field(default_factory=lambda: _uid("chatx"))
    request_id: str
    route_id: str
    conversation_id: str
    provider_id: str
    model_id: str | None = None
    status: Literal[
        "queued", "running", "complete", "failed", "cancel_requested", "cancelled"
    ] = "queued"
    provider_error_type: str | None = None
    provider_error_message: str | None = None
    work_receipt_id: str | None = None
    assistant_message_id: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class StreamEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: _uid("sev"))
    execution_id: str
    sequence: int = Field(ge=1)
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class MemoryEntry(BaseModel):
    memory_id: str = Field(default_factory=lambda: _uid("mem"))
    content: str
    source_type: str
    source_ref: str | None = None
    reason: str
    scope: Literal["user", "project", "conversation", "temporary"]
    status: Literal["proposed", "active", "rejected"] = "proposed"
    sensitivity: Literal["normal", "sensitive"] = "normal"
    pinned: bool = False
    conversation_id: str | None = None
    source_message_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillRecord(BaseModel):
    skill_id: str = Field(default_factory=lambda: _uid("skill"))
    name: str
    description: str
    source_kind: Literal["builtin", "user", "imported"]
    source_ref: str
    enabled: bool = True
    trust_level: Literal["builtin", "low", "meaningful", "high"] = "low"
    active_version_id: str | None = None
    requested_permissions: list[str] = Field(default_factory=list)
    compatibility: dict[str, Any] = Field(default_factory=dict)
    last_used_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class SkillVersion(BaseModel):
    skill_version_id: str = Field(default_factory=lambda: _uid("skver"))
    skill_id: str
    version: str
    content_hash: str
    manifest: dict[str, Any] = Field(default_factory=dict)
    install_path: str | None = None
    receipt_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
