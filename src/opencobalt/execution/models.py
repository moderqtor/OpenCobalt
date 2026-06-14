"""Pydantic schemas for Receipt-Backed Execution v0.

Every agent action leaves a verifiable receipt. These models describe the
full evidence chain: plan -> step -> result -> artifact -> receipt.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["green", "yellow", "red", "black"]
StepStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]
ExecutionStatus = Literal["succeeded", "failed", "timeout", "not_executed"]
VerificationStatus = Literal["unverified", "verified", "failed", "partial"]
VerifiabilityLevel = Literal[
    "full",
    "partial",
    "dry_run_only",
    "unavailable",
    "untrusted",
]
EnvironmentPolicy = Literal["minimal", "inherited_redacted", "none"]

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


def _stable_hash(payload: dict[str, Any] | list[Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RuntimeCapabilitySnapshot(BaseModel):
    """Normalized, descriptive capability evidence for one runtime adapter."""

    adapter_id: str
    adapter_name: str
    adapter_version: str | None = None
    executable_path: str | None = None
    available: bool = False
    capabilities: list[str] = Field(default_factory=list)
    supported_artifact_types: list[str] = Field(default_factory=list)
    supports_dry_run: bool = True
    supports_noninteractive: bool = False
    supports_json_output: bool = False
    requires_network: bool = False
    requires_credentials: bool = True
    max_safe_risk: RiskLevel = "green"
    limitations: list[str] = Field(default_factory=list)
    discovered_at: datetime = Field(default_factory=_now)
    snapshot_hash: str = ""
    verifiability_level: VerifiabilityLevel = "untrusted"
    capability_details: dict[str, Any] = Field(default_factory=dict)

    def with_hash(self) -> "RuntimeCapabilitySnapshot":
        payload = self.model_dump(
            mode="json",
            exclude={"snapshot_hash", "discovered_at"},
        )
        return self.model_copy(update={"snapshot_hash": _stable_hash(payload)})


class NormalizedInvocation(BaseModel):
    """The bounded command/action OpenCobalt intends to run."""

    invocation_id: str = Field(default_factory=_uid)
    adapter_id: str
    mission_id: str | None = None
    approval_id: str | None = None
    mission_step_id: str | None = None
    approval_step_id: str | None = None
    command_argv: list[str] = Field(default_factory=list)
    structured_action: dict[str, Any] = Field(default_factory=dict)
    cwd: str | None = None
    environment_policy: EnvironmentPolicy = "inherited_redacted"
    expected_artifacts: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "green"
    dry_run: bool = True
    timeout_seconds: int = 120
    created_at: datetime = Field(default_factory=_now)
    invocation_hash: str = ""

    def with_hash(self) -> "NormalizedInvocation":
        payload = self.model_dump(
            mode="json",
            exclude={"invocation_id", "created_at", "invocation_hash"},
        )
        return self.model_copy(update={"invocation_hash": _stable_hash(payload)})


class AdapterExecutionEvent(BaseModel):
    """Receipt-local view of one execution event."""

    event_id: str = Field(default_factory=_uid)
    invocation_id: str
    adapter_id: str
    event_type: str
    message: str
    payload_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class NormalizedAdapterReceipt(BaseModel):
    """Canonical adapter receipt view stored alongside legacy WorkReceipt fields."""

    receipt_id: str
    invocation_id: str
    adapter_id: str
    mission_id: str | None = None
    approval_id: str | None = None
    mission_step_id: str | None = None
    approval_step_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    exit_code: int | None = None
    status: str = "skipped"
    risk_level: RiskLevel = "green"
    command_hash: str = ""
    plan_hash: str = ""
    capability_snapshot_hash: str = ""
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    event_count: int = 0
    verification_status: VerificationStatus = "unverified"
    limitations: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    verifiability_level: VerifiabilityLevel = "dry_run_only"


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
    adapter_id: str | None = None
    capability_snapshot_hash: str | None = None
    normalized_invocation: NormalizedInvocation | None = None
    normalized_receipt: NormalizedAdapterReceipt | None = None
    adapter_events: list[AdapterExecutionEvent] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
