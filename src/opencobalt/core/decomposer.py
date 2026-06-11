"""Keyword-based task decomposer for multi-agent orchestration.

No LLM required. Maps task descriptions to typed subtasks using the same
keyword scoring approach as the main router.
"""

from __future__ import annotations

from .models import SubTask

_TYPE_KEYWORDS: dict[str, list[str]] = {
    "impl": [
        "implement", "build", "create", "add", "write", "develop", "code",
        "refactor", "fix", "update", "integrate", "connect", "wire",
    ],
    "tests": [
        "test", "tests", "spec", "pytest", "coverage", "assert", "unit",
        "integration", "tdd", "verify tests",
    ],
    "docs": [
        "document", "docs", "docstring", "readme", "changelog", "comment",
        "explain", "describe",
    ],
    "review": [
        "review", "audit security", "security review", "check for", "lint",
        "validate", "inspect",
    ],
    "analyze": [
        "audit", "analyze", "analyse", "scan", "search", "entire", "all files",
        "codebase", "read through", "comprehensive",
    ],
    "summarize": [
        "summarize", "summary", "shorten", "compress", "paraphrase",
        "extract", "brief",
    ],
}

_TYPE_TO_TOOL: dict[str, str] = {
    "impl": "claude-code",
    "tests": "codex-cli",
    "docs": "codex-cli",
    "review": "claude-code",
    "analyze": "google-antigravity",
    "summarize": "ollama",
}


class TaskDecomposer:
    """Decompose a task string into typed SubTasks via keyword scoring."""

    def decompose(self, task: str) -> list[SubTask]:
        task_lower = task.lower()
        matched: list[str] = []

        for task_type, keywords in _TYPE_KEYWORDS.items():
            if any(kw in task_lower for kw in keywords):
                matched.append(task_type)

        if not matched:
            matched = ["impl"]

        subtasks = []
        for task_type in matched:
            tool = _TYPE_TO_TOOL.get(task_type, "claude-code")
            prompt = self._build_prompt(task, task_type)
            subtasks.append(
                SubTask(
                    task_type=task_type,
                    prompt=prompt,
                    preferred_tool=tool,
                )
            )

        return subtasks

    def _build_prompt(self, task: str, task_type: str) -> str:
        prefixes = {
            "impl": "Implement the following",
            "tests": "Write comprehensive tests for the following",
            "docs": "Write clear documentation for the following",
            "review": "Review the following for correctness and quality",
            "analyze": "Analyze the following thoroughly",
            "summarize": "Summarize the following concisely",
        }
        prefix = prefixes.get(task_type, "Handle the following")
        return f"{prefix}: {task}"
