"""Conversation-scoped routing presets stored in conversation metadata.

SQLite conversation rows remain the durable record. The browser is not the
source of truth. Unknown or ineligible providers are preserved, never replaced.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import (
    AISettings,
    ConversationManualPreset,
    ConversationRoutingSettings,
)

ROUTING_METADATA_KEY = "routing"

ProviderAvailability = Literal["unset", "available", "unavailable"]
ModelAvailability = Literal["unset", "unknown", "available", "unavailable"]


class ConversationRoutingView(BaseModel):
    """API view of stored routing plus live availability, without substitution."""

    conversation_id: str
    mode: Literal["automatic", "manual"]
    provider_id: str | None = None
    model_id: str | None = None
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] = "medium"
    allow_fallback: bool = False
    privacy_mode: Literal["standard", "private", "sensitive"] = "standard"
    local_only: bool = False
    provider_status: ProviderAvailability = "unset"
    provider_unavailable_reason: str | None = None
    model_status: ModelAvailability = "unset"
    model_unavailable_reason: str | None = None


class ConversationRoutingUpdate(BaseModel):
    """Partial update. Omitted fields keep their stored values."""

    mode: Literal["automatic", "manual"] | None = None
    provider_id: str | None = None
    model_id: str | None = None
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None
    allow_fallback: bool | None = None
    privacy_mode: Literal["standard", "private", "sensitive"] | None = None
    local_only: bool | None = None
    write_seq: int | None = Field(default=None, ge=1)


def default_conversation_routing(settings: AISettings | None = None) -> ConversationRoutingSettings:
    defaults = settings or AISettings()
    return ConversationRoutingSettings(
        mode=defaults.default_routing_mode,
        manual_preset=ConversationManualPreset(),
        reasoning_effort="medium",
        allow_fallback=False,
        privacy_mode=defaults.privacy_policy,
        local_only=bool(defaults.local_only_default),
    )


def parse_conversation_routing(
    metadata: dict[str, Any] | None,
    settings: AISettings | None = None,
) -> ConversationRoutingSettings:
    """Read stored routing. Missing or malformed records fall back to defaults."""
    defaults = default_conversation_routing(settings)
    raw = (metadata or {}).get(ROUTING_METADATA_KEY)
    if not isinstance(raw, dict):
        return defaults
    try:
        parsed = ConversationRoutingSettings.model_validate({**defaults.model_dump(), **raw})
    except (ValueError, TypeError):
        return defaults
    if parsed.manual_preset.provider_id:
        return parsed
    legacy_provider = raw.get("provider_id")
    legacy_model = raw.get("model_id")
    if isinstance(legacy_provider, str) or isinstance(legacy_model, str):
        return parsed.model_copy(
            update={
                "manual_preset": ConversationManualPreset(
                    provider_id=legacy_provider if isinstance(legacy_provider, str) else None,
                    model_id=legacy_model if isinstance(legacy_model, str) else None,
                )
            }
        )
    return parsed


def apply_routing_update(
    current: ConversationRoutingSettings,
    update: ConversationRoutingUpdate,
) -> ConversationRoutingSettings:
    """Apply a partial patch. Automatic mode keeps the last manual preset.

    Optional write_seq ignores an older in-flight patch so last user intent wins.
    """
    provided = update.model_fields_set
    if "write_seq" in provided and update.write_seq is not None:
        if update.write_seq <= current.write_seq:
            return current
        next_seq = update.write_seq
    else:
        next_seq = current.write_seq
    mode = update.mode if "mode" in provided and update.mode is not None else current.mode
    preset = current.manual_preset
    if "provider_id" in provided:
        preset = preset.model_copy(update={"provider_id": update.provider_id or None})
        if update.provider_id is None:
            preset = preset.model_copy(update={"model_id": None})
    if "model_id" in provided:
        preset = preset.model_copy(update={"model_id": update.model_id or None})
    if preset.model_id and not preset.provider_id:
        raise ValueError("model override requires a provider override")
    return ConversationRoutingSettings(
        mode=mode,
        manual_preset=preset,
        reasoning_effort=(
            update.reasoning_effort
            if "reasoning_effort" in provided and update.reasoning_effort is not None
            else current.reasoning_effort
        ),
        allow_fallback=(
            update.allow_fallback
            if "allow_fallback" in provided and update.allow_fallback is not None
            else current.allow_fallback
        ),
        privacy_mode=(
            update.privacy_mode
            if "privacy_mode" in provided and update.privacy_mode is not None
            else current.privacy_mode
        ),
        local_only=(
            update.local_only
            if "local_only" in provided and update.local_only is not None
            else current.local_only
        ),
        write_seq=next_seq,
    )


def routing_metadata_payload(routing: ConversationRoutingSettings) -> dict[str, Any]:
    return {ROUTING_METADATA_KEY: routing.model_dump(mode="json")}


def merge_routing_metadata(
    metadata: dict[str, Any] | None,
    routing: ConversationRoutingSettings,
) -> dict[str, Any]:
    merged = dict(metadata or {})
    merged[ROUTING_METADATA_KEY] = routing.model_dump(mode="json")
    return merged


def routing_view(
    conversation_id: str,
    routing: ConversationRoutingSettings,
    *,
    provider_status: ProviderAvailability = "unset",
    provider_unavailable_reason: str | None = None,
    model_status: ModelAvailability = "unset",
    model_unavailable_reason: str | None = None,
) -> ConversationRoutingView:
    return ConversationRoutingView(
        conversation_id=conversation_id,
        mode=routing.mode,
        provider_id=routing.manual_preset.provider_id,
        model_id=routing.manual_preset.model_id,
        reasoning_effort=routing.reasoning_effort,
        allow_fallback=routing.allow_fallback,
        privacy_mode=routing.privacy_mode,
        local_only=routing.local_only,
        provider_status=provider_status,
        provider_unavailable_reason=provider_unavailable_reason,
        model_status=model_status,
        model_unavailable_reason=model_unavailable_reason,
    )
