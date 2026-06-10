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

from .models import RiskLevel
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

    def detect(self) -> bool:
        """Return True if the runtime executable is on PATH."""
        return shutil.which(self.executable) is not None

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        """Return a capability snapshot suitable for embedding in a receipt."""
        ...

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

    def capabilities(self) -> dict[str, Any]:
        return {"echo_only": {"supported": True, "source": "static"}}

    def supports_non_interactive(self) -> bool:
        return True

    def default_timeout_seconds(self) -> int:
        return 10

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        return ["echo", task]


_ADAPTERS: dict[str, type[RuntimeAdapter]] = {
    AntigravityAdapter.runtime_id: AntigravityAdapter,
    OllamaAdapter.runtime_id: OllamaAdapter,
    NoopAdapter.runtime_id: NoopAdapter,
}


def available_runtimes() -> list[str]:
    return sorted(_ADAPTERS)


def get_adapter(runtime_id: str, **kwargs: Any) -> RuntimeAdapter:
    """Return an adapter instance for a runtime id.

    Raises KeyError for unknown runtimes so callers can fail cleanly.
    """
    try:
        adapter_cls = _ADAPTERS[runtime_id]
    except KeyError:
        known = ", ".join(available_runtimes())
        raise KeyError(f"unknown runtime '{runtime_id}' (known: {known})") from None
    return adapter_cls(**kwargs)
