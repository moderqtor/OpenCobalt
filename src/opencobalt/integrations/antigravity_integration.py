"""Integration for Google Antigravity CLI."""

from __future__ import annotations

import re
import shutil
import subprocess
import warnings
from copy import deepcopy
from typing import Any

from .base_integration import BaseIntegration

_COMMAND = "agy"


def _capability(supported: bool | None, source: str, evidence: str = "", **metadata: Any) -> dict[str, Any]:
    capability = {"supported": supported, "source": source, "evidence": evidence}
    capability.update(metadata)
    return capability


ANTIGRAVITY_CAPABILITIES: dict[str, dict[str, bool | str | None]] = {
    "interactive_cli": _capability(None, "runtime_discovered"),
    "agent_runtime": _capability(True, "static", "Google Antigravity CLI is modeled as an agent runtime."),
    "multi_agent_orchestration": _capability(None, "unknown"),
    "artifact_generation": _capability(None, "unknown"),
    "browser_verification": _capability(None, "unknown"),
    "terminal_execution": _capability(None, "unknown"),
    "editor_context": _capability(None, "unknown"),
    "plugin_support": _capability(None, "unknown"),
    "skills_hooks_subagents": _capability(None, "unknown"),
    "subagent_protocol": _capability(None, "unknown"),
    "non_interactive_mode": _capability(None, "unknown"),
    "non_interactive_print": _capability(None, "unknown"),
    "model_selection": _capability(None, "unknown"),
    "terminal_sandbox": _capability(None, "unknown"),
    "sandbox_mode": _capability(None, "unknown"),
    "unsafe_skip_permissions": _capability(None, "unknown", allowed_by_default=False, risk="red"),
    "artifact_locations": _capability(None, "unknown"),
    "screenshot_capture": _capability(None, "unknown"),
    "sqlite_conversation_schema": _capability(None, "unknown"),
}


def _run_discovery_command(args: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return {"ok": False, "value": None, "error": f"{args[0]} not on PATH"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "value": None, "error": f"{' '.join(args)} timed out"}

    output = (result.stdout or result.stderr or "").strip()
    return {
        "ok": result.returncode == 0,
        "value": output if result.returncode == 0 else None,
        "error": "" if result.returncode == 0 else output,
    }


def _mark_runtime_capability(capabilities: dict[str, dict[str, bool | str | None]], key: str, evidence: str) -> None:
    capabilities[key] = _capability(True, "runtime_discovered", evidence)


def _mark_help_flag_capability(capabilities: dict[str, dict[str, Any]], key: str, flag: str, **metadata: Any) -> None:
    capabilities[key] = _capability(True, "runtime_discovered", f"{flag} found in agy help", **metadata)


def _help_has_flag(help_text: str, flag: str) -> bool:
    pattern = rf"(?<![\w-]){re.escape(flag)}(?![\w-])"
    return re.search(pattern, help_text) is not None


def _help_mentions_plugin(help_text: str) -> bool:
    return re.search(r"(?i)(?<![a-z])plugins?(?![a-z])", help_text) is not None


def _capabilities_from_help(help_text: str, installed: bool) -> dict[str, dict[str, bool | str | None]]:
    capabilities = deepcopy(ANTIGRAVITY_CAPABILITIES)
    capabilities["interactive_cli"] = _capability(
        installed,
        "runtime_discovered" if installed else "unknown",
        _COMMAND if installed else "",
    )
    if not help_text:
        return capabilities

    if _help_has_flag(help_text, "--print"):
        _mark_help_flag_capability(capabilities, "non_interactive_print", "--print")
        _mark_runtime_capability(capabilities, "non_interactive_mode", "--print")
    elif _help_has_flag(help_text, "--prompt"):
        _mark_runtime_capability(capabilities, "non_interactive_mode", "--prompt")

    if _help_has_flag(help_text, "--model"):
        _mark_help_flag_capability(capabilities, "model_selection", "--model")

    if _help_mentions_plugin(help_text):
        capabilities["plugin_support"] = _capability(
            True,
            "runtime_discovered",
            "plugin found in agy help",
        )

    if _help_has_flag(help_text, "--sandbox"):
        _mark_help_flag_capability(capabilities, "sandbox_mode", "--sandbox", risk="safety_enhancing")
        _mark_runtime_capability(capabilities, "terminal_sandbox", "--sandbox")

    if _help_has_flag(help_text, "--dangerously-skip-permissions"):
        _mark_help_flag_capability(
            capabilities,
            "unsafe_skip_permissions",
            "--dangerously-skip-permissions",
            allowed_by_default=False,
            risk="red",
        )
    return capabilities


def _capability_supported(capabilities: dict[str, dict[str, Any]] | None, *keys: str) -> bool:
    if capabilities is None:
        return True
    return any(capabilities.get(key, {}).get("supported") is True for key in keys)


def build_antigravity_command(
    prompt: str,
    *,
    model: str | None = None,
    sandbox: bool = False,
    dangerously_skip_permissions: bool = False,
    allow_dangerously_skip_permissions: bool = False,
    capabilities: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Build a default-safe agy argv without invoking the runtime."""
    if capabilities is not None and not _capability_supported(
        capabilities,
        "non_interactive_print",
        "non_interactive_mode",
    ):
        raise ValueError("agy --print is not supported by discovered help")
    if model is not None and not _capability_supported(capabilities, "model_selection"):
        raise ValueError("agy --model is not supported by discovered help")
    if sandbox and not _capability_supported(capabilities, "sandbox_mode", "terminal_sandbox"):
        raise ValueError("agy --sandbox is not supported by discovered help")

    command = [_COMMAND]
    if sandbox:
        command.append("--sandbox")
    if dangerously_skip_permissions and allow_dangerously_skip_permissions:
        warnings.warn(
            "--dangerously-skip-permissions auto-approves agy permission requests and is unsafe.",
            RuntimeWarning,
            stacklevel=2,
        )
        command.append("--dangerously-skip-permissions")
    if model is not None:
        command.extend(["--model", model])
    command.extend(["--print", prompt])
    return command


def discover_antigravity_runtime(ledger=None) -> dict[str, Any]:
    """Discover local agy runtime behavior without assuming undocumented flags."""
    path = shutil.which(_COMMAND)
    if not path:
        result = {
            "installed": False,
            "path": None,
            "version": {"ok": False, "value": None, "error": "agy not on PATH"},
            "help": {"ok": False, "value": "", "error": "agy not on PATH"},
            "capabilities": _capabilities_from_help("", installed=False),
        }
    else:
        version = _run_discovery_command([_COMMAND, "--version"])
        help_result = _run_discovery_command([_COMMAND, "--help"])
        help_text = help_result["value"] if help_result["ok"] and help_result["value"] else ""
        result = {
            "installed": True,
            "path": path,
            "version": version,
            "help": {**help_result, "value": help_text},
            "capabilities": _capabilities_from_help(help_text, installed=True),
        }

    if ledger is not None:
        from opencobalt.core.models import VerificationResult

        ledger.insert_verification_result(
            VerificationResult(
                command="opencobalt doctor antigravity",
                exit_code=0,
                passed=True,
                output_summary="Antigravity installed" if result["installed"] else "Antigravity missing",
                metadata={"integration": "google-antigravity", "diagnostic": result},
            )
        )
    return result


class AntigravityIntegration(BaseIntegration):
    name = "google-antigravity"
    display_name = "Google Antigravity CLI"
    command = _COMMAND
    vendor = "google"
    kind = "agent_runtime"
    status = "primary"
    description = "Google Antigravity CLI local agent runtime invoked with agy."
    source_url = "https://antigravity.google/product/antigravity-cli"
    tier = "executive"
    capabilities = ["agent-runtime", "interactive-cli", "artifact-workflows", "browser-workflows"]

    def install_check(self) -> bool:
        return shutil.which(self.command) is not None

    def invoke(self, task: str) -> str:
        return f"agy (stub -- task copied by OpenCobalt; direct execution is under active development: {task[:60]})"
