"""Integration awareness for OpenAI Codex CLI."""

from __future__ import annotations

import shutil

from .base_integration import BaseIntegration


class CodexCliIntegration(BaseIntegration):
    name = "codex-cli"
    description = (
        "OpenAI Codex CLI awareness. Runtime execution requires the separate "
        "receipt-backed codex-cli adapter."
    )
    source_url = "https://github.com/openai/codex"
    tier = "manager"
    capabilities = ["tests", "lint", "review", "cleanup", "editor-tasks", "adapter-aware"]

    def install_check(self) -> bool:
        return shutil.which("codex") is not None

    def invoke(self, task: str) -> str:
        return (
            "codex-cli integration stub. Runtime execution is only supported "
            "through the receipt-backed runtime adapter if `opencobalt adapters "
            f"inspect codex-cli` discovers a safe local surface: {task[:60]}"
        )
