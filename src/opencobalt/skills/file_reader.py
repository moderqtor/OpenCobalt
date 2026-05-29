"""Skill that reads text file contents from the filesystem."""

from __future__ import annotations

from pathlib import Path

from opencobalt.skills.base_skill import BaseSkill, SkillResult


class FileReader(BaseSkill):
    name = "file-reader"
    description = "Read file contents from the filesystem"

    def run(self, path: str, **kwargs) -> SkillResult:  # type: ignore[override]
        p = Path(path)

        if not p.exists():
            return SkillResult(
                skill_name=self.name,
                success=False,
                output=None,
                error=f"File not found: {path}",
            )

        try:
            content = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError, OSError) as exc:
            return SkillResult(
                skill_name=self.name,
                success=False,
                output=None,
                error=f"Cannot read file: {exc}",
            )

        size = p.stat().st_size
        return SkillResult(
            skill_name=self.name,
            success=True,
            output={"path": path, "content": content, "size": size},
        )
