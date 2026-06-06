"""Integration for Antigravity CLI -- Google's successor to Gemini CLI."""

from __future__ import annotations

import shutil

from .base_integration import BaseIntegration


class AntigravityIntegration(BaseIntegration):
    name = "antigravity-cli"
    description = "Antigravity CLI by Google (successor to Gemini CLI, long-context + code)"
    source_url = "https://antigravity.google/product/antigravity-cli"
    tier = "executive"
    capabilities = ["long-context", "search", "analyze", "multimodal"]

    def install_check(self) -> bool:
        return shutil.which("antigravity") is not None

    def invoke(self, task: str) -> str:
        return f"antigravity '{task[:60]}' (stub -- install antigravity-cli to enable)"
