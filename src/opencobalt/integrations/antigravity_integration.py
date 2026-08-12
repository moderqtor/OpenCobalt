"""Integration for Google Antigravity CLI."""

from __future__ import annotations

import re
import shutil
import subprocess
import warnings
from copy import deepcopy
from typing import Any

from opencobalt.core.runtime_boundary import legacy_runtime_block_message

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
    "json_output": _capability(None, "unknown"),
    "stream_json_output": _capability(None, "unknown"),
    "json_schema": _capability(None, "unknown"),
    "reasoning_effort": _capability(None, "unknown"),
    "execution_mode": _capability(None, "unknown"),
    "conversation_resume": _capability(None, "unknown"),
    "disable_slash_commands": _capability(None, "unknown"),
    "print_timeout": _capability(None, "unknown"),
    "models_subcommand": _capability(None, "unknown"),
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

    if _help_has_flag(help_text, "--output-format"):
        _mark_help_flag_capability(capabilities, "json_output", "--output-format")
        if re.search(r"(?i)stream-json", help_text):
            _mark_runtime_capability(capabilities, "stream_json_output", "stream-json found in agy help")

    if _help_has_flag(help_text, "--json-schema"):
        _mark_help_flag_capability(capabilities, "json_schema", "--json-schema")

    if _help_has_flag(help_text, "--effort"):
        _mark_help_flag_capability(capabilities, "reasoning_effort", "--effort")

    if _help_has_flag(help_text, "--mode"):
        _mark_help_flag_capability(capabilities, "execution_mode", "--mode")

    if _help_has_flag(help_text, "--conversation"):
        _mark_help_flag_capability(capabilities, "conversation_resume", "--conversation")

    if _help_has_flag(help_text, "--disable-slash-commands"):
        _mark_help_flag_capability(
            capabilities, "disable_slash_commands", "--disable-slash-commands"
        )

    if _help_has_flag(help_text, "--print-timeout"):
        _mark_help_flag_capability(capabilities, "print_timeout", "--print-timeout")

    if re.search(r"(?im)^\s*models\b", help_text) or re.search(
        r"(?i)list available models", help_text
    ):
        _mark_runtime_capability(capabilities, "models_subcommand", "models subcommand found in agy help")
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
    output_format: str | None = None,
    effort: str | None = None,
    mode: str | None = None,
    json_schema: str | None = None,
    disable_slash_commands: bool = False,
    print_timeout: str | None = None,
    conversation_id: str | None = None,
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
    if output_format is not None:
        if output_format not in {"text", "json", "stream-json"}:
            raise ValueError("agy output format must be text, json, or stream-json")
        if output_format == "json" and not _capability_supported(capabilities, "json_output"):
            raise ValueError("agy --output-format json is not supported by discovered help")
        if output_format == "stream-json" and not _capability_supported(
            capabilities, "stream_json_output", "json_output"
        ):
            raise ValueError("agy --output-format stream-json is not supported by discovered help")
    if effort is not None:
        if effort not in {"low", "medium", "high"}:
            raise ValueError("agy --effort must be low, medium, or high")
        if not _capability_supported(capabilities, "reasoning_effort"):
            raise ValueError("agy --effort is not supported by discovered help")
    if mode is not None:
        if mode not in {"plan", "accept-edits"}:
            raise ValueError("agy --mode must be plan or accept-edits")
        if not _capability_supported(capabilities, "execution_mode"):
            raise ValueError("agy --mode is not supported by discovered help")
    if json_schema is not None and not _capability_supported(capabilities, "json_schema"):
        raise ValueError("agy --json-schema is not supported by discovered help")
    if disable_slash_commands and not _capability_supported(
        capabilities, "disable_slash_commands"
    ):
        raise ValueError("agy --disable-slash-commands is not supported by discovered help")
    if print_timeout is not None:
        if not re.fullmatch(r"\d+[smh](\d+[smh])?", print_timeout):
            raise ValueError("agy --print-timeout must be a bounded Go duration")
        if not _capability_supported(capabilities, "print_timeout"):
            raise ValueError("agy --print-timeout is not supported by discovered help")
    if conversation_id is not None:
        if (
            not conversation_id
            or conversation_id.startswith("-")
            or len(conversation_id) > 200
            or any(
                not (character.isalnum() or character in "-_")
                for character in conversation_id
            )
        ):
            raise ValueError("agy conversation id must be a bounded identifier")
        if not _capability_supported(capabilities, "conversation_resume"):
            raise ValueError("agy --conversation is not supported by discovered help")

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
    if mode is not None:
        command.extend(["--mode", mode])
    if output_format is not None:
        command.extend(["--output-format", output_format])
    if json_schema is not None:
        command.extend(["--json-schema", json_schema])
    if disable_slash_commands:
        command.append("--disable-slash-commands")
    if print_timeout is not None:
        command.extend(["--print-timeout", print_timeout])
    if conversation_id is not None:
        command.extend(["--conversation", conversation_id])
    if model is not None:
        command.extend(["--model", model])
    if effort is not None:
        command.extend(["--effort", effort])
    command.extend(["--print", prompt])
    return command


def build_antigravity_models_command(
    *,
    capabilities: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """Build argv for machine-readable model discovery without starting an agent turn."""
    if capabilities is not None and not _capability_supported(
        capabilities, "models_subcommand"
    ):
        raise ValueError("agy models is not supported by discovered help")
    if capabilities is not None and not _capability_supported(capabilities, "json_output"):
        raise ValueError("agy --output-format json is not supported by discovered help")
    return [_COMMAND, "--output-format", "json", "models"]


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
        _ = task
        return f"{legacy_runtime_block_message('google-antigravity')} (stub)"
