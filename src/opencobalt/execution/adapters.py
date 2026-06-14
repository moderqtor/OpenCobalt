"""Runtime adapter protocol for Receipt-Backed Execution v0.

An adapter knows how to detect a local agent runtime, report its discovered
capabilities, and build a default-safe argv for a one-shot non-interactive
task. Adapters never execute anything themselves.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from opencobalt.integrations.antigravity_integration import (
    build_antigravity_command,
    discover_antigravity_runtime,
)

from .models import RiskLevel, RuntimeCapabilitySnapshot
from .policy import classify_risk


@dataclass
class CommandOptions:
    """Options that shape command construction. All default to safe values."""

    model: str | None = None
    sandbox: bool = False
    dangerously_skip_permissions: bool = False
    allow_dangerously_skip_permissions: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class RuntimeAdapter(ABC):
    runtime_id: str
    display_name: str
    executable: str
    supported_artifact_types: tuple[str, ...] = ("stdout", "stderr")
    supports_json_output: bool = False
    requires_network: bool = False
    requires_credentials: bool = True
    max_safe_risk: RiskLevel = "yellow"
    verifiability_level: str = "partial"

    def detect(self) -> bool:
        """Return True if the runtime executable is on PATH."""
        return shutil.which(self.executable) is not None

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        """Return a capability snapshot suitable for embedding in a receipt."""
        ...

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        """Return normalized descriptive capability evidence for this adapter."""
        raw = self.capabilities()
        executable_path = shutil.which(self.executable)
        available = executable_path is not None
        supports_noninteractive = self.supports_non_interactive()
        limitations: list[str] = []
        if not available:
            limitations.append(f"executable not found: {self.executable}")
        if not supports_noninteractive:
            limitations.append("non-interactive invocation is unavailable")
        if self.requires_credentials:
            limitations.append("may require runtime credentials outside OpenCobalt")
        level = self.verifiability_level if available else "unavailable"
        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path=executable_path,
            available=available,
            capabilities=_supported_capability_names(raw),
            supported_artifact_types=list(self.supported_artifact_types),
            supports_dry_run=True,
            supports_noninteractive=supports_noninteractive,
            supports_json_output=self.supports_json_output,
            requires_network=self.requires_network if available else True,
            requires_credentials=self.requires_credentials if available else True,
            max_safe_risk=self.max_safe_risk if available else "green",
            limitations=limitations,
            verifiability_level=level,  # type: ignore[arg-type]
            capability_details=raw,
        ).with_hash()

    @abstractmethod
    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        """Return a default-safe argv for the task. Never uses shell strings."""
        ...

    @abstractmethod
    def supports_non_interactive(self) -> bool:
        ...

    def default_timeout_seconds(self) -> int:
        return 120

    def risk_for_task(self, task: str) -> RiskLevel:
        return classify_risk(task)


class AntigravityAdapter(RuntimeAdapter):
    """Google Antigravity CLI (agy). Limited to discovered --print mode."""

    runtime_id = "google-antigravity"
    display_name = "Google Antigravity CLI"
    executable = "agy"
    requires_network = True
    requires_credentials = True
    max_safe_risk = "yellow"
    verifiability_level = "partial"

    def __init__(self, capabilities: dict[str, Any] | None = None) -> None:
        self._capabilities = capabilities

    def capabilities(self) -> dict[str, Any]:
        if self._capabilities is None:
            self._capabilities = discover_antigravity_runtime()["capabilities"]
        return self._capabilities

    def supports_non_interactive(self) -> bool:
        caps = self.capabilities()
        return any(
            caps.get(key, {}).get("supported") is True
            for key in ("non_interactive_print", "non_interactive_mode")
        )

    def default_timeout_seconds(self) -> int:
        return 300

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        opts = options or CommandOptions()
        return build_antigravity_command(
            task,
            model=opts.model,
            sandbox=opts.sandbox,
            dangerously_skip_permissions=opts.dangerously_skip_permissions,
            allow_dangerously_skip_permissions=opts.allow_dangerously_skip_permissions,
            capabilities=self.capabilities(),
        )


class OllamaAdapter(RuntimeAdapter):
    """Local Ollama models. One-shot prompt via `ollama run`."""

    runtime_id = "ollama"
    display_name = "Ollama (local models)"
    executable = "ollama"
    default_model = "llama3"
    requires_network = False
    requires_credentials = False
    max_safe_risk = "yellow"
    verifiability_level = "full"

    def capabilities(self) -> dict[str, Any]:
        return {
            "local_inference": {"supported": True, "source": "static"},
            "non_interactive_run": {"supported": True, "source": "static"},
        }

    def supports_non_interactive(self) -> bool:
        return True

    def default_timeout_seconds(self) -> int:
        return 600

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        opts = options or CommandOptions()
        model = opts.model or self.default_model
        return ["ollama", "run", model, task]


class NoopAdapter(RuntimeAdapter):
    """Echo-only adapter for tests and pipeline verification. No agent runs."""

    runtime_id = "noop"
    display_name = "Noop (echo)"
    executable = "echo"
    requires_network = False
    requires_credentials = False
    max_safe_risk = "yellow"
    verifiability_level = "full"

    def capabilities(self) -> dict[str, Any]:
        return {"echo_only": {"supported": True, "source": "static"}}

    def supports_non_interactive(self) -> bool:
        return True

    def default_timeout_seconds(self) -> int:
        return 10

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        # Normalize tasks that already start with "echo " so the captured
        # output is the message itself, not "echo echo ...".
        if task.startswith("echo "):
            return ["echo", task[len("echo "):]]
        return ["echo", task]


_ADAPTERS: dict[str, type[RuntimeAdapter]] = {
    AntigravityAdapter.runtime_id: AntigravityAdapter,
    OllamaAdapter.runtime_id: OllamaAdapter,
    NoopAdapter.runtime_id: NoopAdapter,
}


def _supported_capability_names(raw: dict[str, Any]) -> list[str]:
    supported: list[str] = []
    for name, detail in raw.items():
        if isinstance(detail, dict):
            if detail.get("supported") is True:
                supported.append(name)
        elif detail:
            supported.append(name)
    return sorted(supported)


def available_runtimes() -> list[str]:
    return sorted(_ADAPTERS)


def get_adapter(runtime_id: str, **kwargs: Any) -> RuntimeAdapter:
    """Return an adapter instance for a runtime id.

    Raises KeyError for unknown runtimes so callers can fail cleanly.
    """
    from opencobalt.integrations.registry import resolve_integration_name

    canonical = resolve_integration_name(runtime_id) or runtime_id
    try:
        adapter_cls = _ADAPTERS[canonical]
    except KeyError:
        known = ", ".join(available_runtimes())
        raise KeyError(f"unknown runtime '{runtime_id}' (known: {known})") from None
    return adapter_cls(**kwargs)
