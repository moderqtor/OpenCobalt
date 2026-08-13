"""Process-local wait/notify for live human approvals.

ApprovalStore remains the durable source of truth. This module only coordinates
in-process waits so a provider runtime can pause, the UI can decide, and the
same live session can resume. It is provider-neutral: ACP is the first caller.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from opencobalt.execution.runner import redact_text

from .approval_bridge import (
    ApprovalBridge,
    ApprovalError,
    ApprovalRequest,
    ApprovalStep,
    BlockedStepError,
    StaleApprovalError,
)

DEFAULT_APPROVAL_WAIT_SECONDS = 240
_POLL_SECONDS = 0.25
_SENSITIVE_ARG_KEYS = (
    "token",
    "secret",
    "password",
    "credential",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "private_key",
)

LiveDecision = Literal["approved", "rejected", "expired", "stale", "cancelled"]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _safe_display_path(value: str | None, *, home: Path | None = None) -> str | None:
    if not value:
        return None
    text = redact_text(value)
    root = str((home or Path.home()).expanduser())
    if text.startswith(root):
        text = "<home>" + text[len(root) :]
    return text[:500]


def redact_arguments(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy structured arguments with credential-shaped values removed."""
    if not raw:
        return {}
    redacted: dict[str, Any] = {}
    for key, value in list(raw.items())[:40]:
        name = str(key)[:80]
        lowered = name.casefold()
        if any(marker in lowered for marker in _SENSITIVE_ARG_KEYS):
            redacted[name] = "<redacted>"
            continue
        if isinstance(value, str):
            redacted[name] = redact_text(value)[:500]
        elif isinstance(value, bool):
            redacted[name] = value
        elif isinstance(value, int) and not isinstance(value, bool):
            redacted[name] = value
        elif isinstance(value, list):
            redacted[name] = [
                redact_text(str(item))[:200] for item in value[:20] if item is not None
            ]
        elif isinstance(value, Mapping):
            redacted[name] = redact_arguments(value)
        else:
            redacted[name] = redact_text(str(value))[:200]
    return redacted


@dataclass
class LiveApprovalContext:
    """Caller-supplied linkage for one live permission request."""

    execution_id: str | None = None
    mission_id: str | None = None
    route_id: str | None = None
    conversation_id: str | None = None
    chat_request_id: str | None = None
    provider: str = ""
    runtime: str = ""
    provider_session_id: str | None = None
    capability_role: str | None = None
    repository_path: str | None = None


@dataclass
class LiveApprovalWaiter:
    event: threading.Event = field(default_factory=threading.Event)
    decision: LiveDecision | None = None
    decided_by: str | None = None
    reason: str = ""


class LiveApprovalCoordinator:
    """Bounded, cancellable waits for pending approvals in this process."""

    def __init__(
        self,
        bridge: ApprovalBridge,
        *,
        wait_seconds: int = DEFAULT_APPROVAL_WAIT_SECONDS,
    ) -> None:
        self.bridge = bridge
        self.wait_seconds = wait_seconds
        self._lock = threading.Lock()
        self._waiters: dict[str, LiveApprovalWaiter] = {}
        self._request_index: dict[str, str] = {}
        self._execution_index: dict[str, set[str]] = {}

    def has_live_pending(self, execution_id: str | None) -> bool:
        if not execution_id:
            return False
        with self._lock:
            return bool(self._execution_index.get(execution_id))

    def live_request_ids(self, execution_id: str | None = None) -> list[str]:
        with self._lock:
            if execution_id is None:
                return list(self._request_index)
            step_ids = self._execution_index.get(execution_id, set())
            return [
                request_id
                for request_id, step_id in self._request_index.items()
                if step_id in step_ids
            ]

    def register_waiter(
        self,
        request: ApprovalRequest,
        step: ApprovalStep,
        *,
        execution_id: str | None,
    ) -> LiveApprovalWaiter:
        waiter = LiveApprovalWaiter()
        with self._lock:
            self._waiters[step.step_id] = waiter
            self._request_index[request.request_id] = step.step_id
            if execution_id:
                self._execution_index.setdefault(execution_id, set()).add(step.step_id)
        return waiter

    def wait_for_decision(
        self,
        request: ApprovalRequest,
        step: ApprovalStep,
        *,
        timeout_seconds: int | None = None,
        cancelled: Callable[[], bool] | None = None,
        is_alive: Callable[[], bool] | None = None,
    ) -> LiveDecision:
        waiter = self._waiters.get(step.step_id)
        if waiter is None:
            waiter = self.register_waiter(
                request,
                step,
                execution_id=str(request.metadata.get("execution_id") or "") or None,
            )
        timeout = self.wait_seconds if timeout_seconds is None else timeout_seconds
        deadline = time.monotonic() + max(1, timeout)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._finish_wait(request.request_id, step.step_id, "expired")
                    self.bridge.mark_terminal(
                        request.request_id,
                        step_id=step.step_id,
                        state="expired",
                        reason="approval wait timed out",
                        decided_by="runtime",
                    )
                    return "expired"
                if cancelled is not None and cancelled():
                    self._finish_wait(request.request_id, step.step_id, "cancelled")
                    self.bridge.mark_terminal(
                        request.request_id,
                        step_id=step.step_id,
                        state="stale",
                        reason="execution cancelled while waiting for approval",
                        decided_by="cancellation",
                    )
                    return "cancelled"
                if is_alive is not None and not is_alive():
                    self._finish_wait(request.request_id, step.step_id, "stale")
                    self.bridge.mark_terminal(
                        request.request_id,
                        step_id=step.step_id,
                        state="stale",
                        reason="provider process ended while waiting for approval",
                        decided_by="runtime",
                    )
                    return "stale"
                if waiter.event.wait(timeout=min(_POLL_SECONDS, remaining)):
                    return waiter.decision or "stale"
        finally:
            self._drop_waiter(request.request_id, step.step_id)

    def decide(
        self,
        request_id: str,
        *,
        decision: Literal["approved", "rejected"],
        decided_by: str = "human",
        reason: str = "",
        require_live: bool = True,
    ) -> ApprovalStep:
        request = self.bridge.store.get_request(request_id)
        if request is None:
            raise KeyError(f"unknown approval request: {request_id}")
        step = request.steps[0] if request.steps else None
        if step is None:
            raise KeyError(f"approval {request_id} has no steps")
        if step.blocked and decision == "approved":
            raise BlockedStepError(
                f"step {step.step_id} is black-risk and cannot be approved"
            )
        with self._lock:
            waiter = self._waiters.get(step.step_id)
        if require_live and waiter is None:
            raise StaleApprovalError(
                "this approval is not waiting in a live provider session"
            )
        decided = self.bridge.decide_pending(
            request.request_id,
            decision=decision,
            step_id=step.step_id,
            decided_by=decided_by,
            reason=reason,
            decision_kind="allow_once" if decision == "approved" else "deny",
        )[0]
        if waiter is not None:
            waiter.decision = decision
            waiter.decided_by = decided_by
            waiter.reason = reason
            waiter.event.set()
        return decided

    def cancel_execution(self, execution_id: str) -> None:
        with self._lock:
            step_ids = list(self._execution_index.get(execution_id, set()))
            waiters = [(step_id, self._waiters.get(step_id)) for step_id in step_ids]
        for _step_id, waiter in waiters:
            if waiter is None or waiter.event.is_set():
                continue
            waiter.decision = "cancelled"
            waiter.decided_by = "cancellation"
            waiter.reason = "execution cancelled"
            waiter.event.set()

    def fail_execution(self, execution_id: str, *, reason: str) -> None:
        with self._lock:
            step_ids = list(self._execution_index.get(execution_id, set()))
        for step_id in step_ids:
            request_id = next(
                (
                    req_id
                    for req_id, indexed in self._request_index.items()
                    if indexed == step_id
                ),
                None,
            )
            if request_id is None:
                continue
            try:
                self.bridge.mark_terminal(
                    request_id,
                    step_id=step_id,
                    state="stale",
                    reason=reason,
                    decided_by="runtime",
                )
            except (KeyError, ApprovalError):
                continue
            with self._lock:
                waiter = self._waiters.get(step_id)
            if waiter is not None and not waiter.event.is_set():
                waiter.decision = "stale"
                waiter.decided_by = "runtime"
                waiter.reason = reason
                waiter.event.set()

    def mark_orphaned_acp_stale(self) -> int:
        """Convert persisted pending ACP approvals into stale after process start.

        Cursor ACP advertises loadSession: false, so a previous live wait cannot
        be resumed across an OpenCobalt restart.
        """
        changed = 0
        for request in self.bridge.store.list_requests(
            state="pending", source_type="acp_permission", limit=500
        ):
            marked = self.bridge.mark_terminal(
                request.request_id,
                state="stale",
                reason="OpenCobalt restarted; Cursor ACP cannot reload the session",
                decided_by="runtime",
            )
            changed += len(marked)
        return changed

    def public_view(
        self,
        request: ApprovalRequest,
        *,
        step: ApprovalStep | None = None,
        home: Path | None = None,
    ) -> dict[str, Any]:
        target = step or (request.steps[0] if request.steps else None)
        if target is None:
            raise KeyError(f"approval {request.request_id} has no steps")
        metadata = {**request.metadata, **target.metadata}
        live = False
        with self._lock:
            live = target.step_id in self._waiters
        path = _safe_display_path(
            str(metadata.get("affected_path") or "") or None, home=home
        )
        command = metadata.get("command")
        command_text = redact_text(str(command))[:300] if command else None
        headline = str(metadata.get("headline") or target.task or "Approval required")[:200]
        state = target.approval_state
        return {
            "request_id": request.request_id,
            "step_id": target.step_id,
            "state": state,
            "actionable": live and state == "pending",
            "decision": (
                "allow_once"
                if state == "approved"
                else "deny"
                if state == "rejected"
                else None
            ),
            "decision_source": metadata.get("decision_source"),
            "decision_kind": metadata.get("decision_kind"),
            "headline": headline,
            "summary": redact_text(str(metadata.get("summary") or target.task))[:400],
            "action": str(metadata.get("action_name") or metadata.get("kind") or "action")[:80],
            "category": str(metadata.get("action_category") or target.permission_scope)[:80],
            "risk_level": target.risk_level,
            "policy_classification": str(
                metadata.get("policy_classification") or "pending_human"
            )[:80],
            "path": path,
            "command": command_text,
            "arguments": metadata.get("arguments")
            if isinstance(metadata.get("arguments"), dict)
            else {},
            "provider": str(metadata.get("provider") or "")[:80] or None,
            "runtime": str(metadata.get("runtime") or "")[:80] or None,
            "capability_role": str(metadata.get("capability_role") or "")[:80] or None,
            "repository": _safe_display_path(
                str(metadata.get("repository_path") or "") or None, home=home
            ),
            "mission_id": metadata.get("mission_id"),
            "execution_id": metadata.get("execution_id"),
            "route_id": metadata.get("route_id"),
            "conversation_id": metadata.get("conversation_id"),
            "provider_session_id": metadata.get("provider_session_id"),
            "source_type": request.source_type,
            "changeset_id": metadata.get("changeset_id"),
            "created_at": target.created_at,
            "updated_at": target.updated_at,
            "expires_at": metadata.get("expires_at"),
            "provider_status": metadata.get("provider_status"),
        }

    def list_public(
        self,
        *,
        state: str | None = None,
        execution_id: str | None = None,
        mission_id: str | None = None,
        conversation_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        requests = self.bridge.store.list_requests(state=state, limit=max(limit, 100))
        views: list[dict[str, Any]] = []
        for request in requests:
            metadata = request.metadata
            if execution_id and metadata.get("execution_id") != execution_id:
                continue
            if mission_id and metadata.get("mission_id") != mission_id:
                continue
            if conversation_id and metadata.get("conversation_id") != conversation_id:
                continue
            for step in request.steps:
                views.append(self.public_view(request, step=step))
                if len(views) >= limit:
                    return views
        return views

    def _finish_wait(self, request_id: str, step_id: str, decision: LiveDecision) -> None:
        with self._lock:
            waiter = self._waiters.get(step_id)
        if waiter is not None and not waiter.event.is_set():
            waiter.decision = decision
            waiter.event.set()

    def _drop_waiter(self, request_id: str, step_id: str) -> None:
        with self._lock:
            self._waiters.pop(step_id, None)
            self._request_index.pop(request_id, None)
            for execution_id, step_ids in list(self._execution_index.items()):
                step_ids.discard(step_id)
                if not step_ids:
                    self._execution_index.pop(execution_id, None)


def approval_expiry_iso(wait_seconds: int) -> str:
    return _iso(_now() + timedelta(seconds=max(1, wait_seconds)))
