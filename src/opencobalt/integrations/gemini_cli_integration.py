"""Integration for Gemini CLI -- Google's long-context AI tool."""

from __future__ import annotations

import shutil

from .base_integration import BaseIntegration


class GeminiCLIIntegration(BaseIntegration):
    name = "gemini-cli"
    description = "Long-context AI CLI by Google (codebase-wide analysis)"
    source_url = "https://github.com/google-gemini/gemini-cli"
    tier = "executive"
    capabilities = ["long-context", "search", "analyze", "audit"]

    def install_check(self) -> bool:
        return shutil.which("gemini") is not None

    def invoke(self, task: str) -> str:
        return f"gemini '{task[:60]}' (stub -- run manually if gemini-cli is installed)"
