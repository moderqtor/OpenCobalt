"""Integration registry for OpenCobalt.

Holds all registered integrations. Each integration is a slot for an
external tool -- adding it here does not install or depend on that tool.
"""

from __future__ import annotations

from .aider_integration import AiderIntegration
from .antigravity_integration import AntigravityIntegration
from .base_integration import BaseIntegration, IntegrationProfile
from .claude_code_integration import ClaudeCodeIntegration
from .context7_integration import Context7Integration
from .cursor_integration import CursorIntegration
from .gemini_cli_integration import GeminiCLIIntegration
from .ollama_integration import OllamaIntegration

REGISTRY: dict[str, BaseIntegration] = {
    "aider": AiderIntegration(),
    "antigravity-cli": AntigravityIntegration(),
    "claude-code": ClaudeCodeIntegration(),
    "context7": Context7Integration(),
    "cursor": CursorIntegration(),
    "gemini-cli": GeminiCLIIntegration(),
    "ollama": OllamaIntegration(),
}


def list_integrations() -> list[IntegrationProfile]:
    """Return a profile for every registered integration."""
    return [integration.profile() for integration in REGISTRY.values()]


def get_integration(name: str) -> BaseIntegration | None:
    """Return the integration with the given name, or None if not found."""
    return REGISTRY.get(name)
