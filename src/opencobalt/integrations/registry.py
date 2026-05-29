"""Integration registry for OpenCobalt.

Holds all registered integrations. Each integration is a slot for an
external tool -- adding it here does not install or depend on that tool.
"""

from __future__ import annotations

from .aider_integration import AiderIntegration
from .base_integration import BaseIntegration, IntegrationProfile
from .ollama_integration import OllamaIntegration

REGISTRY: dict[str, BaseIntegration] = {
    "aider": AiderIntegration(),
    "ollama": OllamaIntegration(),
}


def list_integrations() -> list[IntegrationProfile]:
    """Return a profile for every registered integration."""
    return [integration.profile() for integration in REGISTRY.values()]


def get_integration(name: str) -> BaseIntegration | None:
    """Return the integration with the given name, or None if not found."""
    return REGISTRY.get(name)
