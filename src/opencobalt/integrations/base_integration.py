"""Base class and profile model for all OpenCobalt integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field

IntegrationStatus = Literal["active", "stub", "available"]


class IntegrationProfile(BaseModel):
    name: str
    description: str
    source_url: str
    installed: bool = False
    tier: str = "worker"
    capabilities: list[str] = Field(default_factory=list)
    integration_status: IntegrationStatus = "stub"


class BaseIntegration(ABC):
    name: str  # class attribute
    description: str  # class attribute
    source_url: str  # class attribute
    tier: str = "worker"  # class attribute; subclasses override
    capabilities: list[str] = []  # class attribute; subclasses override

    @abstractmethod
    def install_check(self) -> bool:
        """Return True if the external tool is available on PATH."""
        ...

    @abstractmethod
    def invoke(self, task: str) -> str:
        """Return a string describing what would happen (stub -- does not execute)."""
        ...

    def integration_status(self) -> IntegrationStatus:
        """Return 'active' when installed, 'stub' otherwise.

        Subclasses may override to return 'available' for tools that are
        downloadable but not checkable via PATH (e.g. GUI apps, MCP servers).
        """
        return "active" if self.install_check() else "stub"

    def profile(self) -> IntegrationProfile:
        return IntegrationProfile(
            name=self.name,
            description=self.description,
            source_url=self.source_url,
            installed=self.install_check(),
            tier=self.tier,
            capabilities=list(self.capabilities),
            integration_status=self.integration_status(),
        )
