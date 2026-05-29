"""Code reviewer agent -- manager tier, flags for escalation."""

from __future__ import annotations

from ..core.models import AgentProfile
from .base_agent import BaseAgent

_STUB_FINDINGS = """\
Finding 1 [severity: low]
  Location: <file>:<line> (stub)
  Note: Unused variable detected. Remove or document its purpose.

Finding 2 [severity: medium]
  Location: <file>:<line> (stub)
  Note: Function lacks a docstring. Add one to describe inputs and return value.

Finding 3 [severity: high]
  Location: <file>:<line> (stub)
  Note: Error path returns None without signaling failure. Raise or return a typed result.

Escalation note: findings at high severity would be forwarded to an executive-tier
agent for final judgment before any automated fix is applied.
"""


class CodeReviewerAgent(BaseAgent):
    """Manager-tier agent that reviews code and flags items for escalation."""

    profile = AgentProfile(
        agent_id="code-reviewer",
        name="code-reviewer",
        tier="manager",
        capabilities=["review", "escalation"],
        task_types=["review"],
        requires_api_key=False,
    )

    def run(self, task: str, *, dry_run: bool = False) -> str:
        if dry_run:
            return "[dry-run] code-reviewer would analyze task and produce structured findings"
        header = f"Code review for: {task[:80]}\n{'=' * 60}\n"
        return header + _STUB_FINDINGS
