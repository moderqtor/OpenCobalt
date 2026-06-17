"""Integration for aider -- AI pair programmer for code editing."""

from __future__ import annotations

import shutil

from opencobalt.core.runtime_boundary import legacy_runtime_block_message

from .base_integration import BaseIntegration


class AiderIntegration(BaseIntegration):
    name = "aider"
    description = "Code editing via aider (AI pair programmer)"
    source_url = "https://github.com/paul-gauthier/aider"

    def install_check(self) -> bool:
        """Return True if the aider binary is available on PATH."""
        return shutil.which("aider") is not None

    def invoke(self, task: str) -> str:
        """Return a stub pointing to the runtime adapter boundary."""
        _ = task
        return f"{legacy_runtime_block_message('aider')} (stub)"
