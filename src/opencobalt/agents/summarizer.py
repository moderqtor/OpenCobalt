"""Summarizer agent, worker tier with receipt-boundary fallback."""

from __future__ import annotations

from ..core.models import AgentProfile
from ..core.runtime_boundary import legacy_runtime_block_message
from .base_agent import BaseAgent


class SummarizerAgent(BaseAgent):
    """Worker-tier agent that summarizes text via Ollama."""

    compatible_skills: list[str] = ["context-injector"]

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
            return "[dry-run] summarizer: use opencobalt run --runtime ollama --dry-run"
        _ = task
        return legacy_runtime_block_message("ollama")
