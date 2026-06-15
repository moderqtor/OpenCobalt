"""Integration registry for OpenCobalt.

Holds all registered integrations. Each integration is a slot for an
external tool -- adding it here does not install or depend on that tool.
"""

from __future__ import annotations

import warnings

from .aider_integration import AiderIntegration
from .antigravity_integration import AntigravityIntegration
from .base_integration import BaseIntegration, IntegrationProfile
from .claude_code_integration import ClaudeCodeIntegration
from .codex_cli_integration import CodexCliIntegration
from .context7_integration import Context7Integration
from .cursor_integration import CursorIntegration
from .github_integration import GitHubIntegration
from .obsidian_integration import ObsidianIntegration
from .ollama_integration import OllamaIntegration

REGISTRY: dict[str, BaseIntegration] = {
    "aider": AiderIntegration(),
    "claude-code": ClaudeCodeIntegration(),
    "codex-cli": CodexCliIntegration(),
    "context7": Context7Integration(),
    "cursor": CursorIntegration(),
    "github-cli": GitHubIntegration(),
    "google-antigravity": AntigravityIntegration(),
    "obsidian": ObsidianIntegration(),
    "ollama": OllamaIntegration(),
}

_ALIASES: dict[str, str] = {
    "antigravity-cli": "google-antigravity",
}

_DEPRECATED_ALIASES: dict[str, str] = {
    "gemini-cli": "google-antigravity",
    "gemini_cli": "google-antigravity",
    "google-gemini-cli": "google-antigravity",
}


def list_integrations() -> list[IntegrationProfile]:
    """Return a profile for every registered integration."""
    return [integration.profile() for integration in REGISTRY.values()]


def resolve_integration_name(name: str) -> str | None:
    """Return the canonical integration name, warning for deprecated aliases."""
    if name in REGISTRY:
        return name
    if name in _ALIASES:
        return _ALIASES[name]
    if name in _DEPRECATED_ALIASES:
        canonical = _DEPRECATED_ALIASES[name]
        warnings.warn(
            f"Gemini CLI integration is legacy; use {canonical} with agy instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return canonical
    return None


def get_integration(name: str) -> BaseIntegration | None:
    """Return the integration with the given name, or None if not found."""
    canonical = resolve_integration_name(name)
    return REGISTRY.get(canonical) if canonical else None
