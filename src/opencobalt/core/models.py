"""Pydantic schemas for all OpenCobalt domain objects."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


class SessionEvent(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    project: str
    source: str
    event_type: str
    summary: str
    raw_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolRun(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    session_id: str
    tool: str
    command: str
    exit_code: int | None = None
    duration_seconds: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextPack(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    project: str
    sources: list[str] = Field(default_factory=list)
    content: str
    token_estimate: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentProfile(BaseModel):
    agent_id: str
    name: str
    tier: Literal["executive", "manager", "worker"]
    capabilities: list[str] = Field(default_factory=list)
    task_types: list[str] = Field(default_factory=list)
    requires_api_key: bool = False
    local_only: bool = False


class RouteDecision(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    task: str
    recommended_tool: str
    score: int
    reasoning: str
    tier: Literal["executive", "manager", "worker"]
    scores: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    command: str
    exit_code: int
    passed: bool
    output_summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    project: str
    namespace: str
    content: str
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DesignBrief(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    project: str
    description: str
    design_tokens: dict[str, str] = Field(default_factory=dict)
    anti_slop_rules: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubTask(BaseModel):
    id: str = Field(default_factory=_uid)
    task_type: str
    prompt: str
    preferred_tool: str
    preferred_agent: str | None = None


class OrchestrationResult(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    task: str
    subtasks: list[SubTask]
    outputs: dict[str, str] = Field(default_factory=dict)
    synthesis: str = ""
    elapsed_s: float = 0.0
    success: bool = False
    errors: list[str] = Field(default_factory=list)


class MultiRouteDecision(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    task: str
    subtasks: list[SubTask]
    tools_used: list[str] = Field(default_factory=list)
    result_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
