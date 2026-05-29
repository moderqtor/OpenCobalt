"""Abstract base class for all OpenCobalt agents."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.models import AgentProfile


class BaseAgent(ABC):
    """Base class every concrete agent must subclass."""

    profile: AgentProfile  # class-level attribute each subclass sets

    @abstractmethod
    def run(self, task: str, *, dry_run: bool = False) -> str:
        """Execute the agent's task and return a result string.

        Args:
            task: Natural language description of the work.
            dry_run: If True, return a description of what would happen without
                     actually performing any external calls.
        """
        ...

    @property
    def name(self) -> str:
        return self.profile.name

    @property
    def tier(self) -> str:
        return self.profile.tier

    @property
    def capabilities(self) -> list[str]:
        return self.profile.capabilities
