"""Normalized adapter receipt helpers.

This module is deliberately execution-local. It enriches the existing
ExecutionPlan, WorkReceipt, artifact, and event records instead of creating
a parallel receipt or provenance system.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import (
    AdapterExecutionEvent,
    ExecutionArtifact,
    ExecutionPlan,
    ExecutionResult,
    NormalizedAdapterReceipt,
    NormalizedInvocation,
    RuntimeCapabilitySnapshot,
    VerifiabilityLevel,
    VerificationStatus,
)
from .runner import redact_argv


def stable_hash(payload: dict[str, Any] | list[Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def command_hash(command_argv: list[str]) -> str:
    return stable_hash({"command_argv": command_argv})


def plan_hash(plan: ExecutionPlan) -> str:
    payload = plan.model_dump(mode="json", exclude={"created_at"})
    return stable_hash(payload)


def capability_snapshot_payload(
    raw_capabilities: dict[str, Any],
    snapshot: RuntimeCapabilitySnapshot,
) -> dict[str, Any]:
    """Preserve legacy flat capabilities and add a normalized envelope."""
    payload = dict(raw_capabilities)
    payload["normalized"] = snapshot.model_dump(mode="json")
    return payload


def build_invocation(
    *,
    adapter_id: str,
    command_argv: list[str],
    cwd: str | None,
    expected_artifacts: list[str],
    risk_level: str,
    dry_run: bool,
    timeout_seconds: int,
    mission_id: str | None = None,
    approval_id: str | None = None,
    mission_step_id: str | None = None,
    approval_step_id: str | None = None,
    structured_action: dict[str, Any] | None = None,
) -> NormalizedInvocation:
    return NormalizedInvocation(
        adapter_id=adapter_id,
        mission_id=mission_id,
        approval_id=approval_id,
        mission_step_id=mission_step_id,
        approval_step_id=approval_step_id,
        command_argv=redact_argv(command_argv),
        structured_action=structured_action or {},
        cwd=cwd,
        environment_policy="inherited_redacted",
        expected_artifacts=expected_artifacts,
        risk_level=risk_level,  # type: ignore[arg-type]
        dry_run=dry_run,
        timeout_seconds=timeout_seconds,
    ).with_hash()


def events_for_receipt(
    *,
    events: list[dict[str, Any]],
    invocation_id: str,
    adapter_id: str,
) -> list[AdapterExecutionEvent]:
    out: list[AdapterExecutionEvent] = []
    for event in events:
        out.append(
            AdapterExecutionEvent(
                event_id=event.get("id") or event.get("event_id") or "",
                invocation_id=invocation_id,
                adapter_id=adapter_id,
                event_type=event.get("event_type", "unknown"),
                message=event.get("message", ""),
                payload_json=event.get("metadata") or {},
                created_at=event.get("timestamp"),
            )
        )
    return out


def artifact_hashes(artifacts: list[ExecutionArtifact]) -> dict[str, str]:
    return {artifact.artifact_id: artifact.sha256 for artifact in artifacts}


def build_normalized_receipt(
    *,
    receipt_id: str,
    invocation: NormalizedInvocation,
    capability_snapshot: RuntimeCapabilitySnapshot,
    plan: ExecutionPlan,
    result: ExecutionResult | None,
    artifacts: list[ExecutionArtifact],
    verification_status: VerificationStatus,
    limitations: list[str],
    provenance_refs: list[str],
    event_count: int,
) -> NormalizedAdapterReceipt:
    hashes = artifact_hashes(artifacts)
    status = "skipped" if result is None else result.status
    level = _receipt_verifiability(
        capability_snapshot=capability_snapshot,
        dry_run=plan.dry_run,
        result=result,
        verification_status=verification_status,
        artifact_hashes=hashes,
        event_count=event_count,
    )
    return NormalizedAdapterReceipt(
        receipt_id=receipt_id,
        invocation_id=invocation.invocation_id,
        adapter_id=invocation.adapter_id,
        mission_id=invocation.mission_id,
        approval_id=invocation.approval_id,
        mission_step_id=invocation.mission_step_id,
        approval_step_id=invocation.approval_step_id,
        started_at=result.started_at if result else None,
        finished_at=result.finished_at if result else None,
        exit_code=result.return_code if result else None,
        status=status,
        risk_level=plan.risk_level,
        command_hash=command_hash(invocation.command_argv),
        plan_hash=plan_hash(plan),
        capability_snapshot_hash=capability_snapshot.snapshot_hash,
        artifact_hashes=hashes,
        event_count=event_count,
        verification_status=verification_status,
        limitations=limitations,
        provenance_refs=provenance_refs,
        verifiability_level=level,
    )


def normalized_snapshot_from_receipt(
    capabilities_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    normalized = capabilities_snapshot.get("normalized")
    return normalized if isinstance(normalized, dict) else None


def legacy_capability_names(capabilities_snapshot: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for name, detail in capabilities_snapshot.items():
        if name == "normalized":
            continue
        if isinstance(detail, dict) and detail.get("supported") is True:
            names.append(name)
        elif detail is True:
            names.append(name)
    return sorted(names)


def verify_normalized_integrity(receipt, artifacts: list[ExecutionArtifact]) -> bool:
    """Validate normalized hashes that can be recomputed locally."""
    if receipt.normalized_invocation is not None:
        if (
            receipt.normalized_invocation.with_hash().invocation_hash
            != receipt.normalized_invocation.invocation_hash
        ):
            return False
    if receipt.normalized_receipt is None:
        return True
    normalized = receipt.normalized_receipt
    if normalized.command_hash != command_hash(redact_argv(receipt.command_plan)):
        return False
    if receipt.capability_snapshot_hash:
        if normalized.capability_snapshot_hash != receipt.capability_snapshot_hash:
            return False
    hashes = artifact_hashes(artifacts)
    for artifact_id, expected in normalized.artifact_hashes.items():
        if hashes.get(artifact_id) != expected:
            return False
    return True


def _receipt_verifiability(
    *,
    capability_snapshot: RuntimeCapabilitySnapshot,
    dry_run: bool,
    result: ExecutionResult | None,
    verification_status: VerificationStatus,
    artifact_hashes: dict[str, str],
    event_count: int,
) -> VerifiabilityLevel:
    if not capability_snapshot.available:
        return "unavailable"
    if dry_run or result is None or result.status == "not_executed":
        return "dry_run_only"
    if capability_snapshot.verifiability_level in ("untrusted", "partial"):
        return capability_snapshot.verifiability_level
    if artifact_hashes and verification_status == "verified" and event_count > 0:
        return "full"
    if artifact_hashes:
        return "partial"
    return "untrusted"
