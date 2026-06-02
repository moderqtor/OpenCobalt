"""Skill that generates a unified diff between two text strings."""

from __future__ import annotations

import difflib

from opencobalt.skills.base_skill import BaseSkill, SkillResult


class DiffWriter(BaseSkill):
    name = "diff-writer"
    description = "Generate a unified diff between two text strings"
    compatible_agents: list[str] = ["code-reviewer"]

    def run(  # type: ignore[override]
        self,
        original: str,
        modified: str,
        label: str = "change",
        **kwargs,
    ) -> SkillResult:
        if not isinstance(original, str) or not isinstance(modified, str):
            return SkillResult(
                skill_name=self.name,
                success=False,
                output=None,
                error="Both 'original' and 'modified' must be strings",
            )

        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)

        diff_lines = list(
            difflib.unified_diff(
                original_lines,
                modified_lines,
                fromfile=f"a/{label}",
                tofile=f"b/{label}",
            )
        )

        diff_string = "".join(diff_lines)
        additions = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

        return SkillResult(
            skill_name=self.name,
            success=True,
            output={"diff": diff_string, "additions": additions, "deletions": deletions},
        )
