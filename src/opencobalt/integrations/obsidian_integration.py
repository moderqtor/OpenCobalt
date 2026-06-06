"""Integration for Obsidian -- read/write vault notes via local REST plugin."""

from __future__ import annotations

import shutil
from pathlib import Path

from .base_integration import BaseIntegration, IntegrationStatus


class ObsidianIntegration(BaseIntegration):
    name = "obsidian"
    description = "Obsidian vault integration (read/write notes via local REST API plugin)"
    source_url = "https://obsidian.md"
    tier = "manager"
    capabilities = ["notes", "knowledge-base", "export", "search"]

    def install_check(self) -> bool:
        mac_app = Path("/Applications/Obsidian.app")
        return mac_app.exists() or shutil.which("obsidian") is not None

    def integration_status(self) -> IntegrationStatus:
        return "available" if self.install_check() else "stub"

    def invoke(self, task: str) -> str:
        return (
            f"obsidian: create note '{task[:60]}' "
            "(requires local-rest-api plugin — see docs/INTEGRATIONS.md)"
        )
