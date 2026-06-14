"""Runtime adapter protocol for Receipt-Backed Execution v0.

An adapter knows how to detect a local agent runtime, report its discovered
capabilities, and build a default-safe argv for a one-shot non-interactive
task. Adapters never execute anything themselves.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
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


_CURSOR_BUNDLED_CLI = Path("Contents") / "Resources" / "app" / "bin" / "cursor"
_CURSOR_HELP_TIMEOUT_SECONDS = 5


def _default_cursor_app_paths() -> tuple[Path, ...]:
    return (
        Path("/Applications/Cursor.app"),
        Path.home() / "Applications" / "Cursor.app",
    )


def _is_executable(path: str | Path | None) -> bool:
    if path is None:
        return False
    candidate = Path(path)
    return candidate.is_file() and os.access(candidate, os.X_OK)


class CursorAdapter(RuntimeAdapter):
    """Cursor Agent CLI. Limited to read-only plan mode when locally discovered."""

    runtime_id = "cursor"
    display_name = "Cursor Agent"
    executable = "cursor"
    requires_network = True
    requires_credentials = True
    max_safe_risk = "green"
    verifiability_level = "partial"
    supports_json_output = True

    def __init__(
        self,
        *,
        app_paths: tuple[str | Path, ...] | None = None,
        help_text: str | None = None,
    ) -> None:
        self._app_paths = tuple(Path(path) for path in app_paths) if app_paths is not None else (
            _default_cursor_app_paths()
        )
        self._help_text = help_text
        self._capabilities: dict[str, Any] | None = None

    def _path_binary(self) -> str | None:
        found = shutil.which(self.executable)
        return found if _is_executable(found) else None

    def _existing_app_paths(self) -> list[Path]:
        return [path for path in self._app_paths if path.exists()]

    def _bundled_cli(self) -> str | None:
        for app_path in self._existing_app_paths():
            candidate = app_path / _CURSOR_BUNDLED_CLI
            if _is_executable(candidate):
                return str(candidate)
        return None

    def _execution_cli(self) -> str | None:
        return self._path_binary() or self._bundled_cli()

    def _display_path(self) -> str | None:
        path_binary = self._path_binary()
        if path_binary:
            return path_binary
        apps = self._existing_app_paths()
        if apps:
            return str(apps[0])
        return None

    def _agent_help(self) -> str:
        if self._help_text is not None:
            return self._help_text
        executable = self._execution_cli()
        if executable is None:
            return ""
        try:
            result = subprocess.run(
                [executable, "agent", "--help"],
                capture_output=True,
                text=True,
                timeout=_CURSOR_HELP_TIMEOUT_SECONDS,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return ""
        return "\n".join(part for part in (result.stdout, result.stderr) if part)

    def capabilities(self) -> dict[str, Any]:
        if self._capabilities is not None:
            return self._capabilities

        path_binary = self._path_binary()
        app_paths = self._existing_app_paths()
        bundled_cli = self._bundled_cli()
        executable = path_binary or bundled_cli
        help_text = self._agent_help() if executable else ""
        has_agent = "cursor agent" in help_text or "Start the Cursor Agent" in help_text
        has_print = "--print" in help_text
        has_mode = "--mode" in help_text and "plan" in help_text and "read-only" in help_text
        has_output_format = "--output-format" in help_text
        has_json = "json" in help_text and has_output_format
        has_sandbox = "--sandbox" in help_text
        has_model = "--model" in help_text

        self._capabilities = {
            "macos_app": {
                "supported": bool(app_paths),
                "source": "filesystem",
                "path": str(app_paths[0]) if app_paths else None,
            },
            "path_binary": {
                "supported": path_binary is not None,
                "source": "PATH",
                "path": path_binary,
            },
            "bundled_cli": {
                "supported": bundled_cli is not None,
                "source": "app_bundle",
                "path": bundled_cli,
            },
            "agent_subcommand": {
                "supported": has_agent,
                "source": "cursor agent --help" if help_text else "unknown",
            },
            "non_interactive_print": {
                "supported": has_print,
                "source": "cursor agent --help" if help_text else "unknown",
            },
            "read_only_plan_mode": {
                "supported": has_mode,
                "source": "cursor agent --help" if help_text else "unknown",
            },
            "text_output": {
                "supported": has_output_format,
                "source": "cursor agent --help" if help_text else "unknown",
            },
            "json_output": {
                "supported": has_json,
                "source": "cursor agent --help" if help_text else "unknown",
            },
            "sandbox_flag": {
                "supported": has_sandbox,
                "source": "cursor agent --help" if help_text else "unknown",
            },
            "model_selection": {
                "supported": has_model,
                "source": "cursor agent --help" if help_text else "unknown",
            },
            "cloud_mode": {
                "supported": "--cloud" in help_text,
                "source": "cursor agent --help" if help_text else "unknown",
                "enabled_by_opencobalt": False,
            },
            "credential_auth": {
                "supported": "--api-key" in help_text or "CURSOR_API_KEY" in help_text,
                "source": "cursor agent --help" if help_text else "unknown",
                "stored_by_opencobalt": False,
            },
        }
        return self._capabilities

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        raw = self.capabilities()
        available = self._display_path() is not None
        supports_noninteractive = self.supports_non_interactive()
        limitations: list[str] = []

        if not available:
            limitations.append("Cursor app or cursor executable not found")
        elif raw["bundled_cli"]["supported"] is False and raw["path_binary"]["supported"] is False:
            limitations.append("Cursor app detected, but no executable agent CLI was found")
        if available and not supports_noninteractive:
            limitations.append("receipt-compatible cursor agent --print plan mode not discovered")
        if available:
            limitations.extend(
                [
                    "execution is limited to cursor agent --print --mode plan",
                    "cloud mode is not enabled by OpenCobalt",
                    "force, browser, MCP auto-approval, login, logout, and API-key flags are not used",
                    "Cursor credentials and account state remain outside OpenCobalt",
                ]
            )

        if not available:
            level = "unavailable"
        elif supports_noninteractive:
            level = "partial"
        elif raw["macos_app"]["supported"] is True:
            level = "partial"
        else:
            level = "untrusted"

        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            executable_path=self._display_path(),
            available=available,
            capabilities=_supported_capability_names(raw),
            supported_artifact_types=list(self.supported_artifact_types),
            supports_dry_run=True,
            supports_noninteractive=supports_noninteractive,
            supports_json_output=bool(raw["json_output"]["supported"]),
            requires_network=True,
            requires_credentials=True,
            max_safe_risk=self.max_safe_risk if available else "green",
            limitations=limitations,
            verifiability_level=level,  # type: ignore[arg-type]
            capability_details=raw,
        ).with_hash()

    def supports_non_interactive(self) -> bool:
        caps = self.capabilities()
        return bool(
            self._execution_cli()
            and caps.get("agent_subcommand", {}).get("supported") is True
            and caps.get("non_interactive_print", {}).get("supported") is True
            and caps.get("read_only_plan_mode", {}).get("supported") is True
        )

    def default_timeout_seconds(self) -> int:
        return 600

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        opts = options or CommandOptions()
        if opts.dangerously_skip_permissions or opts.allow_dangerously_skip_permissions:
            raise ValueError("Cursor adapter does not support unsafe permission bypass")
        executable = self._execution_cli()
        if executable is None:
            raise ValueError("Cursor executable not found")
        if not self.supports_non_interactive():
            raise ValueError("Cursor agent --print plan mode was not discovered")
        caps = self.capabilities()
        argv = [
            executable,
            "agent",
            "--print",
            "--mode",
            "plan",
            "--output-format",
            "text",
        ]
        if opts.sandbox:
            if caps.get("sandbox_flag", {}).get("supported") is not True:
                raise ValueError("Cursor sandbox flag was not discovered")
            argv.extend(["--sandbox", "enabled"])
        if opts.model:
            if caps.get("model_selection", {}).get("supported") is not True:
                raise ValueError("Cursor model selection was not discovered")
            argv.extend(["--model", opts.model])
        argv.append("--")
        argv.append(task)
        return argv


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
    CursorAdapter.runtime_id: CursorAdapter,
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
