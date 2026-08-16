"""Receipt-backed adapter for persistent Codex SDK broker turns.

The SDK itself runs only inside the worker subprocess launched by
ExecutionEngine. This keeps OpenCobalt's execution boundary authoritative while
still allowing Codex threads to persist and resume across broker commands.
"""

from __future__ import annotations

import importlib.util
import sys
from importlib import metadata
from typing import Any, Literal

from opencobalt.execution.adapters import CommandOptions, RuntimeAdapter
from opencobalt.execution.models import RuntimeCapabilitySnapshot
from opencobalt.execution.policy import classify_risk, max_risk

BrokerAction = Literal["turn", "archive"]


class CodexSdkBrokerAdapter(RuntimeAdapter):
    runtime_id = "codex-sdk-broker"
    display_name = "Codex SDK Broker"
    executable = sys.executable
    supported_artifact_types = ("stdout", "stderr")
    supports_json_output = True
    requires_network = True
    requires_credentials = True
    max_safe_risk = "yellow"
    verifiability_level = "partial"

    def __init__(
        self,
        *,
        action: BrokerAction = "turn",
        provider_session_id: str | None = None,
        model: str | None = None,
    ) -> None:
        self.action = action
        self.provider_session_id = provider_session_id
        self.model = model

    @staticmethod
    def _sdk_available() -> bool:
        return importlib.util.find_spec("openai_codex") is not None

    @staticmethod
    def _sdk_version() -> str | None:
        try:
            return metadata.version("openai-codex")
        except metadata.PackageNotFoundError:
            return None

    def capabilities(self) -> dict[str, Any]:
        available = self._sdk_available()
        return {
            "python_sdk": {
                "supported": available,
                "source": "python import discovery",
                "version": self._sdk_version(),
            },
            "persistent_threads": {
                "supported": available,
                "source": "OpenAI Codex Python SDK thread_start/thread_resume",
            },
            "workspace_write_sandbox": {
                "supported": available,
                "source": "OpenAI Codex Python SDK Sandbox.workspace_write",
            },
            "deny_all_escalation": {
                "supported": available,
                "source": "OpenAI Codex Python SDK ApprovalMode.deny_all",
            },
            "thread_archive": {
                "supported": available,
                "source": "OpenAI Codex Python SDK thread_archive",
            },
        }

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        raw = self.capabilities()
        available = self._sdk_available()
        limitations = [
            "Codex authentication and account state remain outside OpenCobalt",
            "Codex SDK runs in an OpenCobalt staged workspace, not the authoritative repository",
            "workspace-write is filesystem containment, not a claim of full host isolation",
            "sandbox escalation requests are denied by the broker worker",
            "push, merge, deploy, publish, spend, messaging, and secret access are not granted",
        ]
        if not available:
            limitations.insert(0, "optional dependency openai-codex is not installed")
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            adapter_version=self._sdk_version(),
            executable_path=sys.executable,
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
        return self._sdk_available()

    def default_timeout_seconds(self) -> int:
        return 1800

    def risk_for_task(self, task: str):
        # A broker turn can mutate its staged workspace, so even an innocuous
        # prompt is at least yellow process authority. Higher prompt risk wins.
        return max_risk("yellow", classify_risk(task))

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        opts = options or CommandOptions()
        if opts.dangerously_skip_permissions or opts.allow_dangerously_skip_permissions:
            raise ValueError("Codex SDK broker does not support permission bypass")
        if not self._sdk_available():
            raise ValueError("optional dependency openai-codex is not installed")
        argv = [sys.executable, "-m", "opencobalt.agent_broker.worker", self.action]
        if self.provider_session_id:
            argv.extend(["--thread-id", self.provider_session_id])
        selected_model = self.model or opts.model
        if selected_model:
            argv.extend(["--model", selected_model])
        if self.action == "turn":
            argv.extend(["--prompt", task])
        return argv
