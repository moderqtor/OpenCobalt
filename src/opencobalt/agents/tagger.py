"""Tagger agent -- worker tier, Ollama stub."""

from __future__ import annotations

from ..core.models import AgentProfile
from .base_agent import BaseAgent


class TaggerAgent(BaseAgent):
    """Worker-tier agent that tags content via Ollama (stub)."""

    profile = AgentProfile(
        agent_id="tagger",
        name="tagger",
        tier="worker",
        capabilities=["tagging"],
        task_types=["tag"],
        local_only=True,
    )

    def run(self, task: str, *, dry_run: bool = False) -> str:
        if dry_run:
            return "[dry-run] tagger would process task via Ollama"
        return "Tags: [stub, draft, needs-review] (Ollama not called)"
