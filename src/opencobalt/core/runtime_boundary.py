"""Shared helpers for legacy external runtime execution blockers."""

from __future__ import annotations

from typing import Final

_RUNTIME_ALIASES: Final[dict[str, str]] = {
    "claude": "claude-code",
    "claude-code": "claude-code",
    "codex": "codex-cli",
    "codex-cli": "codex-cli",
    "cursor": "cursor",
    "antigravity": "google-antigravity",
    "antigravity-cli": "google-antigravity",
    "google-antigravity": "google-antigravity",
    "gemini": "google-antigravity",
    "gemini-cli": "google-antigravity",
    "gemini_cli": "google-antigravity",
    "google-gemini-cli": "google-antigravity",
    "agy": "google-antigravity",
    "ollama": "ollama",
    "aider": "aider",
}


def normalize_runtime_id(name: str) -> str | None:
    """Return the canonical adapter id for a known external runtime alias."""
    return _RUNTIME_ALIASES.get(name.strip().lower())


def legacy_runtime_block_message(name: str) -> str:
    """Message used when old helpers try to execute an external runtime."""
    runtime = normalize_runtime_id(name) or "<adapter-id>"
    return (
        f"[blocked] Direct {name} subprocess execution is blocked outside receipt-backed "
        "ExecutionEngine. Use "
        f"`opencobalt run \"TASK\" --runtime {runtime} --dry-run`."
    )


def legacy_runtime_block_message_for_runtime(runtime: str) -> str:
    """Message for call sites that already have a canonical runtime id."""
    return (
        f"[blocked] Direct {runtime} execution is blocked outside receipt-backed "
        "ExecutionEngine. Use "
        f"`opencobalt run \"TASK\" --runtime {runtime} --dry-run`."
    )
