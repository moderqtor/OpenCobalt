"""Tagger agent, worker tier with receipt-boundary fallback."""

from __future__ import annotations

from ..core.models import AgentProfile
from ..core.runtime_boundary import legacy_runtime_block_message
from .base_agent import BaseAgent


class TaggerAgent(BaseAgent):
    """Worker-tier agent that tags content via Ollama."""

    compatible_skills: list[str] = ["file-reader"]

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
            return "[dry-run] tagger: use opencobalt run --runtime ollama --dry-run"
        _ = task
        return legacy_runtime_block_message("ollama")
