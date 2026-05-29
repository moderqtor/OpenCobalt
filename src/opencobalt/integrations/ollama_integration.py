"""Integration for Ollama -- local model inference."""

from __future__ import annotations

import subprocess

from .base_integration import BaseIntegration


class OllamaIntegration(BaseIntegration):
    name = "ollama"
    description = "Local model inference via Ollama"
    source_url = "https://github.com/ollama/ollama"

    def install_check(self) -> bool:
        """Return True if the ollama binary is present and responsive."""
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                timeout=3,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def invoke(self, task: str) -> str:
        """Return a stub description of what ollama would do with this task."""
        return f"ollama run llama3 '{task[:60]}' (stub -- Ollama not called directly)"
