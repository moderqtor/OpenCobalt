"""Integration for Cursor -- AI-native code editor."""

from __future__ import annotations

from .base_integration import BaseIntegration


class CursorIntegration(BaseIntegration):
    name = "cursor"
    description = "AI-native code editor (UI, frontend, editor workflows)"
    source_url = "https://www.cursor.com"
    tier = "manager"
    capabilities = ["ui", "editor", "frontend", "component", "style"]

    def install_check(self) -> bool:
        # Cursor does not expose a PATH binary; detection is OS-specific.
        return False

    def integration_status(self) -> str:
        return "available"

    def invoke(self, task: str) -> str:
        return f"cursor -- open project and use AI panel for: {task[:60]} (stub)"
