"""Pydantic schemas for Receipt-Backed Execution v0.

Every agent action leaves a verifiable receipt. These models describe the
full evidence chain: plan -> step -> result -> artifact -> receipt.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["green", "yellow", "red", "black"]
StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]
ExecutionStatus = Literal["succeeded", "failed", "timeout", "not_executed"]
VerificationStatus = Literal["unverified", "verified", "failed", "partial"]

ARTIFACT_TYPES = {
    "plan",
    "command_output",
    "stdout",
    "stderr",
    "report",
    "inspection_report",
    "diff",
    "test_output",
    "log",
    "screenshot",
    "browser_recording",
    "unknown",
}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


class ExecutionStep(BaseModel):
    step_id: str = Field(default_factory=_uid)
    runtime: str
    command_argv: list[str]
    description: str = ""
    risk_level: RiskLevel = "green"
    approval_required: bool = False
    timeout_seconds: int = 120
    status: StepStatus = "pending"
    created_at: datetime = Field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ExecutionPlan(BaseModel):
    plan_id: str = Field(default_factory=_uid)
    task: str
    runtime: str
    model_policy: str | None = None
    cwd: str | None = None
    risk_level: RiskLevel = "green"
    approval_required: bool = False
    steps: list[ExecutionStep] = Field(default_factory=list)
    dry_run: bool = True
    created_at: datetime = Field(default_factory=_now)


class ExecutionResult(BaseModel):
    execution_id: str = Field(default_factory=_uid)
    plan_id: str
    step_id: str | None = None
    runtime: str
    command_argv: list[str]
    cwd: str | None = None
    return_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    stdout_preview: str = ""
    stderr_preview: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    status: ExecutionStatus = "not_executed"
    error: str | None = None


class ExecutionArtifact(BaseModel):
    artifact_id: str = Field(default_factory=_uid)
    session_id: str | None = None
    plan_id: str | None = None
    execution_id: str | None = None
    source_runtime: str
    artifact_type: str = "unknown"
    path: str
    sha256: str
    size_bytes: int
    created_at: datetime = Field(default_factory=_now)
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkReceipt(BaseModel):
    receipt_id: str = Field(default_factory=_uid)
    plan_id: str
    execution_id: str | None = None
    task: str
    selected_runtime: str
    route_reason: str | None = None
    risk_level: RiskLevel = "green"
    approval_required: bool = False
    capabilities_snapshot: dict[str, Any] = Field(default_factory=dict)
    command_plan: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = "unverified"
    created_at: datetime = Field(default_factory=_now)
