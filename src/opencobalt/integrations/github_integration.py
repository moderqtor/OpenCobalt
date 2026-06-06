"""Integration for GitHub CLI -- PR creation, issue linking, branch management."""

from __future__ import annotations

import shutil

from .base_integration import BaseIntegration


class GitHubIntegration(BaseIntegration):
    name = "github-cli"
    description = "GitHub CLI (gh) for PR creation, issue linking, and repo management"
    source_url = "https://github.com/cli/cli"
    tier = "manager"
    capabilities = ["pr-create", "issue-link", "branch", "review"]

    def install_check(self) -> bool:
        return shutil.which("gh") is not None

    def invoke(self, task: str) -> str:
        return f"gh pr create --title '{task[:60]}' (stub -- run manually if gh is installed)"
