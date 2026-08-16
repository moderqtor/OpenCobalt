"""Receipt-backed adapter for Google Antigravity CLI broker turns.

Runs Google Antigravity CLI (agy) only inside OpenCobalt staged workspaces through
ExecutionEngine.
"""

from __future__ import annotations

import shutil
from typing import Any

from opencobalt.execution.adapters import CommandOptions, RuntimeAdapter
from opencobalt.execution.models import RuntimeCapabilitySnapshot
from opencobalt.execution.policy import classify_risk, max_risk
from opencobalt.integrations.antigravity_integration import (
    build_antigravity_command,
    discover_antigravity_runtime,
)


class AntigravityBrokerAdapter(RuntimeAdapter):
    """Receipt-backed broker adapter for Google Antigravity CLI."""

    runtime_id = "google-antigravity-broker"
    display_name = "Google Antigravity Broker"
    executable = "agy"
    supported_artifact_types = ("stdout", "stderr")
    supports_json_output = True
    requires_network = True
    requires_credentials = True
    max_safe_risk = "yellow"
    verifiability_level = "partial"

    def __init__(
        self,
        *,
        provider_session_id: str | None = None,
        model: str | None = None,
        sandbox: bool = True,
        capabilities: dict[str, Any] | None = None,
    ) -> None:
        self.provider_session_id = provider_session_id
        self.model = model
        self.sandbox = sandbox
        self._capabilities = capabilities

    def capabilities(self) -> dict[str, Any]:
        if self._capabilities is None:
            self._capabilities = discover_antigravity_runtime()["capabilities"]
        return self._capabilities

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        raw = self.capabilities()
        installed = shutil.which(self.executable) is not None
        available = installed and any(
            raw.get(key, {}).get("supported") is True
            for key in ("non_interactive_print", "non_interactive_mode")
        )
        limitations = [
            "Google Antigravity authentication and account state remain outside OpenCobalt",
            "Google Antigravity CLI runs in an OpenCobalt staged workspace, not the authoritative repository",
            "staged workspace is filesystem containment, not a claim of full host isolation",
            "permission bypass (--dangerously-skip-permissions) is forbidden by OpenCobalt policy",
            "push, merge, deploy, publish, spend, messaging, and secret access are not granted",
            "remote conversation archiving is not supported by Google Antigravity CLI",
        ]
        if not installed:
            limitations.insert(0, "Google Antigravity CLI (agy) is not installed on PATH")
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path=shutil.which(self.executable),
            available=available,
            capabilities=[name for name, detail in raw.items() if detail.get("supported") is True],
            supported_artifact_types=list(self.supported_artifact_types),
            supports_dry_run=True,
            supports_noninteractive=available,
            supports_json_output=True,
            requires_network=True,
            requires_credentials=True,
            max_safe_risk=self.max_safe_risk if available else "green",
            limitations=limitations,
            verifiability_level="partial" if available else "unavailable",
            capability_details=raw,
        ).with_hash()

    def supports_non_interactive(self) -> bool:
        caps = self.capabilities()
        return any(
            caps.get(key, {}).get("supported") is True
            for key in ("non_interactive_print", "non_interactive_mode")
        )

    def default_timeout_seconds(self) -> int:
        return 1800

    def risk_for_task(self, task: str):
        # A broker turn can mutate its staged workspace, so even an innocuous
        # prompt is at least yellow process authority. Higher prompt risk wins.
        return max_risk("yellow", classify_risk(task))

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        opts = options or CommandOptions()
        return build_antigravity_command(
            task,
            model=self.model or opts.model,
            sandbox=self.sandbox if opts.sandbox is False else (opts.sandbox or self.sandbox),
            output_format="json",
            conversation_id=self.provider_session_id,
            dangerously_skip_permissions=opts.dangerously_skip_permissions,
            allow_dangerously_skip_permissions=opts.allow_dangerously_skip_permissions,
            capabilities=self.capabilities(),
        )
