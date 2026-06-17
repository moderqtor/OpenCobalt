"""Integration for Cursor -- AI-native code editor."""

from __future__ import annotations

import shutil
from pathlib import Path

from opencobalt.core.runtime_boundary import legacy_runtime_block_message

from .base_integration import BaseIntegration


def _default_app_paths() -> tuple[Path, ...]:
    return (
        Path("/Applications/Cursor.app"),
        Path.home() / "Applications" / "Cursor.app",
    )


class CursorIntegration(BaseIntegration):
    name = "cursor"
    description = (
        "AI-native code editor awareness. Runtime execution requires the "
        "separate receipt-backed cursor adapter."
    )
    source_url = "https://www.cursor.com"
    tier = "manager"
    capabilities = ["ui", "editor", "frontend", "component", "style", "adapter-aware"]

    def install_check(self) -> bool:
        return shutil.which("cursor") is not None or any(
            path.exists() for path in _default_app_paths()
        )

    def invoke(self, task: str) -> str:
        _ = task
        return f"{legacy_runtime_block_message('cursor')} (stub)"
