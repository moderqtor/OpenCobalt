"""Agent registry -- maps agent names to instances."""

from __future__ import annotations

from ..core.models import AgentProfile
from .base_agent import BaseAgent
from .code_reviewer import CodeReviewerAgent
from .context_builder import ContextBuilderAgent
from .summarizer import SummarizerAgent
from .tagger import TaggerAgent

REGISTRY: dict[str, BaseAgent] = {
    "summarizer": SummarizerAgent(),
    "tagger": TaggerAgent(),
    "code-reviewer": CodeReviewerAgent(),
    "context-builder": ContextBuilderAgent(),
}


def list_agents() -> list[AgentProfile]:
    """Return agent profiles sorted by name."""
    return sorted(
        (agent.profile for agent in REGISTRY.values()),
        key=lambda p: p.name,
    )


def get_agent(name: str) -> BaseAgent | None:
    """Return the agent instance for the given name, or None if not found."""
    return REGISTRY.get(name)
