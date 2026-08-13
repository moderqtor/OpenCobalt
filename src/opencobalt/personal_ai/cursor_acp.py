"""Cursor ACP provider: coding-agent runtime over official stdio JSON-RPC.

OpenCobalt owns routing, approvals, missions, and receipts. This module only
speaks the documented Cursor ACP surface through ExecutionEngine.
"""

from __future__ import annotations

import json
import re
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


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def validate_repository_path(project_path: str | None, *, workspace_root: Path | None = None) -> Path:
    """Require an explicit existing directory that cannot escape the workspace."""
    if project_path is None or not str(project_path).strip():
        raise ValueError("coding requests require an explicit repository path")
    if "\x00" in project_path or ".." in Path(project_path).parts:
        raise ValueError("repository path must not contain traversal")
    root = (workspace_root or Path.cwd()).expanduser().resolve()
    try:
        resolved = Path(project_path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError("repository path must be an existing directory") from exc
    if not resolved.is_dir():
        raise ValueError("repository path must be an existing directory")
    if resolved != root and not resolved.is_relative_to(root):
        raise ValueError("repository path must stay within the current workspace root")
    return resolved


def classify_permission_risk(
    params: Mapping[str, Any],
    *,
    mode: str,
) -> tuple[str, str]:
    """Return (risk_level, tool_summary) from a documented permission request."""
    tool = params.get("toolCall") if isinstance(params.get("toolCall"), Mapping) else {}
    kind = str(tool.get("kind") or params.get("kind") or "other").casefold()
    title = str(tool.get("title") or params.get("title") or kind)[:200]
    summary = redact_text(title)
    blob = f"{kind} {title}".casefold()
    if any(marker in blob for marker in DANGEROUS_PERMISSION_MARKERS):
        return "black", summary
    if mode != "agent" and kind in {"edit", "delete", "move", "execute"}:
        return "red", summary
    if kind in {"delete", "execute"}:
        return "red", summary
    if kind in {"edit", "move"}:
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
    ) -> None:
        self.mode = mode
        self.bridge = bridge or ApprovalBridge(policy=ApprovalPolicy(auto_approve_green=True))
        self.decision_hook = decision_hook
        self.records: list[dict[str, Any]] = []

    def decide(self, params: Mapping[str, Any]) -> dict[str, Any]:
        risk, summary = classify_permission_risk(params, mode=self.mode)
        request = self._persist_request(params, risk=risk, summary=summary)
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
        else:
            hook_decision = self.decision_hook(step) if self.decision_hook else "rejected"
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
                    decided_by="policy" if self.decision_hook is None else "human",
                    reason="ACP permission denied pending explicit approval",
                )
                policy = (
                    "denied_missing_human"
                    if self.decision_hook is None
                    else "rejected_by_human"
                )
        option_id = permission_option_id(params, allow=allow)
        if option_id not in ALLOWED_ACP_OPTIONS and allow:
            option_id = permission_option_id(params, allow=False)
            allow = False
            policy = "denied_by_policy"
        record = {
            "approval_request_id": request.request_id,
            "approval_step_id": step.step_id,
            "tool": summary,
            "risk_level": risk,
            "policy_decision": policy,
            "option_id": option_id,
            "acp_response": {"outcome": {"outcome": "selected", "optionId": option_id}},
        }
        self.records.append(record)
        refreshed = self.bridge.store.get_request(request.request_id)
        if refreshed is not None:
            refreshed.metadata = {**refreshed.metadata, "acp_permission": record}
            self.bridge.store.save_request(refreshed)
        return record["acp_response"]

    def _persist_request(
        self, params: Mapping[str, Any], *, risk: str, summary: str
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            request_id=_uid("areq"),
            source_type="acp_permission",
            source_id=_uid("acp"),
            run_id="acp",
            goal_id="acp",
            track_id="acp-permission",
            opportunity_plan_id="acp-permission",
            goal_text=summary,
            track_name="ACP permission",
            risk_level=risk,
            metadata={"acp_params_keys": sorted(str(key) for key in params.keys())[:20]},
        )
        auto_approved = risk == "green" and self.bridge.policy.auto_approve_green
        request.steps.append(
            ApprovalStep(
                step_id=_uid("astp"),
                request_id=request.request_id,
                source_type="acp_permission",
                source_id=request.source_id,
                task=summary,
                risk_level=risk,
                permission_scope="read" if risk == "green" else "write",
                approval_required=risk != "green",
                approval_state="approved" if auto_approved else "pending",
                metadata={"auto_approved": auto_approved, "blocked": risk == "black"},
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
            response = self.permission_gate.decide(params)
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

    def discover_models(self, *, local_only: bool = False) -> ProviderModelCatalog:
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
        gate = AcpPermissionGate(
            mode=mode,
            bridge=ApprovalBridge(
                store=self.approval_store,
                policy=ApprovalPolicy(auto_approve_green=True),
            ),
            decision_hook=self.permission_hook,
        )

        def handler(session: InteractiveSession) -> dict[str, Any]:
            client = AcpClient(
                session,
                cwd=str(repo),
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

        try:
            outcome = self.engine.run_task(
                request.message,
                runtime="cursor",
                model=request.model_id,
                execute=True,
                approved=False,
                timeout_seconds=request.timeout_seconds,
                cwd=str(repo),
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
        return result

    def stream(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[ProviderEvent]:
        result = self.execute(request, cancellation)
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
