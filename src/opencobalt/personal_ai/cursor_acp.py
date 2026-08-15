"""Cursor ACP provider: coding-agent runtime over official stdio JSON-RPC.

OpenCobalt owns routing, approvals, missions, and receipts. This module only
speaks the documented Cursor ACP surface through ExecutionEngine.
"""

from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from opencobalt.core.approval_bridge import (
    ApprovalBridge,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStep,
    ApprovalStore,
)
from opencobalt.core.approval_runtime import (
    DEFAULT_APPROVAL_WAIT_SECONDS,
    LiveApprovalContext,
    LiveApprovalCoordinator,
    approval_expiry_iso,
    redact_arguments,
)
from opencobalt.execution.adapters import CommandOptions, CursorAdapter
from opencobalt.execution.models import RuntimeCapabilitySnapshot
from opencobalt.execution.runner import InteractiveSession, redact_text
from opencobalt.personal_ai.providers import (
    AuthenticationState,
    CancellationToken,
    EngineBackedChatProvider,
    ProviderCapabilities,
    ProviderError,
    ProviderEvent,
    ProviderHealth,
    ProviderHealthState,
    ProviderModel,
    ProviderModelCatalog,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
    ProviderToolEvent,
    ProviderUsage,
    _AdapterLike,
    _EngineLike,
    _events_from_result,
    _normalize_outcome,
    _pre_execution_error,
    _public_error_text,
    _routing_profile,
    _uid,
)

ACP_PROTOCOL_VERSION = 1
CURSOR_CLIENT_NAME = "opencobalt"
CURSOR_CLIENT_VERSION = "0.1.0"
ALLOWED_ACP_OPTIONS = frozenset({"allow-once", "reject-once"})
DANGEROUS_PERMISSION_MARKERS = (
    "force",
    "yolo",
    "dangerously",
    "allow-always",
    "approve-mcps",
    "production",
    "credential",
    "secret",
    "api key",
    "rm -rf",
    "drop table",
)
_SOURCE_PATH = re.compile(
    r"(?:^|[\s`])(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]{1,8}|(?:^|[\s`])[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|c|cc|cpp|h|md)"
)
_FORBIDDEN_REPOSITORY_ROOTS = frozenset(
    {
        Path("/"),
        Path("/Users"),
        Path("/home"),
        Path("/etc"),
        Path("/System"),
        Path("/usr"),
        Path("/bin"),
        Path("/sbin"),
        Path("/var"),
        Path("/private"),
        Path("/opt"),
        Path("/tmp"),
        Path("/private/tmp"),
        Path("/private/var"),
    }
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def validate_repository_path(project_path: str | None, *, workspace_root: Path | None = None) -> Path:
    """Require an explicit existing directory. Optional workspace_root bounds file paths."""
    if project_path is None or not str(project_path).strip():
        raise ValueError("coding requests require an explicit repository path")
    if "\x00" in project_path:
        raise ValueError("repository path must not contain a null byte")
    raw = Path(project_path)
    if ".." in raw.parts:
        raise ValueError("repository path must not contain traversal")
    try:
        resolved = raw.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError("repository path must be an existing directory") from exc
    if not resolved.is_dir():
        raise ValueError("repository path must be an existing directory")
    if workspace_root is not None:
        root = workspace_root.expanduser().resolve()
        if resolved != root and not resolved.is_relative_to(root):
            raise ValueError("path must stay within the attached repository")
    home = Path.home().expanduser().resolve()
    if resolved in _FORBIDDEN_REPOSITORY_ROOTS or resolved == home:
        raise ValueError("repository path is too broad to attach as a coding workspace")
    return resolved


def path_escapes_repository(path: str | None, repository: Path | None) -> bool:
    if path is None or repository is None:
        return False
    if "\x00" in path or ".." in Path(path).parts:
        return True
    try:
        candidate = Path(path)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (repository / candidate).resolve()
        )
    except (OSError, RuntimeError, ValueError):
        return True
    return resolved != repository and not resolved.is_relative_to(repository)


def permission_details(
    params: Mapping[str, Any],
    *,
    repository: Path | None = None,
) -> dict[str, Any]:
    """Normalize a documented ACP permission request into redacted display fields."""
    tool = params.get("toolCall") if isinstance(params.get("toolCall"), Mapping) else {}
    kind = str(tool.get("kind") or params.get("kind") or "other").casefold()[:40]
    title = str(tool.get("title") or params.get("title") or kind)[:200]
    raw_input = tool.get("rawInput") if isinstance(tool.get("rawInput"), Mapping) else {}
    if not raw_input and isinstance(params.get("rawInput"), Mapping):
        raw_input = params["rawInput"]
    path = None
    locations = tool.get("locations")
    if isinstance(locations, list):
        for location in locations:
            if isinstance(location, Mapping) and location.get("path"):
                path = str(location["path"])[:1024]
                break
    if path is None:
        for key in ("path", "file", "filePath", "target"):
            value = raw_input.get(key)
            if isinstance(value, str) and value.strip():
                path = value[:1024]
                break
    command = None
    for key in ("command", "cmd", "shellCommand"):
        value = raw_input.get(key)
        if isinstance(value, str) and value.strip():
            command = value[:500]
            break
    name = Path(path).name if path else None
    if kind in {"edit", "write", "move"} and name:
        headline = f"Cursor wants to modify {name}"
    elif kind == "delete" and name:
        headline = f"Cursor wants to delete {name}"
    elif kind in {"execute", "terminal"} and command:
        headline = f"Cursor wants to run {redact_text(command)[:120]}"
    elif kind == "read" and name:
        headline = f"Cursor wants to read {name}"
    else:
        headline = f"Cursor wants to {redact_text(title)[:120]}"
    return {
        "kind": kind,
        "title": redact_text(title),
        "headline": headline[:200],
        "affected_path": path,
        "command": redact_text(command) if command else None,
        "arguments": redact_arguments(raw_input),
        "path_escaped": path_escapes_repository(path, repository),
    }


def classify_permission_risk(
    params: Mapping[str, Any],
    *,
    mode: str,
    repository: Path | None = None,
) -> tuple[str, str]:
    """Return (risk_level, tool_summary) from a documented permission request."""
    details = permission_details(params, repository=repository)
    kind = details["kind"]
    summary = details["title"]
    blob = f"{kind} {summary} {details.get('command') or ''} {details.get('affected_path') or ''}".casefold()
    if details.get("path_escaped") or any(marker in blob for marker in DANGEROUS_PERMISSION_MARKERS):
        return "black", summary
    mutation_hint = any(
        token in blob
        for token in (
            "edit",
            "write",
            "delete",
            "move",
            "apply",
            "patch",
            "create",
            "overwrite",
            "unlink",
        )
    )
    execute_hint = kind in {"execute", "terminal"} or any(
        token in blob for token in ("terminal", "bash", "shell", "run ")
    )
    if mutation_hint and kind in {"read", "search", "think", "fetch", "other", ""}:
        kind = "execute" if execute_hint else "edit"
    if mode != "agent" and kind in {"edit", "delete", "move", "execute", "write"}:
        return "red", summary
    if kind in {"delete", "execute"} or execute_hint:
        return "red", summary
    if kind in {"edit", "move", "write"} or mutation_hint:
        return "yellow", summary
    if kind in {"read", "search", "think", "fetch"}:
        return "green", summary
    return "yellow", summary


def permission_option_id(
    params: Mapping[str, Any],
    *,
    allow: bool,
) -> str:
    options = params.get("options")
    offered: list[str] = []
    if isinstance(options, list):
        for item in options:
            if isinstance(item, Mapping) and isinstance(item.get("optionId"), str):
                offered.append(item["optionId"])
    wanted = "allow-once" if allow else "reject-once"
    if wanted in offered:
        return wanted
    if not allow:
        for fallback in ("reject-once", "reject_once", "reject"):
            if fallback in offered:
                return fallback
    if offered:
        raise ValueError("ACP permission options did not include a safe decision")
    return wanted


class AcpPermissionGate:
    """Map ACP session/request_permission onto OpenCobalt approvals."""

    def __init__(
        self,
        *,
        mode: str,
        bridge: ApprovalBridge | None = None,
        decision_hook: Callable[[ApprovalStep], str] | None = None,
        coordinator: LiveApprovalCoordinator | None = None,
        context: LiveApprovalContext | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
        repository: Path | None = None,
        wait_seconds: int = DEFAULT_APPROVAL_WAIT_SECONDS,
    ) -> None:
        self.mode = mode
        self.bridge = bridge or ApprovalBridge(policy=ApprovalPolicy(auto_approve_green=True))
        self.decision_hook = decision_hook
        self.coordinator = coordinator
        self.context = context or LiveApprovalContext()
        self.event_sink = event_sink
        self.repository = repository
        self.wait_seconds = wait_seconds
        self.records: list[dict[str, Any]] = []

    def decide(
        self,
        params: Mapping[str, Any],
        *,
        is_alive: Callable[[], bool] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        details = permission_details(params, repository=self.repository)
        risk, summary = classify_permission_risk(
            params, mode=self.mode, repository=self.repository
        )
        request = self._persist_request(
            params, risk=risk, summary=summary, details=details
        )
        step = request.steps[0]
        policy = "pending"
        allow = False
        if risk == "black" or (self.mode != "agent" and risk != "green"):
            self.bridge.reject(
                request.request_id,
                step_id=step.step_id,
                decided_by="policy",
                reason="dangerous or mutating ACP permission denied",
            )
            policy = "denied_by_policy"
        elif risk == "green" and self.bridge.policy.auto_approve_green:
            allow = True
            policy = "auto_approved_green"
        elif self.decision_hook is not None:
            hook_decision = self.decision_hook(step)
            if hook_decision == "approved":
                self.bridge.approve(
                    request.request_id,
                    step_id=step.step_id,
                    decided_by="human",
                    reason="explicit ACP permission approval",
                )
                allow = True
                policy = "approved_by_human"
            else:
                self.bridge.reject(
                    request.request_id,
                    step_id=step.step_id,
                    decided_by="human",
                    reason="ACP permission denied pending explicit approval",
                )
                policy = "rejected_by_human"
        elif self.coordinator is not None:
            self.coordinator.register_waiter(
                request, step, execution_id=self.context.execution_id
            )
            self._emit("approval_required", request, step, policy="pending_human")
            decision = self.coordinator.wait_for_decision(
                request,
                step,
                timeout_seconds=self.wait_seconds,
                cancelled=cancelled,
                is_alive=is_alive,
            )
            allow = decision == "approved"
            policy = {
                "approved": "approved_by_human",
                "rejected": "rejected_by_human",
                "expired": "expired",
                "cancelled": "cancelled",
            }.get(decision, "stale")
            self._emit(
                "approval_decided",
                request,
                step,
                policy=policy,
                decision=decision,
            )
        else:
            self.bridge.reject(
                request.request_id,
                step_id=step.step_id,
                decided_by="policy",
                reason="ACP permission denied pending explicit approval",
            )
            policy = "denied_missing_human"
        option_id = permission_option_id(params, allow=allow)
        if option_id not in ALLOWED_ACP_OPTIONS and allow:
            option_id = permission_option_id(params, allow=False)
            allow = False
            policy = "denied_by_policy"
        record = {
            "approval_request_id": request.request_id,
            "approval_step_id": step.step_id,
            "tool": summary,
            "headline": details["headline"],
            "risk_level": risk,
            "policy_decision": policy,
            "option_id": option_id,
            "path": details.get("affected_path"),
            "command": details.get("command"),
            "acp_response": {"outcome": {"outcome": "selected", "optionId": option_id}},
        }
        self.records.append(record)
        refreshed = self.bridge.store.get_request(request.request_id)
        if refreshed is not None:
            refreshed.metadata = {
                **refreshed.metadata,
                "acp_permission": record,
                "policy_classification": policy,
                "provider_status": option_id,
            }
            self.bridge.store.save_request(refreshed)
        return record["acp_response"]

    def _emit(
        self,
        event_type: str,
        request: ApprovalRequest,
        step: ApprovalStep,
        *,
        policy: str,
        decision: str | None = None,
    ) -> None:
        if self.event_sink is None or self.coordinator is None:
            return
        refreshed = self.bridge.store.get_request(request.request_id) or request
        view = self.coordinator.public_view(refreshed, step=step)
        view["policy_classification"] = policy
        if decision is not None:
            view["live_decision"] = decision
        self.event_sink({"event_type": event_type, "approval": view})

    def _persist_request(
        self,
        params: Mapping[str, Any],
        *,
        risk: str,
        summary: str,
        details: Mapping[str, Any],
    ) -> ApprovalRequest:
        auto_approved = (
            risk == "green"
            and self.bridge.policy.auto_approve_green
            and not details.get("path_escaped")
        )
        context = self.context
        request = ApprovalRequest(
            request_id=_uid("areq"),
            source_type="acp_permission",
            source_id=context.execution_id or _uid("acp"),
            run_id=context.execution_id or "acp",
            goal_id=context.chat_request_id or "acp",
            track_id=context.mission_id or "acp-permission",
            opportunity_plan_id=context.route_id or "acp-permission",
            goal_text=str(details.get("headline") or summary),
            track_name="ACP permission",
            risk_level=risk,
            metadata={
                "acp_params_keys": sorted(str(key) for key in params.keys())[:20],
                "execution_id": context.execution_id,
                "mission_id": context.mission_id,
                "route_id": context.route_id,
                "conversation_id": context.conversation_id,
                "provider": context.provider or "cursor",
                "runtime": context.runtime or "cursor",
                "provider_session_id": context.provider_session_id,
                "capability_role": context.capability_role,
                "repository_path": context.repository_path,
                "action_name": details.get("kind"),
                "action_category": details.get("kind"),
                "headline": details.get("headline"),
                "summary": summary,
                "affected_path": details.get("affected_path"),
                "command": details.get("command"),
                "arguments": details.get("arguments") or {},
                "expires_at": approval_expiry_iso(self.wait_seconds),
                "policy_classification": (
                    "auto_approved_green" if auto_approved else "pending_human"
                ),
            },
        )
        request.steps.append(
            ApprovalStep(
                step_id=_uid("astp"),
                request_id=request.request_id,
                source_type="acp_permission",
                source_id=request.source_id,
                task=str(details.get("headline") or summary),
                risk_level=risk,
                permission_scope="read" if risk == "green" else "write",
                approval_required=risk != "green",
                approval_state="approved" if auto_approved else "pending",
                metadata={
                    "auto_approved": auto_approved,
                    "blocked": risk == "black",
                    "kind": details.get("kind"),
                    "headline": details.get("headline"),
                    "affected_path": details.get("affected_path"),
                    "command": details.get("command"),
                    "arguments": details.get("arguments") or {},
                },
            )
        )
        request.refresh_state()
        self.bridge.store.save_request(request)
        return request


class AcpClient:
    """Newline-delimited JSON-RPC 2.0 client for documented Cursor ACP methods."""

    def __init__(
        self,
        session: InteractiveSession,
        *,
        cwd: str,
        mode: str,
        prompt: str,
        resume_session_id: str | None = None,
        permission_gate: AcpPermissionGate | None = None,
        cancellation: CancellationToken | None = None,
    ) -> None:
        self.session = session
        self.cwd = cwd
        self.mode = mode if mode in {"ask", "plan", "agent"} else "ask"
        self.prompt = prompt
        self.resume_session_id = resume_session_id
        self.permission_gate = permission_gate or AcpPermissionGate(mode=self.mode)
        self.cancellation = cancellation
        self._next_id = 1
        self._pending: dict[int, str] = {}
        self.events: list[dict[str, Any]] = []
        self.session_id: str | None = None
        self.content_parts: list[str] = []
        self.tool_events: list[ProviderToolEvent] = []
        self.usage: dict[str, Any] | None = None
        self.stop_reason: str | None = None
        self.model_id: str | None = None
        self.error: str | None = None
        self._load_session_supported = False

    def run_turn(self) -> dict[str, Any]:
        try:
            self._initialize()
            self._authenticate()
            self._open_session()
            self._prompt()
        except TimeoutError:
            self._cancel()
            self.error = "ACP session timed out"
        except ValueError as exc:
            self.error = _public_error_text(str(exc))
        if self.cancellation is not None and self.cancellation.cancelled:
            self._cancel()
            self.error = self.error or "request cancelled"
        status = "failed" if self.error else "complete"
        if self.error and "cancel" in self.error:
            status = "cancelled"
        return {
            "status": status,
            "content": "".join(self.content_parts),
            "session_id": self.session_id,
            "mode": self.mode,
            "model_id": self.model_id,
            "stop_reason": self.stop_reason,
            "error": self.error,
            "usage": self.usage,
            "tool_events": [event.model_dump(mode="json") for event in self.tool_events],
            "permissions": list(self.permission_gate.records),
            "events": self.events[:200],
        }

    def _initialize(self) -> None:
        result = self._request(
            "initialize",
            {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {"name": CURSOR_CLIENT_NAME, "version": CURSOR_CLIENT_VERSION},
            },
        )
        capabilities = result.get("agentCapabilities") if isinstance(result.get("agentCapabilities"), Mapping) else {}
        self._load_session_supported = bool(capabilities.get("loadSession"))
        agent_info = result.get("agentInfo") or result.get("clientInfo") or result.get("info") or {}
        if isinstance(agent_info, Mapping):
            version = agent_info.get("version")
            if isinstance(version, str):
                self.events.append({"event_type": "status", "summary": f"agent {version}"[:200]})

    def _authenticate(self) -> None:
        self._request("authenticate", {"methodId": "cursor_login"})

    def _open_session(self) -> None:
        if self.resume_session_id and self._load_session_supported:
            try:
                result = self._request(
                    "session/load",
                    {"sessionId": self.resume_session_id, "cwd": self.cwd, "mcpServers": []},
                )
                self.session_id = str(result.get("sessionId") or self.resume_session_id)
                return
            except ValueError:
                self.events.append(
                    {
                        "event_type": "status",
                        "summary": "ACP session/load failed; creating a new session",
                    }
                )
        result = self._request(
            "session/new",
            {"cwd": self.cwd, "mcpServers": [], "mode": self.mode},
        )
        session_id = result.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("ACP session/new did not return a session id")
        self.session_id = session_id

    def _prompt(self) -> None:
        if not self.session_id:
            raise ValueError("ACP session is not open")
        result = self._request(
            "session/prompt",
            {
                "sessionId": self.session_id,
                "prompt": [{"type": "text", "text": self.prompt}],
            },
        )
        self.stop_reason = str(result.get("stopReason") or "") or None
        model = result.get("model") or result.get("modelId")
        if isinstance(model, str):
            self.model_id = model

    def _cancel(self) -> None:
        if not self.session_id:
            return
        try:
            self.session.write_message(
                {
                    "jsonrpc": "2.0",
                    "method": "session/cancel",
                    "params": {"sessionId": self.session_id},
                }
            )
        except (RuntimeError, OSError):
            return

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._pending[request_id] = method
        self.session.write_message(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        while True:
            if self.cancellation is not None and self.cancellation.cancelled:
                raise ValueError("request cancelled")
            message = self.session.read_message()
            if message is None:
                if self.session.cancelled:
                    raise ValueError("request cancelled")
                continue
            handled = self._handle_incoming(message)
            if handled is not None and handled[0] == request_id:
                _method, payload = handled[0], handled[1]
                return payload

    def _handle_incoming(self, message: Mapping[str, Any]) -> tuple[int, dict[str, Any]] | None:
        if "error" in message and message.get("id") in self._pending:
            error = message.get("error")
            detail = error.get("message") if isinstance(error, Mapping) else error
            raise ValueError(_public_error_text(str(detail) or "ACP error"))
        if "result" in message and message.get("id") in self._pending:
            request_id = int(message["id"])
            self._pending.pop(request_id, None)
            result = message.get("result")
            return request_id, result if isinstance(result, dict) else {}
        method = message.get("method")
        if method == "session/update":
            self._handle_update(message.get("params") if isinstance(message.get("params"), Mapping) else {})
            return None
        if method == "session/request_permission":
            params = message.get("params") if isinstance(message.get("params"), Mapping) else {}
            response = self.permission_gate.decide(
                params,
                is_alive=lambda: getattr(self.session, "alive", True) is not False,
                cancelled=lambda: bool(
                    (self.cancellation is not None and self.cancellation.cancelled)
                    or self.session.cancelled
                ),
            )
            self._respond(message.get("id"), response)
            self.events.append(
                {
                    "event_type": "permission_requested",
                    "summary": (self.permission_gate.records[-1]["tool"] if self.permission_gate.records else "permission"),
                }
            )
            return None
        if method == "cursor/create_plan":
            params = message.get("params") if isinstance(message.get("params"), Mapping) else {}
            plan = str(params.get("plan") or params.get("overview") or "")[:4000]
            self.events.append({"event_type": "status", "summary": "plan received", "plan": plan})
            self._respond(
                message.get("id"),
                {"outcome": {"outcome": "rejected", "reason": "OpenCobalt does not auto-approve ACP plans"}},
            )
            return None
        if method == "cursor/ask_question":
            self._respond(
                message.get("id"),
                {"outcome": {"outcome": "skipped", "reason": "OpenCobalt has no ACP question UI"}},
            )
            return None
        if isinstance(method, str) and method.startswith("cursor/"):
            self.events.append({"event_type": "status", "summary": method})
            if message.get("id") is not None:
                self._respond(
                    message.get("id"),
                    {"outcome": {"outcome": "cancelled"}},
                )
            return None
        return None

    def _respond(self, request_id: Any, result: dict[str, Any]) -> None:
        if request_id is None:
            return
        self.session.write_message({"jsonrpc": "2.0", "id": request_id, "result": result})

    def _handle_update(self, params: Mapping[str, Any]) -> None:
        update = params.get("update") if isinstance(params.get("update"), Mapping) else params
        kind = str(update.get("sessionUpdate") or update.get("type") or "status")
        content = update.get("content") if isinstance(update.get("content"), Mapping) else {}
        text = content.get("text") if isinstance(content, Mapping) else None
        if kind == "agent_message_chunk" and isinstance(text, str):
            self.content_parts.append(text)
            self.events.append({"event_type": "text_delta", "chars": len(text)})
            return
        if kind in {"agent_thought_chunk", "reasoning"}:
            self.events.append({"event_type": "reasoning", "summary": "reasoning update"})
            return
        if kind in {"tool_call", "tool_call_update"}:
            tool_name = str(update.get("title") or update.get("kind") or "tool")[:80]
            status = str(update.get("status") or "unknown")
            event = ProviderToolEvent(
                tool_call_id=str(update.get("toolCallId") or _uid("tool"))[:80],
                tool_name=tool_name,
                status="complete" if status in {"completed", "complete"} else "unknown",
                summary=redact_text(tool_name),
            )
            if kind == "tool_call_update" and event.status == "complete":
                self.tool_events.append(event)
            summary_kind = "tool_started" if kind == "tool_call" else "tool_completed"
            if "read" in tool_name.casefold():
                summary_kind = "file_read"
            elif any(token in tool_name.casefold() for token in ("edit", "write", "apply")):
                summary_kind = "file_write"
            elif any(token in tool_name.casefold() for token in ("terminal", "bash", "shell")):
                summary_kind = "terminal"
            self.events.append({"event_type": summary_kind, "summary": event.summary})
            return
        if kind in {"usage", "usage_update"}:
            self.usage = {
                key: update.get(key)
                for key in ("inputTokens", "outputTokens", "totalTokens")
                if isinstance(update.get(key), int)
            } or self.usage
            self.events.append({"event_type": "usage"})
            return
        if "subagent" in kind.casefold() or kind == "cursor/task":
            self.events.append({"event_type": "subagent", "summary": kind[:80]})
            return
        self.events.append({"event_type": "status", "summary": kind[:80]})


class CursorACPRuntimeAdapter:
    """Execution adapter whose only command is `agent acp`."""

    runtime_id = "cursor"
    display_name = "Cursor ACP"
    executable = "agent"
    requires_network = True
    requires_credentials = True
    max_safe_risk = "yellow"
    isolates_answer_only_inference = False

    def __init__(self, cursor: CursorAdapter | None = None) -> None:
        self._cursor = cursor or CursorAdapter()
        self.executable = self._cursor._agent_cli() or "agent"

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        snapshot = self._cursor.discover_capabilities()
        available = self._cursor.supports_acp()
        limitations = list(snapshot.limitations)
        if not available:
            limitations.append("Cursor ACP server was not discovered")
        return snapshot.model_copy(
            update={
                "available": snapshot.available and available,
                "supports_noninteractive": available,
                "limitations": limitations,
            }
        )

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        _ = task
        opts = options or CommandOptions()
        if opts.dangerously_skip_permissions or opts.allow_dangerously_skip_permissions:
            raise ValueError("Cursor ACP does not support unsafe permission bypass")
        argv = self._cursor.build_acp_command()
        forbidden = {"--force", "--yolo", "--api-key", "--approve-mcps", "--cloud", "--browser"}
        if forbidden.intersection(argv):
            raise ValueError("Cursor ACP command included a forbidden flag")
        return argv

    def supports_non_interactive(self) -> bool:
        return self._cursor.supports_acp()

    def default_timeout_seconds(self) -> int:
        return 600

    def risk_for_task(self, task: str) -> str:
        _ = task
        return "yellow"


class CursorACPProvider(EngineBackedChatProvider):
    """First-class coding runtime. Not a general Chat provider."""

    def __init__(
        self,
        engine: _EngineLike,
        adapter: CursorAdapter | _AdapterLike,
        *,
        permission_hook: Callable[[ApprovalStep], str] | None = None,
        approval_store: ApprovalStore | None = None,
        coordinator: LiveApprovalCoordinator | None = None,
        store: Any | None = None,
        staging_root: Path | None = None,
    ) -> None:
        cursor = adapter if isinstance(adapter, CursorAdapter) else CursorAdapter()
        runtime = CursorACPRuntimeAdapter(cursor)
        super().__init__(
            provider_id="cursor",
            display_name="Cursor ACP",
            engine=engine,
            adapter=runtime,
            supports_model_discovery=False,
            routing_profile=_routing_profile("cursor"),
        )
        self._cursor = cursor
        self.permission_hook = permission_hook
        self.approval_store = approval_store
        self.coordinator = coordinator
        self.store = store
        self.staging_root = staging_root
        self._approval_event_sink: Callable[[dict[str, Any]], None] | None = None

    def status(self) -> ProviderStatus:
        snapshot = self.adapter.discover_capabilities()
        acp = self._cursor.supports_acp()
        installed = snapshot.available or self._cursor._display_path() is not None
        auth = self._cursor.authentication_state()
        authentication: AuthenticationState = (
            "verified" if auth == "verified" else "unknown"
        )
        health: ProviderHealthState = "ready" if acp and authentication == "verified" else (
            "unknown" if installed else "unavailable"
        )
        limitations = [_public_error_text(item) for item in snapshot.limitations]
        limitations.append(
            "Cursor is a coding runtime; ordinary Chat does not grant repository mutation"
        )
        return ProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            runtime_id="cursor",
            installed=installed,
            authentication=authentication,
            health=health,
            execution_supported=acp,
            capabilities=ProviderCapabilities(
                completion=acp,
                streaming="completion_only" if acp else "none",
                cancellation="normalized_stream_only" if acp else "none",
                model_discovery=False,
                usage_reporting=True,
                receipt_linkage=acp,
                local_only_eligible=False,
                requires_network=True,
                answer_only_isolation=False,
                acp=acp,
                coding_analysis=acp,
                coding_agent=acp,
            ),
            routing_profile=self.routing_profile.model_copy(deep=True),
            limitations=list(dict.fromkeys(limitations)),
        )

    def health(self) -> ProviderHealth:
        status = self.status()
        return ProviderHealth(
            provider_id=status.provider_id,
            state=status.health,
            authentication=status.authentication,
            evidence="capability_snapshot",
            successful_invocation_proven=False,
            limitations=list(status.limitations),
        )

    def discover_models(
        self, *, local_only: bool = False, refresh: bool = False
    ) -> ProviderModelCatalog:
        _ = refresh
        if local_only:
            return ProviderModelCatalog(
                provider_id=self.provider_id,
                limitations=["Cursor ACP is not local-only eligible"],
            )
        status = self.status()
        if not status.execution_supported:
            return ProviderModelCatalog(
                provider_id=self.provider_id,
                error=ProviderError(
                    category="unavailable",
                    message="Cursor ACP server was not discovered",
                ),
                limitations=list(status.limitations),
            )
        return ProviderModelCatalog(
            provider_id=self.provider_id,
            models=[
                ProviderModel(
                    provider_id=self.provider_id,
                    model_id="cursor-acp",
                    display_name="Cursor ACP session model",
                    source="builtin",
                    execution_location="remote",
                    locality_evidence=["cursor_acp_authenticated_cli"],
                    available=True,
                    quality_tier="strong",
                    cost_category="standard",
                    latency_category="standard",
                    family="cursor",
                    profile_evidence="cursor_acp_runtime_v1",
                    tool_names=["read", "edit", "terminal"],
                )
            ],
            limitations=[
                "Cursor ACP does not expose a stable model catalog through OpenCobalt",
            ],
        )

    def execute(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> ProviderResult:
        if cancellation is not None and cancellation.cancelled:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="cancelled",
                message="request cancelled before execution",
                status="cancelled",
            )
        if request.local_only:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="local_only_violation",
                message="Cursor ACP is not eligible for local-only execution",
                status="blocked",
            )
        status = self.status()
        if not status.installed:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="unavailable",
                message="Cursor ACP executable is unavailable",
                status="unavailable",
            )
        if not status.execution_supported:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="execution_unsupported",
                message="Cursor ACP server was not discovered",
                status="unavailable",
            )
        role = str(request.metadata.get("capability_role") or "coding_analysis")
        if role == "coding_agent" and str(request.metadata.get("chat_surface") or "") == "general_chat":
            return _pre_execution_error(
                request,
                self.provider_id,
                category="policy_denied",
                message="ordinary Chat cannot grant Cursor repository mutation permissions",
                status="blocked",
            )
        try:
            repo = validate_repository_path(request.cwd)
        except ValueError as exc:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="invalid_request",
                message=str(exc),
                status="blocked",
            )
        mode = "agent" if role == "coding_agent" else "ask"
        workspace: dict[str, Any] | None = None
        provider_cwd = repo
        if role == "coding_agent":
            from opencobalt.personal_ai.staging import StagingController, StagingError

            controller = StagingController(
                self._personal_store(),
                staging_root=self._staging_root(),
                approval_store=self.approval_store,
            )
            try:
                workspace = controller.create_workspace(
                    repo,
                    coding_id=str(request.metadata.get("coding_mission_id") or "") or None,
                    mission_id=str(request.metadata.get("mission_id") or "") or None,
                    execution_id=str(request.metadata.get("execution_id") or "") or None,
                    provider_id=self.provider_id,
                )
            except (StagingError, ValueError, OSError) as exc:
                return _pre_execution_error(
                    request,
                    self.provider_id,
                    category="invalid_request",
                    message=_public_error_text(str(exc)),
                    status="blocked",
                )
            provider_cwd = Path(workspace["staging_path"])
        context = LiveApprovalContext(
            execution_id=str(request.metadata.get("execution_id") or "") or None,
            mission_id=str(request.metadata.get("mission_id") or "") or None,
            route_id=str(request.metadata.get("route_id") or "") or None,
            conversation_id=request.conversation_id,
            chat_request_id=request.request_id,
            provider="cursor",
            runtime="cursor",
            provider_session_id=str(request.metadata.get("acp_session_id") or "") or None,
            capability_role=role,
            repository_path=str(repo),
        )
        event_sink = self._approval_event_sink
        gate = AcpPermissionGate(
            mode=mode,
            bridge=ApprovalBridge(
                store=self.approval_store,
                policy=ApprovalPolicy(auto_approve_green=True),
            ),
            decision_hook=self.permission_hook,
            coordinator=self.coordinator,
            context=context,
            event_sink=event_sink,
            repository=provider_cwd,
        )

        def handler(session: InteractiveSession) -> dict[str, Any]:
            client = AcpClient(
                session,
                cwd=str(provider_cwd),
                mode=mode,
                prompt=request.message,
                resume_session_id=(
                    str(request.metadata["acp_session_id"])
                    if request.metadata.get("acp_session_id")
                    else None
                ),
                permission_gate=gate,
                cancellation=cancellation,
            )
            return client.run_turn()

        auth_before = snapshot_repository(repo)
        stage_before = snapshot_repository(provider_cwd)
        try:
            outcome = self.engine.run_task(
                request.message,
                runtime="cursor",
                model=request.model_id,
                execute=True,
                approved=False,
                timeout_seconds=max(request.timeout_seconds, 600),
                cwd=str(provider_cwd),
                unsafe_skip_permissions=False,
                execution_context="general_task",
                adapter=self.adapter,
                session_handler=handler,
                mission_id=str(request.metadata.get("mission_id") or "") or None,
            )
        except (KeyError, ValueError, AttributeError) as exc:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="configuration",
                message=_public_error_text(str(exc)),
                status="failed",
            )
        result = _normalize_outcome(
            request=request,
            provider_id=self.provider_id,
            model_id=request.model_id,
            outcome=outcome,
        )
        parsed = parse_cursor_acp_payload(_engine_output(outcome))
        result.content = parsed.get("content") or result.content
        result.session_id = parsed.get("session_id") or result.session_id
        if parsed.get("model_id"):
            result.model_id = str(parsed["model_id"])
        if parsed.get("tool_events"):
            result.tool_events = [
                ProviderToolEvent.model_validate(item) for item in parsed["tool_events"]
            ]
        if parsed.get("usage"):
            result.usage = _usage_from_acp(parsed["usage"])
        permissions = [
            item
            for item in parsed.get("permissions", [])
            if isinstance(item, Mapping)
        ]
        if permissions:
            result.metadata = {**result.metadata, "acp_permissions": permissions}
        if parsed.get("error") and result.status == "complete":
            result.status = "cancelled" if "cancel" in str(parsed["error"]) else "failed"
            result.error = ProviderError(
                category="cancelled" if result.status == "cancelled" else "provider_error",
                message=_public_error_text(str(parsed["error"])),
            )
        denied = [
            item
            for item in parsed.get("permissions", [])
            if isinstance(item, Mapping) and str(item.get("option_id")) == "reject-once"
        ]
        if denied and role == "coding_agent" and result.status == "complete":
            result.limitations.append("one or more ACP permissions were denied")
        auth_after = snapshot_repository(repo)
        auth_mutated = changed_paths(auth_before, auth_after)
        stage_after = snapshot_repository(provider_cwd)
        staged_mutated = changed_paths(stage_before, stage_after)
        if role == "coding_agent" and workspace is not None:
            from opencobalt.personal_ai.staging import CONTAINMENT_LIMITATION, StagingController

            if auth_mutated:
                result.limitations.append(
                    "Provider mutated the authoritative repository despite staged execution"
                )
                result.metadata = {**result.metadata, "containment_escape": auth_mutated}
            result.limitations.append(CONTAINMENT_LIMITATION)
            controller = StagingController(
                self._personal_store(),
                staging_root=self._staging_root(),
                approval_store=self.approval_store,
            )
            reported_tests = [
                str(event.summary)
                for event in result.tool_events
                if "test" in str(event.summary).casefold() or "pytest" in str(event.summary).casefold()
            ]
            changeset = controller.generate_changeset(
                workspace,
                provider_id=self.provider_id,
                runtime="cursor",
                coding_id=str(request.metadata.get("coding_mission_id") or "") or None,
                mission_id=str(request.metadata.get("mission_id") or "") or None,
                execution_id=str(request.metadata.get("execution_id") or "") or None,
                tests=reported_tests,
                limitations=list(result.limitations),
                run_verification=True,
            )
            if changeset.promotion_state == "pending":
                controller.create_promotion_request(changeset)
            result.metadata = {
                **result.metadata,
                "files_changed": [item.path for item in changeset.files],
                "changeset": changeset.public_view(),
                "workspace_id": workspace["workspace_id"],
                "staged_files_changed": staged_mutated,
            }
            if staged_mutated and not any(
                isinstance(item, Mapping) and str(item.get("option_id")) == "allow-once"
                and str(item.get("risk_level") or "") != "green"
                for item in permissions
            ):
                result.limitations.append(
                    "Cursor changed staged files without an ACP permission request"
                )
        elif staged_mutated:
            result.metadata = {**result.metadata, "files_changed": staged_mutated}
            allowed_writes = [
                item
                for item in permissions
                if isinstance(item, Mapping) and str(item.get("option_id")) == "allow-once"
                and str(item.get("risk_level") or "") != "green"
            ]
            if not allowed_writes:
                result.limitations.append(
                    "Cursor changed repository files without an ACP permission request"
                )
            if role == "coding_analysis":
                result.limitations.append(
                    "coding_analysis is non-mutating; unexpected repository writes were recorded and not promoted"
                )
        if result.receipt_id:
            store = getattr(self.engine, "store", None)
            getter = getattr(store, "get_receipt", None)
            saver = getattr(store, "save_receipt", None)
            if callable(getter) and callable(saver):
                receipt = getter(result.receipt_id)
                if receipt is not None:
                    extra = [
                        f"approval:{item.get('approval_request_id')}"
                        for item in permissions
                        if isinstance(item.get("approval_request_id"), str)
                    ]
                    changeset = result.metadata.get("changeset")
                    if isinstance(changeset, Mapping):
                        if changeset.get("changeset_id"):
                            extra.append(f"changeset:{changeset['changeset_id']}")
                        if changeset.get("workspace_id"):
                            extra.append(f"workspace:{changeset['workspace_id']}")
                        if changeset.get("starting_head"):
                            extra.append(f"head:{changeset['starting_head']}")
                        if changeset.get("promotion_request_id"):
                            extra.append(f"promotion:{changeset['promotion_request_id']}")
                        extra.append("containment:staged_workspace")
                    receipt.provenance_refs = list(
                        dict.fromkeys([*list(receipt.provenance_refs or []), *extra])
                    )
                    limitations = list(receipt.limitations or [])
                    for item in result.limitations:
                        if item and item not in limitations:
                            limitations.append(item)
                    receipt.limitations = limitations
                    saver(receipt)
        return result

    def _personal_store(self) -> Any | None:
        if self.store is not None:
            return self.store
        db_path = getattr(getattr(self.engine, "store", None), "db_path", None)
        if db_path is None:
            return None
        from opencobalt.personal_ai.store import PersonalAIStore

        self.store = PersonalAIStore(Path(db_path))
        return self.store

    def _staging_root(self) -> Path:
        if self.staging_root is not None:
            return Path(self.staging_root)
        db_path = getattr(getattr(self.engine, "store", None), "db_path", None)
        if db_path is not None:
            return Path(db_path).parent / "staging"
        return Path(".opencobalt").resolve() / "staging"

    def stream(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[ProviderEvent]:
        events: queue.Queue[ProviderEvent | None] = queue.Queue()
        sequence = 1

        def sink(payload: dict[str, Any]) -> None:
            nonlocal sequence
            event_type = payload.get("event_type")
            if event_type not in {"approval_required", "approval_decided"}:
                return
            events.put(
                ProviderEvent(
                    request_id=request.request_id,
                    provider_id=self.provider_id,
                    sequence=sequence,
                    event_type=event_type,
                    metadata={"approval": payload.get("approval") or {}},
                )
            )
            sequence += 1

        holder: dict[str, Any] = {}

        def run() -> None:
            self._approval_event_sink = sink
            try:
                holder["result"] = self.execute(request, cancellation)
            except Exception as exc:  # provider boundary must stay inspectable
                holder["error"] = exc
            finally:
                self._approval_event_sink = None
                events.put(None)

        worker = threading.Thread(target=run, name="cursor-acp-execute", daemon=True)
        worker.start()
        while True:
            item = events.get()
            if item is None:
                break
            yield item
        worker.join(timeout=5)
        error = holder.get("error")
        if isinstance(error, Exception):
            raise error
        result = holder.get("result")
        if result is None:
            yield ProviderEvent(
                request_id=request.request_id,
                provider_id=self.provider_id,
                sequence=sequence,
                event_type="error",
                error=ProviderError(
                    category="provider_error",
                    message="Cursor ACP execution ended without a result",
                ),
            )
            return
        yield from _events_from_result(result, cancellation, chunk_size=64)


def parse_cursor_acp_payload(raw_content: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return {"content": raw_content, "permissions": [], "tool_events": []}
    if not isinstance(payload, dict):
        return {"content": raw_content, "permissions": [], "tool_events": []}
    return payload


def _engine_output(outcome: Any) -> str:
    result = getattr(outcome, "result", None)
    if result is None:
        return ""
    direct = getattr(result, "content", "")
    if direct:
        return str(direct)
    path = getattr(result, "stdout_path", None)
    if path:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")[:200_000]
        except OSError:
            return ""
    return str(getattr(result, "stdout_preview", "") or "")


def _usage_from_acp(raw: Mapping[str, Any]) -> ProviderUsage:
    input_tokens = raw.get("inputTokens") if isinstance(raw.get("inputTokens"), int) else raw.get("input_tokens")
    output_tokens = raw.get("outputTokens") if isinstance(raw.get("outputTokens"), int) else raw.get("output_tokens")
    total_tokens = raw.get("totalTokens") if isinstance(raw.get("totalTokens"), int) else raw.get("total_tokens")
    return ProviderUsage(
        input_tokens=input_tokens if isinstance(input_tokens, int) else None,
        output_tokens=output_tokens if isinstance(output_tokens, int) else None,
        total_tokens=total_tokens if isinstance(total_tokens, int) else None,
        source="provider_reported" if any(
            isinstance(value, int) for value in (input_tokens, output_tokens, total_tokens)
        ) else "unavailable",
    )


def looks_like_source_path(text: str) -> bool:
    return _SOURCE_PATH.search(text) is not None


def snapshot_repository(root: Path, *, limit: int = 200) -> dict[str, str]:
    """Bounded relative-path digest map for detecting unsolicited mutations."""
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if len(snapshot) >= limit:
            break
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in {".git", "__pycache__", "node_modules", ".venv"} for part in relative.parts):
            continue
        try:
            if path.stat().st_size > 256_000:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        snapshot[str(relative)] = digest
    return snapshot


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = sorted(set(before) | set(after))
    return [path for path in paths if before.get(path) != after.get(path)]
