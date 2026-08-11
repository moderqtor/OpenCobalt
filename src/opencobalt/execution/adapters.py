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
    isolates_answer_only_inference: bool = False

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
_CLAUDE_HELP_TIMEOUT_SECONDS = 5
_CODEX_HELP_TIMEOUT_SECONDS = 5


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
                "supported": False,
                "source": "cursor agent --help" if help_text else "unknown",
                "advertised_by_cursor": "--cloud" in help_text,
                "enabled_by_opencobalt": False,
            },
            "credential_auth": {
                "supported": False,
                "source": "cursor agent --help" if help_text else "unknown",
                "advertised_by_cursor": "--api-key" in help_text
                or "CURSOR_API_KEY" in help_text,
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


class ClaudeCodeAdapter(RuntimeAdapter):
    """Claude Code CLI. Limited to local help-proven print plan mode."""

    runtime_id = "claude-code"
    display_name = "Claude Code"
    executable = "claude"
    requires_network = True
    requires_credentials = True
    max_safe_risk = "green"
    verifiability_level = "partial"
    supports_json_output = True

    def __init__(
        self,
        *,
        help_text: str | None = None,
        version_text: str | None = None,
    ) -> None:
        self._help_text = help_text
        self._version_text = version_text
        self._capabilities: dict[str, Any] | None = None

    def _path_binary(self) -> str | None:
        found = shutil.which(self.executable)
        return found if _is_executable(found) else None

    def _help(self) -> str:
        if self._help_text is not None:
            return self._help_text
        executable = self._path_binary()
        if executable is None:
            return ""
        try:
            result = subprocess.run(
                [executable, "--help"],
                capture_output=True,
                text=True,
                timeout=_CLAUDE_HELP_TIMEOUT_SECONDS,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return ""
        return "\n".join(part for part in (result.stdout, result.stderr) if part)

    def _version(self) -> str | None:
        if self._version_text is not None:
            return self._version_text or None
        executable = self._path_binary()
        if executable is None:
            return None
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=_CLAUDE_HELP_TIMEOUT_SECONDS,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return None
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        return output or None

    def capabilities(self) -> dict[str, Any]:
        if self._capabilities is not None:
            return self._capabilities

        path_binary = self._path_binary()
        help_text = self._help() if path_binary else ""
        version = self._version() if path_binary else None
        has_print = "--print" in help_text or "-p, --print" in help_text
        has_output_format = "--output-format" in help_text
        has_text_output = has_output_format and "text" in help_text
        has_permission_mode = "--permission-mode" in help_text
        has_plan_mode = has_permission_mode and "plan" in help_text
        has_safe_mode = "--safe-mode" in help_text
        has_no_chrome = "--no-chrome" in help_text
        has_no_session = "--no-session-persistence" in help_text
        has_strict_mcp = "--strict-mcp-config" in help_text
        has_mcp_config = "--mcp-config" in help_text
        has_model = "--model" in help_text

        self._capabilities = {
            "path_binary": {
                "supported": path_binary is not None,
                "source": "PATH",
                "path": path_binary,
            },
            "version": {
                "supported": version is not None,
                "source": "claude --version" if version else "unknown",
                "value": version,
            },
            "help_output": {
                "supported": bool(help_text),
                "source": "claude --help" if help_text else "unknown",
            },
            "non_interactive_print": {
                "supported": has_print,
                "source": "claude --help" if help_text else "unknown",
            },
            "text_output": {
                "supported": has_text_output,
                "source": "claude --help" if help_text else "unknown",
            },
            "json_output": {
                "supported": has_output_format and "json" in help_text,
                "source": "claude --help" if help_text else "unknown",
            },
            "plan_permission_mode": {
                "supported": has_plan_mode,
                "source": "claude --help" if help_text else "unknown",
            },
            "no_session_persistence": {
                "supported": has_no_session,
                "source": "claude --help" if help_text else "unknown",
            },
            "safe_mode": {
                "supported": has_safe_mode,
                "source": "claude --help" if help_text else "unknown",
            },
            "no_chrome": {
                "supported": has_no_chrome,
                "source": "claude --help" if help_text else "unknown",
            },
            "strict_mcp_config": {
                "supported": has_strict_mcp,
                "source": "claude --help" if help_text else "unknown",
            },
            "empty_mcp_config": {
                "supported": has_strict_mcp and has_mcp_config,
                "source": "claude --help" if help_text else "unknown",
            },
            "model_selection": {
                "supported": has_model,
                "source": "claude --help" if help_text else "unknown",
            },
            "dangerous_permission_bypass": {
                "supported": False,
                "source": "claude --help" if help_text else "unknown",
                "advertised_by_claude": "--dangerously-skip-permissions" in help_text
                or "--allow-dangerously-skip-permissions" in help_text
                or "bypassPermissions" in help_text,
                "enabled_by_opencobalt": False,
            },
            "credential_auth": {
                "supported": False,
                "source": "claude --help" if help_text else "unknown",
                "advertised_by_claude": "auth" in help_text
                or "ANTHROPIC_API_KEY" in help_text
                or "setup-token" in help_text,
                "stored_by_opencobalt": False,
            },
            "tool_allowlist": {
                "supported": False,
                "source": "claude --help" if help_text else "unknown",
                "advertised_by_claude": "--allowedTools" in help_text
                or "--allowed-tools" in help_text,
                "enabled_by_opencobalt": False,
            },
            "tool_denylist": {
                "supported": False,
                "source": "claude --help" if help_text else "unknown",
                "advertised_by_claude": "--disallowedTools" in help_text
                or "--disallowed-tools" in help_text,
                "enabled_by_opencobalt": False,
            },
            "spend_cap": {
                "supported": False,
                "source": "claude --help" if help_text else "unknown",
                "advertised_by_claude": "--max-budget-usd" in help_text,
                "enabled_by_opencobalt": False,
            },
            "browser_control": {
                "supported": False,
                "source": "claude --help" if help_text else "unknown",
                "advertised_by_claude": "--chrome" in help_text,
                "enabled_by_opencobalt": False,
            },
            "mcp_management": {
                "supported": False,
                "source": "claude --help" if help_text else "unknown",
                "advertised_by_claude": " mcp " in f" {help_text} "
                or "MCP" in help_text,
                "enabled_by_opencobalt": False,
            },
        }
        return self._capabilities

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        raw = self.capabilities()
        executable = raw["path_binary"]["path"]
        available = executable is not None
        supports_noninteractive = self.supports_non_interactive()
        limitations: list[str] = []

        if not available:
            limitations.append("Claude executable not found: claude")
        elif not raw["help_output"]["supported"]:
            limitations.append(
                "Claude Code help output not discovered; runtime support is discovery-only"
            )
        if available and not supports_noninteractive:
            limitations.append("safe Claude Code --print plan mode was not discovered")
        if available:
            limitations.extend(
                [
                    "execution is limited to claude --print with permission-mode plan",
                    "Claude Code may require network and credentials outside OpenCobalt",
                    "OpenCobalt policy gates remain authoritative",
                    "dangerous permission bypass modes are not used",
                    "credential, auth, token, browser-control, MCP auto-approval, deploy, publish, spend, and message paths are not used",
                ]
            )

        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            adapter_version=raw["version"]["value"],
            executable_path=executable,
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
            verifiability_level="partial" if available else "unavailable",
            capability_details=raw,
        ).with_hash()

    def supports_non_interactive(self) -> bool:
        caps = self.capabilities()
        return bool(
            caps.get("path_binary", {}).get("supported") is True
            and caps.get("non_interactive_print", {}).get("supported") is True
            and caps.get("text_output", {}).get("supported") is True
            and caps.get("plan_permission_mode", {}).get("supported") is True
        )

    def default_timeout_seconds(self) -> int:
        return 600

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        opts = options or CommandOptions()
        if opts.dangerously_skip_permissions or opts.allow_dangerously_skip_permissions:
            raise ValueError("Claude Code adapter does not support unsafe permission bypass")
        if opts.sandbox:
            raise ValueError("Claude Code adapter does not expose sandbox mode")
        executable = self._path_binary()
        if executable is None:
            raise ValueError("Claude executable not found")
        if not self.supports_non_interactive():
            raise ValueError("safe Claude Code --print plan mode was not discovered")
        caps = self.capabilities()
        argv = [
            executable,
            "--print",
            "--output-format",
            "text",
            "--permission-mode",
            "plan",
        ]
        if opts.model:
            if caps.get("model_selection", {}).get("supported") is not True:
                raise ValueError("Claude Code model selection was not discovered")
            argv.extend(["--model", opts.model])
        if caps.get("no_session_persistence", {}).get("supported") is True:
            argv.append("--no-session-persistence")
        if caps.get("safe_mode", {}).get("supported") is True:
            argv.append("--safe-mode")
        if caps.get("no_chrome", {}).get("supported") is True:
            argv.append("--no-chrome")
        if caps.get("empty_mcp_config", {}).get("supported") is True:
            argv.extend(["--strict-mcp-config", "--mcp-config", "{}"])
        argv.append(f"OpenCobalt read-only planning request:\n{task}")
        return argv


class CodexCliAdapter(RuntimeAdapter):
    """Codex CLI. Limited to local help-proven read-only exec mode."""

    runtime_id = "codex-cli"
    display_name = "Codex CLI"
    executable = "codex"
    requires_network = True
    requires_credentials = True
    max_safe_risk = "green"
    verifiability_level = "partial"
    supports_json_output = True

    def __init__(
        self,
        *,
        help_text: str | None = None,
        exec_help_text: str | None = None,
        version_text: str | None = None,
    ) -> None:
        self._help_text = help_text
        self._exec_help_text = exec_help_text
        self._version_text = version_text
        self._capabilities: dict[str, Any] | None = None

    def _path_binary(self) -> str | None:
        found = shutil.which(self.executable)
        return found if _is_executable(found) else None

    def _help(self) -> str:
        if self._help_text is not None:
            return self._help_text
        executable = self._path_binary()
        if executable is None:
            return ""
        try:
            result = subprocess.run(
                [executable, "--help"],
                capture_output=True,
                text=True,
                timeout=_CODEX_HELP_TIMEOUT_SECONDS,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return ""
        return "\n".join(part for part in (result.stdout, result.stderr) if part)

    def _exec_help(self) -> str:
        if self._exec_help_text is not None:
            return self._exec_help_text
        executable = self._path_binary()
        if executable is None:
            return ""
        try:
            result = subprocess.run(
                [executable, "exec", "--help"],
                capture_output=True,
                text=True,
                timeout=_CODEX_HELP_TIMEOUT_SECONDS,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return ""
        return "\n".join(part for part in (result.stdout, result.stderr) if part)

    def _version(self) -> str | None:
        if self._version_text is not None:
            return self._version_text or None
        executable = self._path_binary()
        if executable is None:
            return None
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=_CODEX_HELP_TIMEOUT_SECONDS,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return None
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        return output or None

    def capabilities(self) -> dict[str, Any]:
        if self._capabilities is not None:
            return self._capabilities

        path_binary = self._path_binary()
        help_text = self._help() if path_binary else ""
        exec_help = self._exec_help() if path_binary else ""
        version = self._version() if path_binary else None
        combined_help = f"{help_text}\n{exec_help}"
        has_exec = "Run Codex non-interactively" in combined_help or "\n  exec" in help_text
        has_read_only_sandbox = "--sandbox" in combined_help and "read-only" in combined_help
        has_approval_never = "--ask-for-approval" in help_text and "never" in help_text
        has_json = "--json" in exec_help
        has_ephemeral = "--ephemeral" in exec_help
        has_ignore_user_config = "--ignore-user-config" in exec_help
        has_color_never = "--color" in exec_help and "never" in exec_help
        has_skip_git_repo_check = "--skip-git-repo-check" in exec_help
        has_model = "--model" in combined_help

        self._capabilities = {
            "path_binary": {
                "supported": path_binary is not None,
                "source": "PATH",
                "path": path_binary,
            },
            "version": {
                "supported": version is not None,
                "source": "codex --version" if version else "unknown",
                "value": version,
            },
            "help_output": {
                "supported": bool(help_text),
                "source": "codex --help" if help_text else "unknown",
            },
            "exec_help_output": {
                "supported": bool(exec_help),
                "source": "codex exec --help" if exec_help else "unknown",
            },
            "exec_subcommand": {
                "supported": has_exec,
                "source": "codex --help/codex exec --help" if combined_help.strip() else "unknown",
            },
            "read_only_sandbox": {
                "supported": has_read_only_sandbox,
                "source": "codex --help/codex exec --help" if combined_help.strip() else "unknown",
            },
            "approval_never": {
                "supported": has_approval_never,
                "source": "codex --help" if help_text else "unknown",
            },
            "json_events": {
                "supported": has_json,
                "source": "codex exec --help" if exec_help else "unknown",
            },
            "ephemeral_session": {
                "supported": has_ephemeral,
                "source": "codex exec --help" if exec_help else "unknown",
            },
            "ignore_user_config": {
                "supported": has_ignore_user_config,
                "source": "codex exec --help" if exec_help else "unknown",
            },
            "color_never": {
                "supported": has_color_never,
                "source": "codex exec --help" if exec_help else "unknown",
            },
            "skip_git_repo_check": {
                "supported": has_skip_git_repo_check,
                "source": "codex exec --help" if exec_help else "unknown",
            },
            "model_selection": {
                "supported": has_model,
                "source": "codex --help/codex exec --help" if combined_help.strip() else "unknown",
            },
            "dangerous_permission_bypass": {
                "supported": False,
                "source": "codex --help/codex exec --help" if combined_help.strip() else "unknown",
                "advertised_by_codex": "--dangerously-bypass-approvals-and-sandbox" in combined_help
                or "--dangerously-bypass-hook-trust" in combined_help
                or "danger-full-access" in combined_help,
                "enabled_by_opencobalt": False,
            },
            "credential_auth": {
                "supported": False,
                "source": "codex --help" if help_text else "unknown",
                "advertised_by_codex": "login" in help_text
                or "logout" in help_text
                or "auth" in help_text
                or "OPENAI_API_KEY" in combined_help,
                "stored_by_opencobalt": False,
            },
            "mcp_management": {
                "supported": False,
                "source": "codex --help" if help_text else "unknown",
                "advertised_by_codex": " mcp " in f" {help_text} " or "MCP" in combined_help,
                "enabled_by_opencobalt": False,
            },
            "network_search": {
                "supported": False,
                "source": "codex --help" if help_text else "unknown",
                "advertised_by_codex": "--search" in help_text,
                "enabled_by_opencobalt": False,
            },
            "remote_or_daemon": {
                "supported": False,
                "source": "codex --help" if help_text else "unknown",
                "advertised_by_codex": "app-server" in help_text
                or "remote-control" in help_text
                or "exec-server" in help_text
                or "mcp-server" in help_text,
                "enabled_by_opencobalt": False,
            },
            "repo_mutation_paths": {
                "supported": False,
                "source": "codex --help" if help_text else "unknown",
                "advertised_by_codex": "apply" in help_text
                or "cloud" in help_text
                or "update" in help_text,
                "enabled_by_opencobalt": False,
            },
        }
        return self._capabilities

    def discover_capabilities(self) -> RuntimeCapabilitySnapshot:
        raw = self.capabilities()
        executable = raw["path_binary"]["path"]
        available = executable is not None
        supports_noninteractive = self.supports_non_interactive()
        limitations: list[str] = []

        if not available:
            limitations.append("Codex executable not found: codex")
        elif not raw["help_output"]["supported"]:
            limitations.append(
                "Codex help output not discovered; runtime support is discovery-only"
            )
        if available and not supports_noninteractive:
            limitations.append("safe codex exec read-only invocation was not discovered")
        if available:
            limitations.extend(
                [
                    "execution is limited to codex exec with sandbox read-only and approval policy never",
                    "Codex may require network and credentials outside OpenCobalt",
                    "OpenCobalt policy gates remain authoritative",
                    "dangerous permission bypass modes are not used",
                    "credential, login, logout, MCP management, browser/app-server, remote-control, cloud/apply/update, deploy, publish, spend, message, and web search paths are not used",
                ]
            )

        return RuntimeCapabilitySnapshot(
            adapter_id=self.runtime_id,
            adapter_name=self.display_name,
            adapter_version=raw["version"]["value"],
            executable_path=executable,
            available=available,
            capabilities=_supported_capability_names(raw),
            supported_artifact_types=list(self.supported_artifact_types),
            supports_dry_run=True,
            supports_noninteractive=supports_noninteractive,
            supports_json_output=bool(raw["json_events"]["supported"]),
            requires_network=True,
            requires_credentials=True,
            max_safe_risk=self.max_safe_risk if available else "green",
            limitations=limitations,
            verifiability_level="partial" if available else "unavailable",
            capability_details=raw,
        ).with_hash()

    def supports_non_interactive(self) -> bool:
        caps = self.capabilities()
        return bool(
            caps.get("path_binary", {}).get("supported") is True
            and caps.get("exec_subcommand", {}).get("supported") is True
            and caps.get("read_only_sandbox", {}).get("supported") is True
            and caps.get("approval_never", {}).get("supported") is True
        )

    def default_timeout_seconds(self) -> int:
        return 600

    def build_command(self, task: str, options: CommandOptions | None = None) -> list[str]:
        opts = options or CommandOptions()
        if opts.dangerously_skip_permissions or opts.allow_dangerously_skip_permissions:
            raise ValueError("Codex CLI adapter does not support unsafe permission bypass")
        executable = self._path_binary()
        if executable is None:
            raise ValueError("Codex executable not found")
        if not self.supports_non_interactive():
            raise ValueError("safe codex exec read-only invocation was not discovered")
        caps = self.capabilities()
        argv = [executable]
        if opts.model:
            if caps.get("model_selection", {}).get("supported") is not True:
                raise ValueError("Codex model selection was not discovered")
            argv.extend(["--model", opts.model])
        argv.extend(
            [
                "--sandbox",
                "read-only",
                "--ask-for-approval",
                "never",
                "exec",
            ]
        )
        if caps.get("json_events", {}).get("supported") is True:
            argv.append("--json")
        if caps.get("skip_git_repo_check", {}).get("supported") is True:
            argv.append("--skip-git-repo-check")
        if caps.get("ephemeral_session", {}).get("supported") is True:
            argv.append("--ephemeral")
        if caps.get("ignore_user_config", {}).get("supported") is True:
            argv.append("--ignore-user-config")
        if caps.get("color_never", {}).get("supported") is True:
            argv.extend(["--color", "never"])
        argv.append(f"OpenCobalt read-only planning request:\n{task}")
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
    isolates_answer_only_inference = True

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
    isolates_answer_only_inference = True

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
    ClaudeCodeAdapter.runtime_id: ClaudeCodeAdapter,
    CodexCliAdapter.runtime_id: CodexCliAdapter,
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
