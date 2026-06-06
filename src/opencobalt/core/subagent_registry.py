"""Specialized subagent registry for multi-agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SubagentSpec:
    agent_id: str
    specialization: str
    tier: str
    tool: str
    task_types: list[str]
    prompt_template: str = ""


_REGISTRY: list[SubagentSpec] = [
    SubagentSpec(
        agent_id="impl-agent",
        specialization="code implementation",
        tier="executive",
        tool="claude-code",
        task_types=["impl"],
        prompt_template="Implement the following task precisely and completely: {task}",
    ),
    SubagentSpec(
        agent_id="test-gen",
        specialization="test generation",
        tier="manager",
        tool="codex-cli",
        task_types=["tests"],
        prompt_template="Write comprehensive pytest tests for: {task}",
    ),
    SubagentSpec(
        agent_id="doc-writer",
        specialization="documentation",
        tier="manager",
        tool="codex-cli",
        task_types=["docs"],
        prompt_template="Write clear, concise documentation for: {task}",
    ),
    SubagentSpec(
        agent_id="security-reviewer",
        specialization="security audit",
        tier="executive",
        tool="claude-code",
        task_types=["review"],
        prompt_template="Review the following for security and correctness issues: {task}",
    ),
    SubagentSpec(
        agent_id="analyst-agent",
        specialization="long-context analysis, audit, cross-file search",
        tier="executive",
        tool="gemini-cli",
        task_types=["analyze"],
        prompt_template="Analyze the following thoroughly across all relevant files: {task}",
    ),
    SubagentSpec(
        agent_id="summarizer",
        specialization="summarization",
        tier="worker",
        tool="ollama",
        task_types=["summarize"],
        prompt_template="Summarize the following concisely: {task}",
    ),
]


class SubagentRegistry:
    """Lookup specialized subagent specs by task type or agent ID."""

    def list_all(self) -> list[SubagentSpec]:
        return list(_REGISTRY)

    def get_for_task_type(self, task_type: str) -> SubagentSpec | None:
        for spec in _REGISTRY:
            if task_type in spec.task_types:
                return spec
        return None

    def get(self, agent_id: str) -> SubagentSpec | None:
        for spec in _REGISTRY:
            if spec.agent_id == agent_id:
                return spec
        return None
