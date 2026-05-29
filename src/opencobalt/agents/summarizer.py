"""Summarizer agent -- worker tier, calls Ollama with fallback."""

from __future__ import annotations

import subprocess

from ..core.models import AgentProfile
from .base_agent import BaseAgent


class SummarizerAgent(BaseAgent):
    """Worker-tier agent that summarizes text via Ollama."""

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
            return "[dry-run] summarizer: would call ollama run llama3 to summarize"
        prompt = f"Summarize this in 2-3 sentences: {task}"
        try:
            result = subprocess.run(
                ["ollama", "run", "llama3", prompt],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip()
        except Exception:
            pass
        return f"[fallback] Summary: {task[:120]}... (Ollama unavailable or timed out)"
