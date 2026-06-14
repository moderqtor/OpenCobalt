"""Specialized subagent registry for multi-agent orchestration.

Each spec describes a role: what it does, which tier and tool serve it, the
riskiest work it may accept (risk_ceiling), the widest filesystem/process
access it may hold (permission_scope), and the shape of what it returns
(output_contract). Planning code (see delegation.py) enforces the ceilings;
the registry only declares them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RISK_LEVELS = ("green", "yellow", "red", "black")
PERMISSION_SCOPES = ("read", "write", "execute")
OUTPUT_CONTRACTS = ("report", "artifact", "receipt", "prose")
CONTEXT_SENTINEL = "Colin, COBALT-SENTINEL: receipts-first."
CONTEXT_SENTINEL_INSTRUCTIONS = (
    "When producing a final report for Colin, begin with:\n"
    f'"{CONTEXT_SENTINEL}"\n\n'
    "Then state:\n"
    "- current branch\n"
    "- base branch or main SHA if known\n"
    "- test baseline\n"
    "- whether worktree is clean\n"
    "- whether anything was pushed or merged\n\n"
    "If you cannot determine these facts, say so explicitly. Do not invent "
    "repository state. If the sentinel is missing, stale, or paired with "
    "incorrect repo state, assume context has degraded and pause for re-grounding."
)


def with_context_sentinel(prompt: str) -> str:
    return f"{prompt}\n\n{CONTEXT_SENTINEL_INSTRUCTIONS}"


def _prompt(prompt: str) -> str:
    return with_context_sentinel(prompt)


@dataclass
class SubagentSpec:
    agent_id: str
    specialization: str
    tier: str
    tool: str
    task_types: list[str]
    prompt_template: str = ""
    capabilities: list[str] = field(default_factory=list)
    risk_ceiling: str = "yellow"
    permission_scope: str = "read"
    output_contract: str = "report"


_DEFAULT_SPECS: list[SubagentSpec] = [
    SubagentSpec(
        agent_id="impl-agent",
        specialization="code implementation",
        tier="executive",
        tool="claude-code",
        task_types=["impl"],
        prompt_template=_prompt("Implement the following task precisely and completely: {task}"),
        capabilities=["code-edit", "tests"],
        risk_ceiling="yellow",
        permission_scope="write",
        output_contract="artifact",
    ),
    SubagentSpec(
        agent_id="test-gen",
        specialization="test generation",
        tier="manager",
        tool="codex-cli",
        task_types=["tests"],
        prompt_template=_prompt("Write comprehensive pytest tests for: {task}"),
        capabilities=["tests"],
        risk_ceiling="yellow",
        permission_scope="write",
        output_contract="artifact",
    ),
    SubagentSpec(
        agent_id="doc-writer",
        specialization="documentation",
        tier="manager",
        tool="codex-cli",
        task_types=["docs"],
        prompt_template=_prompt("Write clear, concise documentation for: {task}"),
        capabilities=["docs"],
        risk_ceiling="yellow",
        permission_scope="write",
        output_contract="artifact",
    ),
    SubagentSpec(
        agent_id="security-reviewer",
        specialization="security audit",
        tier="executive",
        tool="claude-code",
        task_types=["review"],
        prompt_template=_prompt(
            "Review the following for security and correctness issues: {task}"
        ),
        capabilities=["security", "review"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="analyst-agent",
        specialization="agent-runtime analysis, audit, cross-file search",
        tier="executive",
        tool="google-antigravity",
        task_types=["analyze"],
        prompt_template=_prompt(
            "Analyze the following thoroughly across all relevant files: {task}"
        ),
        capabilities=["analysis"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="summarizer",
        specialization="summarization",
        tier="worker",
        tool="ollama",
        task_types=["summarize"],
        prompt_template=_prompt("Summarize the following concisely: {task}"),
        capabilities=["summarization"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="prose",
    ),
    SubagentSpec(
        agent_id="architect",
        specialization="architecture design and decomposition",
        tier="executive",
        tool="claude-code",
        task_types=["architecture"],
        prompt_template=_prompt("Design the architecture and decomposition for: {task}"),
        capabilities=["architecture", "planning"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="ui-critic",
        specialization="UI and UX critique against DESIGN.md",
        tier="manager",
        tool="codex-cli",
        task_types=["ui-review"],
        prompt_template=_prompt(
            "Critique the following UI work against the design reference: {task}"
        ),
        capabilities=["design-review"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="refactorer",
        specialization="structured refactoring without behavior change",
        tier="manager",
        tool="codex-cli",
        task_types=["refactor"],
        prompt_template=_prompt("Refactor for clarity without changing behavior: {task}"),
        capabilities=["code-edit"],
        risk_ceiling="yellow",
        permission_scope="write",
        output_contract="artifact",
    ),
    SubagentSpec(
        agent_id="integration-checker",
        specialization="cross-module integration verification",
        tier="manager",
        tool="codex-cli",
        task_types=["integration"],
        prompt_template=_prompt("Verify integration points and contracts for: {task}"),
        capabilities=["tests", "analysis"],
        risk_ceiling="yellow",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="cost-optimizer",
        specialization="routing and spend optimization analysis",
        tier="worker",
        tool="ollama",
        task_types=["cost"],
        prompt_template=_prompt("Analyze cost and routing efficiency for: {task}"),
        capabilities=["analysis"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="receipt-verifier",
        specialization="work receipt and artifact hash verification",
        tier="manager",
        tool="codex-cli",
        task_types=["receipts"],
        prompt_template=_prompt("Verify receipts and artifact hashes for: {task}"),
        capabilities=["verification"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="receipt",
    ),
    SubagentSpec(
        agent_id="policy-auditor",
        specialization="execution policy and risk gate audit",
        tier="executive",
        tool="claude-code",
        task_types=["policy"],
        prompt_template=_prompt("Audit policy gates and risk classification for: {task}"),
        capabilities=["security", "review"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="design-reviewer",
        specialization="design document and API surface review",
        tier="executive",
        tool="claude-code",
        task_types=["design-review"],
        prompt_template=_prompt("Review the design and API surface of: {task}"),
        capabilities=["design-review", "review"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="research-scout",
        specialization="background research and option gathering",
        tier="executive",
        tool="gemini-cli",
        task_types=["research"],
        prompt_template=_prompt("Research options and prior art for: {task}"),
        capabilities=["research"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
    SubagentSpec(
        agent_id="benchmark-runner",
        specialization="benchmark execution and score recording",
        tier="manager",
        tool="codex-cli",
        task_types=["benchmark"],
        prompt_template=_prompt("Run benchmarks and record scores for: {task}"),
        capabilities=["benchmark"],
        risk_ceiling="yellow",
        permission_scope="execute",
        output_contract="artifact",
    ),
    SubagentSpec(
        agent_id="failure-triager",
        specialization="failed run triage and root cause notes",
        tier="manager",
        tool="codex-cli",
        task_types=["triage"],
        prompt_template=_prompt(
            "Triage the failure and identify the root cause of: {task}"
        ),
        capabilities=["analysis", "triage"],
        risk_ceiling="green",
        permission_scope="read",
        output_contract="report",
    ),
]


class SubagentRegistry:
    """Lookup specialized subagent specs by task type or agent ID.

    Instances start with the default library; register() adds more without
    mutating other instances.
    """

    def __init__(self, *, include_defaults: bool = True) -> None:
        self._specs: list[SubagentSpec] = list(_DEFAULT_SPECS) if include_defaults else []

    def register(self, spec: SubagentSpec) -> None:
        if self.get(spec.agent_id) is not None:
            raise ValueError(f"subagent already registered: {spec.agent_id}")
        if spec.risk_ceiling not in RISK_LEVELS:
            raise ValueError(f"unknown risk ceiling: {spec.risk_ceiling}")
        if spec.permission_scope not in PERMISSION_SCOPES:
            raise ValueError(f"unknown permission scope: {spec.permission_scope}")
        if spec.output_contract not in OUTPUT_CONTRACTS:
            raise ValueError(f"unknown output contract: {spec.output_contract}")
        self._specs.append(spec)

    def list_all(self) -> list[SubagentSpec]:
        return list(self._specs)

    def get_for_task_type(self, task_type: str) -> SubagentSpec | None:
        for spec in self._specs:
            if task_type in spec.task_types:
                return spec
        return None

    def get(self, agent_id: str) -> SubagentSpec | None:
        for spec in self._specs:
            if spec.agent_id == agent_id:
                return spec
        return None
