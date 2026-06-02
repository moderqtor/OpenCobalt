"""Tagger agent -- worker tier, calls Ollama with fallback."""

from __future__ import annotations

import subprocess

from ..core.models import AgentProfile
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
            return "[dry-run] tagger: would call ollama run llama3 to generate tags"
        prompt = (
            f"Generate 3-5 single-word tags for this. "
            f"Output ONLY the tags separated by commas, nothing else: {task}"
        )
        try:
            result = subprocess.run(
                ["ollama", "run", "llama3", prompt],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                return f"Tags: {result.stdout.strip()}"
        except Exception:
            pass
        return "[fallback] Tags: task, review, draft (Ollama unavailable or timed out)"
