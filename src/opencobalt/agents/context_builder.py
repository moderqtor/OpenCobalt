"""Context builder agent -- deterministic, no model calls."""

from __future__ import annotations

from pathlib import Path

from ..core.models import AgentProfile
from .base_agent import BaseAgent


class ContextBuilderAgent(BaseAgent):
    """Worker-tier agent that scans cwd for project structure and returns a summary."""

    compatible_skills: list[str] = ["file-reader", "context-injector"]

    profile = AgentProfile(
        agent_id="context-builder",
        name="context-builder",
        tier="worker",
        capabilities=["context", "file-reading"],
        task_types=["context"],
        local_only=True,
    )

    def run(self, task: str, *, dry_run: bool = False) -> str:
        if dry_run:
            return "[dry-run] context-builder would scan cwd and summarize project structure"

        cwd = Path(".")
        lines: list[str] = [f"Context scan for: {task[:80]}", ""]

        # README
        readme = cwd / "README.md"
        if readme.exists():
            size = readme.stat().st_size
            lines.append(f"README.md -- found ({size} bytes)")
        else:
            lines.append("README.md -- not found")

        # docs/
        docs_dir = cwd / "docs"
        if docs_dir.is_dir():
            doc_files = sorted(docs_dir.rglob("*"))
            doc_count = sum(1 for f in doc_files if f.is_file())
            lines.append(f"docs/ -- found ({doc_count} file(s))")
        else:
            lines.append("docs/ -- not found")

        # src/
        src_dir = cwd / "src"
        if src_dir.is_dir():
            py_files = sorted(src_dir.rglob("*.py"))
            lines.append(f"src/ -- found ({len(py_files)} .py file(s))")
            for f in py_files[:8]:
                lines.append(f"  {f.relative_to(cwd)}")
            if len(py_files) > 8:
                lines.append(f"  ... and {len(py_files) - 8} more")
        else:
            lines.append("src/ -- not found")

        if not any(s in ("README.md -- found", "docs/ -- found", "src/ -- found")
                   for s in [lines[2], lines[3], lines[4]]):
            lines.append("")
            lines.append("No standard project structure detected in cwd.")

        return "\n".join(lines)
