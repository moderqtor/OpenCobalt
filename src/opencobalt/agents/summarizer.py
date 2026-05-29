"""Summarizer agent -- worker tier, Ollama stub."""

from __future__ import annotations

from ..core.models import AgentProfile
from .base_agent import BaseAgent


class SummarizerAgent(BaseAgent):
    """Worker-tier agent that summarizes text via Ollama (stub)."""

    profile = AgentProfile(
        agent_id="summarizer",
        name="summarizer",
        tier="worker",
        capabilities=["summarization"],
        task_types=["summarize"],
        local_only=True,
    )

    def run(self, task: str, *, dry_run: bool = False) -> str:
        if dry_run:
            return "[dry-run] summarizer would process task via Ollama"
        return f"Summary: {task[:80]}... (stub -- Ollama not called)"
