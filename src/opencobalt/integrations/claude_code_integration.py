"""Integration for Claude Code -- Anthropic's AI-native CLI."""

from __future__ import annotations

import shutil

from opencobalt.core.runtime_boundary import legacy_runtime_block_message

from .base_integration import BaseIntegration


class ClaudeCodeIntegration(BaseIntegration):
    name = "claude-code"
    description = "AI-native coding CLI by Anthropic (executive-tier tasks)"
    source_url = "https://github.com/anthropics/claude-code"
    tier = "executive"
    capabilities = ["architecture", "code", "review", "debug", "security"]

    def install_check(self) -> bool:
        return shutil.which("claude") is not None

    def invoke(self, task: str) -> str:
        _ = task
        return f"{legacy_runtime_block_message('claude-code')} (stub)"
