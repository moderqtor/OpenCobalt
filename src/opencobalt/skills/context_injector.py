"""Context injector skill -- builds a context snippet for a task."""

from __future__ import annotations

from pathlib import Path

from .base_skill import BaseSkill, SkillResult


class ContextInjector(BaseSkill):
    """Build a concise context snippet from a task description and project path.

    Collects README and top-level docs into a short snippet suitable for
    injecting into an agent prompt. Does not call any external service.
    """

    name = "context-injector"
    description = "Build a project context snippet from README and docs for a given task"
    compatible_agents: list[str] = ["context-builder", "summarizer", "code-reviewer"]

    def run(self, *, task: str = "", project_path: str = ".") -> SkillResult:
        try:
            root = Path(project_path).expanduser().resolve()
            lines: list[str] = []

            if task:
                lines.append(f"Task: {task}")
                lines.append("")

            readme = root / "README.md"
            if readme.exists():
                content = readme.read_text(encoding="utf-8", errors="replace")
                # Keep first 500 chars to stay token-lean
                excerpt = content[:500].strip()
                if excerpt:
                    lines.append("README (excerpt):")
                    lines.append(excerpt)
                    lines.append("")

            docs_dir = root / "docs"
            if docs_dir.is_dir():
                doc_names = sorted(p.name for p in docs_dir.glob("*.md"))
                if doc_names:
                    lines.append(f"Docs available: {', '.join(doc_names[:8])}")

            snippet = "\n".join(lines).strip()
            return SkillResult(
                skill_name=self.name,
                success=True,
                output={"snippet": snippet, "task": task, "project_path": str(root)},
            )
        except Exception as exc:
            return SkillResult(
                skill_name=self.name,
                success=False,
                output={},
                error=str(exc),
            )
