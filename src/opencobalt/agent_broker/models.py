"""Typed durable state for external agent sessions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

BrokerStatus = Literal["planned", "active", "stopped", "failed"]
TurnStatus = Literal["planned", "complete", "failed"]
RelayStatus = Literal["processing", "result_pending", "complete", "failed", "ignored"]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


class AgentBrokerSession(BaseModel):
    """OpenCobalt-owned state for one resumable external-agent thread."""

    session_id: str = Field(default_factory=lambda: _uid("agent"))
    runtime: str = "codex-sdk"
    provider_session_id: str | None = None
    objective: str
    repository_path: str
    workspace_id: str
    workspace_path: str
    source_branch: str | None = None
    starting_head: str | None = None
    model: str | None = None
    status: BrokerStatus = "planned"
    turn_count: int = 0
    last_prompt: str | None = None
    last_response: str | None = None
    last_receipt_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentBrokerTurn(BaseModel):
    """One receipt-linked turn inside a durable broker session."""

    turn_id: str = Field(default_factory=lambda: _uid("agent-turn"))
    session_id: str
    sequence: int = Field(ge=1)
    prompt: str
    response: str = ""
    provider_session_id: str | None = None
    receipt_id: str | None = None
    status: TurnStatus = "planned"
    created_at: datetime = Field(default_factory=_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRelayEvent(BaseModel):
    """One deduplicated command/result exchange on an external relay channel."""

    relay_event_id: str = Field(default_factory=lambda: _uid("relay"))
    repository: str
    issue_number: int = Field(gt=0)
    source_comment_id: int = Field(gt=0)
    command_id: str
    author: str
    action: str
    session_id: str | None = None
    receipt_id: str | None = None
    result_comment_id: int | None = None
    status: RelayStatus = "processing"
    command_json: dict[str, Any] = Field(default_factory=dict)
    result_json: dict[str, Any] = Field(default_factory=dict)
    result_body: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
