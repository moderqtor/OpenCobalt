"""Code reviewer agent -- manager tier, uses file-reader skill, flags for escalation."""

from __future__ import annotations

from pathlib import Path

from ..core.models import AgentProfile
from ..skills.registry import get_skill
from .base_agent import BaseAgent

_GENERIC_FINDINGS = [
    "Check all public functions have descriptive docstrings.",
    "Verify error paths raise or return a typed result rather than returning None silently.",
    "Review imports for unused entries (run: ruff check --select F401).",
    "Confirm any mutable default arguments use Field(default_factory=...) or None.",
]


class CodeReviewerAgent(BaseAgent):
    """Manager-tier agent that reviews code and flags items for escalation.

    When given a file path, uses the file-reader skill to read it and computes
    real metrics (line count, function count, class count). Stub findings are
    augmented with actual file statistics.
    """

    compatible_skills: list[str] = ["file-reader", "diff-writer"]

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
            return "[dry-run] code-reviewer: would read file via file-reader skill, compute metrics, flag for escalation"

        # Attempt to treat the task as a file path
        file_result = None
        candidate = Path(task.strip())
        if candidate.suffix in {".py", ".ts", ".tsx", ".js", ".jsx"}:
            reader = get_skill("file-reader")
            if reader is not None:
                file_result = reader.run(path=str(candidate))

        if file_result and file_result.success:
            content: str = file_result.output.get("content", "")
            size: int = file_result.output.get("size", 0)
            lines = content.splitlines()
            fn_count = sum(1 for ln in lines if ln.lstrip().startswith("def "))
            cls_count = sum(1 for ln in lines if ln.lstrip().startswith("class "))
            comment_count = sum(1 for ln in lines if ln.lstrip().startswith("#"))

            header = f"Code review: {candidate}\n{'=' * 60}\n"
            metrics = (
                f"File metrics\n"
                f"  lines      : {len(lines)}\n"
                f"  functions  : {fn_count}\n"
                f"  classes    : {cls_count}\n"
                f"  comments   : {comment_count}\n"
                f"  size       : {size} bytes\n"
                f"\n"
            )

            # Generate contextual findings based on actual metrics
            findings = []
            if fn_count > 0 and comment_count < fn_count:
                findings.append(
                    f"[medium] {fn_count} function(s), {comment_count} comment line(s). "
                    "Consider adding docstrings to undocumented functions."
                )
            if len(lines) > 200:
                findings.append(
                    f"[low] File is {len(lines)} lines. Consider splitting into smaller modules "
                    "if responsibilities are distinct."
                )
            for f in _GENERIC_FINDINGS:
                findings.append(f"[low] {f}")

            body = "\n".join(f"Finding {i + 1}\n  {f}\n" for i, f in enumerate(findings[:4]))
            footer = (
                "\nEscalation note: medium/high findings should be reviewed by an "
                "executive-tier tool before automated changes are applied.\n"
            )
            return header + metrics + body + footer

        # Fallback: no file path or unreadable -- generic review
        header = f"Code review: {task[:80]}\n{'=' * 60}\n"
        body = "\n".join(f"Finding {i + 1}\n  [low] {f}\n" for i, f in enumerate(_GENERIC_FINDINGS))
        footer = "\nEscalation note: forward high-severity findings to an executive-tier tool.\n"
        return header + body + footer
