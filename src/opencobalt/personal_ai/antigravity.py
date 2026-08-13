"""Antigravity-backed Personal AI provider using discovered headless interfaces.

OpenCobalt owns routing, isolation, and receipts. This module only translates
discovered ``agy`` capabilities into the normalized provider boundary.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

from opencobalt.execution.adapters import AntigravityAdapter, CommandOptions
from opencobalt.execution.models import RuntimeCapabilitySnapshot
from opencobalt.integrations.antigravity_integration import (
    build_antigravity_command,
    build_antigravity_models_command,
)
from opencobalt.personal_ai.providers import (
    AuthenticationState,
    CancellationToken,
    EngineBackedChatProvider,
    ProviderError,
    ProviderHealth,
    ProviderHealthState,
    ProviderModel,
    ProviderModelCatalog,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
    ProviderToolEvent,
    _AdapterLike,
    _EngineLike,
    _events_from_result,
    _normalize_outcome,
    _pre_execution_error,
    _public_error_text,
    _public_output_text,
    _routing_profile,
    _safe_model_identifier,
)

_SCRATCH_ROOT = Path(".opencobalt") / "scratch" / "antigravity"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _capability_supported(capabilities: Mapping[str, Any], *keys: str) -> bool:
    return any(
        isinstance(capabilities.get(key), Mapping)
        and capabilities[key].get("supported") is True
        for key in keys
    )


def infer_antigravity_model_profile(model_id: str, display_name: str = "") -> dict[str, Any]:
    """Derive routing priors from discovered model identifiers.

    These are naming heuristics, not live quality, latency, or price evidence.
    """
    lowered = f"{model_id} {display_name}".casefold()
    effort_levels: list[str] = []
    if re.search(r"(?:^|[-_])high(?:$|[-_])", model_id.casefold()) or model_id.casefold().endswith(
        "-high"
    ):
        effort_levels = ["high"]
    elif model_id.casefold().endswith("-medium"):
        effort_levels = ["medium"]
    elif model_id.casefold().endswith("-low"):
        effort_levels = ["low"]

    reasoning_support = any(
        token in lowered for token in ("thinking", "pro", "opus", "sonnet")
    ) or bool(effort_levels)

    if "opus" in lowered:
        quality, cost, latency = "strong", "high", "high"
    elif "pro" in lowered:
        quality, cost, latency = "strong", "standard", "high"
    elif "sonnet" in lowered:
        quality, cost, latency = "strong", "standard", "standard"
    elif "flash" in lowered and model_id.casefold().endswith("-low"):
        quality, cost, latency = "standard", "low", "low"
    elif "flash" in lowered:
        quality, cost, latency = "standard", "low", "low"
    elif "gpt-oss" in lowered or "gpt oss" in lowered:
        quality, cost, latency = "standard", "low", "standard"
    else:
        quality, cost, latency = "standard", "standard", "standard"

    if "gemini" in lowered:
        family = "gemini"
    elif "claude" in lowered:
        family = "claude"
    elif "gpt" in lowered:
        family = "gpt"
    else:
        family = "unknown"

    return {
        "family": family,
        "quality_tier": quality,
        "cost_category": cost,
        "latency_category": latency,
        "reasoning_support": reasoning_support,
        "effort_levels": effort_levels,
        "streaming_support": True,
        "heuristic": "antigravity_model_id_v1",
    }


def parse_antigravity_models_payload(raw_content: str) -> tuple[list[ProviderModel], list[str]]:
    """Admit only structured model records from ``agy --output-format json models``."""
    payload = _parse_json_object(raw_content)
    if payload is None:
        raise ValueError("invalid Antigravity model catalog JSON")
    command = payload.get("command") if isinstance(payload.get("command"), Mapping) else {}
    data = command.get("data") if isinstance(command, Mapping) else None
    raw_models = data.get("models") if isinstance(data, Mapping) else None
    if not isinstance(raw_models, list):
        raise ValueError("invalid Antigravity model catalog shape")

    discovered_at = _now()
    models: list[ProviderModel] = []
    seen: set[str] = set()
    skipped = 0
    for raw in raw_models[:200]:
        if not isinstance(raw, Mapping):
            skipped += 1
            continue
        model_id = raw.get("id") or raw.get("model")
        label = raw.get("label") or raw.get("name") or model_id
        if not isinstance(model_id, str) or not _safe_model_identifier(model_id):
            skipped += 1
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        profile = infer_antigravity_model_profile(
            model_id, label if isinstance(label, str) else model_id
        )
        models.append(
            ProviderModel(
                provider_id="antigravity",
                model_id=model_id,
                display_name=str(label)[:200],
                source="runtime_discovered",
                execution_location="remote",
                locality_evidence=["antigravity_authenticated_catalog"],
                reasoning_support=bool(profile["reasoning_support"]),
                effort_levels=list(profile["effort_levels"]),
                streaming_support=True,
                available=True,
                discovered_at=discovered_at,
                quality_tier=profile["quality_tier"],
                cost_category=profile["cost_category"],
                latency_category=profile["latency_category"],
                family=profile["family"],
                profile_evidence=profile["heuristic"],
            )
        )
    limitations = [
        "model quality, cost, and latency are identifier heuristics, not live calibration",
        "Antigravity models execute remotely through an authenticated CLI session",
    ]
    if skipped:
        limitations.append(f"excluded {skipped} malformed Antigravity model record(s)")
    return models, limitations


def parse_antigravity_payload(
    raw_content: str,
) -> tuple[str, dict[str, Any] | None, list[ProviderToolEvent], str | None, list[str]]:
    """Normalize json or stream-json Antigravity print output."""
    stream_events = _parse_stream_json(raw_content)
    if stream_events:
        return _normalize_stream_json(stream_events)

    payload = _parse_json_object(raw_content)
    if payload is None:
        return raw_content, None, [], None, []
    return _normalize_result_envelope(payload, tool_events=[])


def antigravity_scratch_dir(request_id: str) -> Path:
    """Return an isolated working directory that is not the OpenCobalt repository."""
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", request_id)[:80] or "request"
    root = Path.cwd() / _SCRATCH_ROOT
    path = root / safe_id
    path.mkdir(parents=True, exist_ok=True)
    (path / ".opencobalt-scratch").write_text(
        "OpenCobalt Antigravity answer-only scratch directory.\n",
        encoding="utf-8",
    )
    return path


def print_timeout_flag(timeout_seconds: int) -> str:
    bounded = max(1, min(int(timeout_seconds), 3600))
    return f"{bounded}s"


def mapped_effort(value: str | None) -> str | None:
    if value in {"low", "medium", "high"}:
        return value
    if value == "xhigh":
        return "high"
    return None


class _AntigravityModelCatalogAdapter:
    """Read the authenticated model catalog without starting an agent turn."""

    runtime_id = "google-antigravity-models"
    display_name = "Google Antigravity model catalog"
    executable = "agy"
    isolates_answer_only_inference = True

    def __init__(self, capabilities: dict[str, Any]) -> None:
        self._capabilities = capabilities

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        available = _capability_supported(self._capabilities, "models_subcommand") and (
            _capability_supported(self._capabilities, "json_output")
        )
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path="agy" if available else None,
            available=available,
            capabilities=["model_catalog"] if available else [],
            supported_artifact_types=["stdout", "stderr"],
            supports_dry_run=True,
            supports_noninteractive=available,
            supports_json_output=True,
            requires_network=True,
            requires_credentials=True,
            max_safe_risk="green",
            limitations=(
                []
                if available
                else ["agy models JSON catalog was not discovered from local help"]
            ),
            verifiability_level="partial" if available else "unavailable",
            capability_details={"catalog_command": "agy --output-format json models"},
        ).with_hash()

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        _ = task, options
        return build_antigravity_models_command(capabilities=self._capabilities)

    def supports_non_interactive(self) -> bool:
        return self.discover_capabilities().supports_noninteractive

    def default_timeout_seconds(self) -> int:
        return 30

    def risk_for_task(self, task: str) -> str:
        _ = task
        return "green"


class _AntigravityPrintAdapter:
    """One-shot headless print in an isolated scratch workspace."""

    display_name = "Google Antigravity isolated print"
    executable = "agy"
    isolates_answer_only_inference = True

    def __init__(
        self,
        *,
        capabilities: dict[str, Any],
        model_id: str | None = None,
        effort: str | None = None,
        timeout_seconds: int = 120,
        output_format: Literal["json", "stream-json"] = "json",
        json_schema: str | None = None,
        conversation_id: str | None = None,
        research: bool = False,
    ) -> None:
        self._capabilities = capabilities
        self.model_id = model_id
        self.effort = mapped_effort(effort)
        self.timeout_seconds = timeout_seconds
        self.output_format = output_format
        self.json_schema = json_schema
        self.conversation_id = conversation_id
        self.research = research
        self.runtime_id = (
            "google-antigravity-research" if research else "google-antigravity-answer-only"
        )

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        available = _capability_supported(
            self._capabilities, "non_interactive_print", "non_interactive_mode"
        ) and _capability_supported(self._capabilities, "json_output")
        limitations = [
            "isolated scratch working directory; OpenCobalt repository is not the workspace",
            "headless permission prompts are not auto-approved; unsafe skip is disabled",
            "--sandbox is used when discovered so terminal commands stay restricted",
        ]
        if self.research:
            limitations.append(
                "research print may use provider tools if the runtime auto-allows them; "
                "OpenCobalt still verifies cited HTTPS sources independently"
            )
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path="agy" if available else None,
            available=available,
            capabilities=["isolated_print"] if available else [],
            supported_artifact_types=["stdout", "stderr"],
            supports_dry_run=True,
            supports_noninteractive=available,
            supports_json_output=True,
            requires_network=True,
            requires_credentials=True,
            max_safe_risk="yellow",
            limitations=limitations,
            verifiability_level="partial" if available else "unavailable",
            capability_details={
                "output_format": self.output_format,
                "sandbox": _capability_supported(
                    self._capabilities, "sandbox_mode", "terminal_sandbox"
                ),
                "research": self.research,
            },
        ).with_hash()

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        model = self.model_id or (options.model if options is not None else None)
        effort = self.effort
        if model and _model_encodes_effort(model):
            effort = None
        sandbox = _capability_supported(self._capabilities, "sandbox_mode", "terminal_sandbox")
        output_format = self.output_format
        if output_format == "stream-json" and not _capability_supported(
            self._capabilities, "stream_json_output", "json_output"
        ):
            output_format = "json"
        return build_antigravity_command(
            task,
            model=model,
            sandbox=sandbox,
            dangerously_skip_permissions=False,
            allow_dangerously_skip_permissions=False,
            capabilities=self._capabilities,
            output_format=output_format,
            effort=effort,
            json_schema=self.json_schema,
            disable_slash_commands=_capability_supported(
                self._capabilities, "disable_slash_commands"
            ),
            print_timeout=(
                print_timeout_flag(self.timeout_seconds)
                if _capability_supported(self._capabilities, "print_timeout")
                else None
            ),
            conversation_id=self.conversation_id,
        )

    def supports_non_interactive(self) -> bool:
        return self.discover_capabilities().supports_noninteractive

    def default_timeout_seconds(self) -> int:
        return self.timeout_seconds

    def risk_for_task(self, task: str) -> str:
        _ = task
        return "green"


class AntigravityChatProvider(EngineBackedChatProvider):
    """Executable Antigravity Chat provider with isolated print and live models."""

    def __init__(self, engine: _EngineLike, adapter: _AdapterLike) -> None:
        super().__init__(
            provider_id="antigravity",
            display_name="Google Antigravity",
            engine=engine,
            adapter=adapter,
            supports_model_discovery=True,
            routing_profile=_routing_profile("antigravity"),
        )
        self._catalog_cache: ProviderModelCatalog | None = None

    def _runtime_capabilities(self) -> dict[str, Any]:
        if isinstance(self.adapter, AntigravityAdapter):
            return self.adapter.capabilities()
        snapshot = self.adapter.discover_capabilities()
        details = snapshot.capability_details
        return details if isinstance(details, dict) else {}

    def _uses_isolated_print(self) -> bool:
        return getattr(self.adapter, "executable", None) == "agy" and _capability_supported(
            self._runtime_capabilities(), "json_output"
        )

    def status(self) -> ProviderStatus:
        status = super().status()
        capabilities = self._runtime_capabilities()
        catalog_supported = _capability_supported(
            capabilities, "models_subcommand"
        ) and _capability_supported(capabilities, "json_output")
        isolated = status.capabilities.answer_only_isolation or self._uses_isolated_print()
        status.capabilities.model_discovery = bool(
            status.installed and catalog_supported
        )
        status.capabilities.answer_only_isolation = bool(
            status.execution_supported and isolated
        )
        status.capabilities.usage_reporting = bool(
            status.execution_supported and _capability_supported(capabilities, "json_output")
        )
        status.capabilities.streaming = (
            "completion_only" if status.execution_supported else "none"
        )
        status.limitations = [
            item
            for item in status.limitations
            if "approval-and-resume is not implemented" not in item
        ]
        if status.execution_supported and isolated:
            status.limitations.append(
                "answer-only Chat uses an isolated scratch workspace, discovered "
                "--sandbox when available, JSON print output, and never enables "
                "--dangerously-skip-permissions"
            )
            status.limitations.append(
                "headless Antigravity soft-denies tools that require approval; Chat "
                "does not grant repository or shell authority"
            )
        if status.capabilities.model_discovery:
            status.limitations.append(
                "models are discovered from the authenticated agy catalog; disappeared "
                "models are not kept available"
            )
        status.limitations = list(dict.fromkeys(status.limitations))
        return status

    def health(self) -> ProviderHealth:
        status = self.status()
        catalog = None
        if status.capabilities.model_discovery:
            catalog = self.discover_models()
        verified = bool(catalog and catalog.models and catalog.error is None)
        authentication: AuthenticationState = "verified" if verified else status.authentication
        health: ProviderHealthState = "ready" if verified and status.execution_supported else status.health
        limitations = list(status.limitations)
        if catalog is not None and catalog.error is not None:
            limitations.append(_public_error_text(catalog.error.message))
            health = "unavailable"
            authentication = "unknown"
        return ProviderHealth(
            provider_id=status.provider_id,
            state=health,
            authentication=authentication,
            evidence="capability_snapshot",
            successful_invocation_proven=False,
            limitations=limitations,
        )

    def discover_models(self, *, local_only: bool = False) -> ProviderModelCatalog:
        request = ProviderRequest(
            message="discover authenticated Antigravity models",
            local_only=local_only,
            timeout_seconds=30,
        )
        if local_only:
            return ProviderModelCatalog(
                provider_id=self.provider_id,
                error=ProviderError(
                    category="local_only_violation",
                    message="Antigravity model discovery requires network access and is excluded by local-only",
                ),
            )
        capabilities = self._runtime_capabilities()
        catalog_adapter = _AntigravityModelCatalogAdapter(capabilities)
        if not catalog_adapter.supports_non_interactive():
            return ProviderModelCatalog(
                provider_id=self.provider_id,
                error=ProviderError(
                    category="unavailable",
                    message="Antigravity JSON model catalog was not discovered",
                ),
            )
        outcome = self.engine.run_task(
            "inspect authenticated Antigravity model catalog",
            runtime=catalog_adapter.runtime_id,
            model=None,
            execute=True,
            approved=False,
            timeout_seconds=30,
            cwd=str(antigravity_scratch_dir("models")),
            unsafe_skip_permissions=False,
            execution_context="answer_only_inference",
            adapter=catalog_adapter,
        )
        normalized = _normalize_outcome(
            request=request,
            provider_id="antigravity-catalog",
            model_id=None,
            outcome=outcome,
        )
        raw_content = normalized.content
        result = getattr(outcome, "result", None)
        if result is not None:
            from opencobalt.personal_ai.providers import _engine_result_output

            raw_content = _engine_result_output(result) or normalized.content
        if normalized.status != "complete":
            return ProviderModelCatalog(
                provider_id=self.provider_id,
                receipt_id=normalized.receipt_id,
                error=normalized.error
                or ProviderError(
                    category="unavailable",
                    message="Antigravity model discovery failed",
                ),
            )
        try:
            models, limitations = parse_antigravity_models_payload(raw_content)
        except ValueError:
            return ProviderModelCatalog(
                provider_id=self.provider_id,
                receipt_id=normalized.receipt_id,
                error=ProviderError(
                    category="provider_error",
                    message="Antigravity returned an invalid model catalog",
                ),
            )
        catalog = ProviderModelCatalog(
            provider_id=self.provider_id,
            models=models,
            receipt_id=normalized.receipt_id,
            limitations=limitations,
        )
        self._catalog_cache = catalog
        return catalog

    def execute(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ) -> ProviderResult:
        if request.local_only:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="local_only_violation",
                message="Antigravity is not eligible for local-only execution",
                status="blocked",
            )
        if not self._uses_isolated_print():
            return super().execute(request, cancellation)

        catalog = self.discover_models(local_only=False)
        admitted = {model.model_id for model in catalog.models}
        if request.model_id and catalog.error is None and request.model_id not in admitted:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="invalid_request",
                message="requested Antigravity model was not reported by authenticated discovery",
                status="blocked",
            )
        if catalog.error is not None and request.model_id:
            return _pre_execution_error(
                request,
                self.provider_id,
                category="unavailable",
                message="Antigravity model discovery failed; refusing unknown model override",
                status="blocked",
            )

        schema_path = None
        json_schema = request.metadata.get("json_schema")
        scratch = antigravity_scratch_dir(request.request_id)
        if isinstance(json_schema, Mapping):
            schema_path = scratch / "schema.json"
            schema_path.write_text(
                json.dumps(json_schema, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
        elif isinstance(json_schema, str) and json_schema.strip():
            schema_path = scratch / "schema.json"
            schema_path.write_text(json_schema, encoding="utf-8")

        research = bool(request.metadata.get("research"))
        adapter = _AntigravityPrintAdapter(
            capabilities=self._runtime_capabilities(),
            model_id=request.model_id,
            effort=str(request.metadata.get("reasoning_effort") or "") or None,
            timeout_seconds=request.timeout_seconds,
            output_format="json" if schema_path is not None else (
                "stream-json" if research else "json"
            ),
            json_schema=str(schema_path) if schema_path is not None else None,
            conversation_id=(
                str(request.metadata["provider_session_id"])
                if isinstance(request.metadata.get("provider_session_id"), str)
                else None
            ),
            research=research,
        )
        result = self._execute_through_engine(
            request,
            cancellation=cancellation,
            adapter=adapter,
            model_id=request.model_id,
            cwd=str(scratch),
        )
        if result.status == "complete" and not result.content.strip():
            result.status = "failed"
            result.error = ProviderError(
                category="provider_error",
                message="Antigravity returned an empty isolated print response",
            )
        return result

    def stream(
        self,
        request: ProviderRequest,
        cancellation: CancellationToken | None = None,
    ):
        result = self.execute(request, cancellation)
        yield from _events_from_result(result, cancellation, chunk_size=64)


def _model_encodes_effort(model_id: str) -> bool:
    lowered = model_id.casefold()
    return lowered.endswith(("-high", "-medium", "-low"))


def _parse_json_object(raw_content: str) -> dict[str, Any] | None:
    text = raw_content.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _parse_stream_json(raw_content: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw_content.splitlines()[:5_000]:
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") in {"init", "step_update", "result"}:
            events.append(event)
    return events


def _normalize_stream_json(
    events: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None, list[ProviderToolEvent], str | None, list[str]]:
    tool_events: list[ProviderToolEvent] = []
    limitations: list[str] = []
    session_id: str | None = None
    for event in events:
        if event.get("event") == "init" and isinstance(event.get("init"), Mapping):
            init = event["init"]
            tools = init.get("tools")
            if isinstance(tools, list) and tools:
                limitations.append(
                    "runtime advertised tools: "
                    + ", ".join(str(item) for item in tools[:24] if isinstance(item, str))
                )
            permission_mode = init.get("permission_mode")
            if isinstance(permission_mode, str) and permission_mode:
                limitations.append(f"permission mode: {permission_mode}")
        step = event.get("step_update")
        if event.get("event") == "step_update" and isinstance(step, Mapping):
            if isinstance(step.get("conversation_id"), str) and step["conversation_id"]:
                session_id = str(step["conversation_id"])
            if str(step.get("step_type")) == "tool" and str(step.get("state")).upper() == "DONE":
                tool_events.append(_tool_event_from_step(step))
            subagents = step.get("subagent_info")
            if isinstance(subagents, Mapping):
                for item in _as_list(subagents.get("subagents"))[:20]:
                    if not isinstance(item, Mapping):
                        continue
                    role = item.get("role") or item.get("type_name") or "subagent"
                    tool_events.append(
                        ProviderToolEvent(
                            tool_call_id=str(item.get("conversation_id") or role)[:200],
                            tool_name="subagent",
                            status="complete",
                            summary=_public_output_text(str(role))[:500],
                        )
                    )
        if event.get("event") == "result" and isinstance(event.get("result"), Mapping):
            content, usage, _, result_session, extra = _normalize_result_envelope(
                event["result"],
                tool_events=tool_events,
            )
            return content, usage, tool_events, result_session or session_id, limitations + extra
    return "", None, tool_events, session_id, limitations


def _normalize_result_envelope(
    payload: Mapping[str, Any],
    *,
    tool_events: list[ProviderToolEvent],
) -> tuple[str, dict[str, Any] | None, list[ProviderToolEvent], str | None, list[str]]:
    status = str(payload.get("status") or "")
    session_id = payload.get("conversation_id")
    session = str(session_id) if isinstance(session_id, str) and session_id else None
    structured = payload.get("structured_output")
    response = payload.get("response")
    if isinstance(structured, Mapping):
        content = json.dumps(structured, sort_keys=True)
    elif isinstance(response, str):
        content = response
    else:
        content = ""
    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else None
    limitations: list[str] = []
    error = payload.get("error")
    if status and status.upper() not in {"SUCCESS", ""}:
        message = error if isinstance(error, str) and error.strip() else f"Antigravity status {status}"
        limitations.append(_public_error_text(str(message)))
    return content, dict(usage) if usage is not None else None, tool_events, session, limitations


def _tool_event_from_step(step: Mapping[str, Any]) -> ProviderToolEvent:
    info = step.get("tool_info") if isinstance(step.get("tool_info"), Mapping) else {}
    name = str(info.get("name") or step.get("tool_name") or "tool")[:100]
    output = info.get("output")
    error = info.get("error")
    failed = isinstance(error, Mapping) or (
        isinstance(error, str) and error.strip()
    )
    summary_source = output if isinstance(output, str) and output.strip() else name
    if failed:
        summary_source = error.get("message") if isinstance(error, Mapping) else error
    return ProviderToolEvent(
        tool_call_id=str(step.get("step_index", name))[:200],
        tool_name=name,
        status="failed" if failed else "complete",
        summary=_public_output_text(str(summary_source))[:500],
    )


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


__all__ = [
    "AntigravityChatProvider",
    "antigravity_scratch_dir",
    "infer_antigravity_model_profile",
    "parse_antigravity_models_payload",
    "parse_antigravity_payload",
    "print_timeout_flag",
]
