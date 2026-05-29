"""Base class and profile model for all OpenCobalt integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class IntegrationProfile(BaseModel):
    name: str
    description: str
    source_url: str
    installed: bool = False


class BaseIntegration(ABC):
    name: str  # class attribute
    description: str  # class attribute
    source_url: str  # class attribute

    @abstractmethod
    def install_check(self) -> bool:
        """Return True if the external tool is available on PATH."""
        ...

    @abstractmethod
    def invoke(self, task: str) -> str:
        """Return a string describing what would happen (stub -- does not execute)."""
        ...

    def profile(self) -> IntegrationProfile:
        return IntegrationProfile(
            name=self.name,
            description=self.description,
            source_url=self.source_url,
            installed=self.install_check(),
        )
