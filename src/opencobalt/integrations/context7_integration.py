"""Integration for Context7 -- live docs MCP server by Upstash."""

from __future__ import annotations

from .base_integration import BaseIntegration


class Context7Integration(BaseIntegration):
    name = "context7"
    description = "Live library documentation via MCP (Upstash Context7)"
    source_url = "https://github.com/upstash/context7"
    tier = "manager"
    capabilities = ["docs", "search", "mcp", "library-context"]

    def install_check(self) -> bool:
        # Context7 runs as an MCP server; no PATH binary to check.
        return False

    def integration_status(self) -> str:
        return "available"

    def invoke(self, task: str) -> str:
        return f"context7 MCP -- resolve library docs for: {task[:60]} (stub)"
