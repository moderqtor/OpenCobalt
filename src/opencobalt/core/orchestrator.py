"""Multi-agent orchestration: executor, synthesizer, DSL parser, session."""

from __future__ import annotations

import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import OrchestrationResult, SubTask
from .subagent_registry import SubagentRegistry

_BINARY_MAP = {
    "claude-code": "claude",
    "codex-cli": "codex",
    "gemini-cli": "gemini",
    "ollama": "ollama",
}


class ResultSynthesizer:
    """Merge per-subtask outputs into a single attributed text block."""

    def synthesize(
        self,
        task: str,
        subtasks: list[SubTask],
        outputs: dict[str, str],
    ) -> str:
        if not subtasks or not outputs:
            return f"No outputs produced for: {task}"

        registry = SubagentRegistry()
        lines = [f"# Orchestration result: {task}\n"]
        for st in subtasks:
            spec = registry.get_for_task_type(st.task_type)
            label = spec.agent_id if spec else st.task_type
            output = outputs.get(st.id, "[no output]")
            lines.append(f"## [{label}] ({st.task_type})\n")
            lines.append(output.strip())
            lines.append("")
        return "\n".join(lines)


class OrchestrationExecutor:
    """Dispatch subtasks in parallel using a dedicated thread pool."""

    def __init__(self, max_workers: int = 6, timeout_s: int = 120) -> None:
        self._max_workers = max_workers
        self._timeout_s = timeout_s

    def run(self, task: str, subtasks: list[SubTask]) -> OrchestrationResult:
        t0 = time.monotonic()
        outputs: dict[str, str] = {}
        errors: list[str] = []

        if not subtasks:
            return OrchestrationResult(
                task=task,
                subtasks=[],
                outputs={},
                synthesis=f"No subtasks produced for: {task}",
                elapsed_s=0.0,
                success=False,
                errors=["no subtasks"],
            )

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._dispatch_subtask, st): st
                for st in subtasks
            }
            total_timeout = self._timeout_s * len(subtasks)
            for future in as_completed(futures, timeout=total_timeout):
                st = futures[future]
                try:
                    outputs[st.id] = future.result(timeout=self._timeout_s)
                except Exception as exc:
                    outputs[st.id] = f"[error: {exc}]"
                    errors.append(f"{st.task_type}: {exc}")

        elapsed = round(time.monotonic() - t0, 2)
        real_outputs = {k: v for k, v in outputs.items() if not v.startswith("[error")}
        success = len(real_outputs) > 0

        synthesizer = ResultSynthesizer()
        synthesis = synthesizer.synthesize(task, subtasks, outputs)

        return OrchestrationResult(
            task=task,
            subtasks=subtasks,
            outputs=outputs,
            synthesis=synthesis,
            elapsed_s=elapsed,
            success=success,
            errors=errors,
        )

    def _dispatch_subtask(self, subtask: SubTask) -> str:
        from .council import consult_subprocess

        binary_key = subtask.preferred_tool
        binary = _BINARY_MAP.get(binary_key, binary_key)

        if not shutil.which(binary):
            return f"[{binary_key} not available -- install {binary} or check PATH]"

        model = binary_key.split("-")[0]
        return consult_subprocess(subtask.prompt, model=model)


class OrchestrationDSLParser:
    """Parse /orch DSL expressions into (task, explicit_agents) pairs.

    Two forms:
      Auto:     just a task string -> ("task", [])
      Explicit: "task" -> [claude:impl, codex:tests] -> merge -> /verify
                -> ("task", ["claude", "codex"])
    """

    def parse(self, expr: str) -> tuple[str, list[str]]:
        expr = expr.strip()

        quoted = re.match(r'^["\'](.+?)["\'](.*)$', expr)
        if quoted:
            task = quoted.group(1).strip()
            rest = quoted.group(2).strip()
        else:
            arrow_pos = expr.find("->")
            if arrow_pos == -1:
                return expr, []
            task = expr[:arrow_pos].strip().strip("\"'")
            rest = expr[arrow_pos:].strip()

        if not rest:
            return task, []

        bracket_match = re.search(r"\[([^\]]+)\]", rest)
        if not bracket_match:
            return task, []

        agents_raw = bracket_match.group(1)
        agents = [
            part.split(":")[0].strip()
            for part in agents_raw.split(",")
            if part.strip()
        ]
        return task, agents


class OrchestrationSession:
    """Top-level entry point for the /orch shell command."""

    def __init__(self) -> None:
        self._parser = OrchestrationDSLParser()
        self._executor = OrchestrationExecutor()

    def run(self, expr: str) -> OrchestrationResult:
        from .decomposer import TaskDecomposer

        task, explicit_agents = self._parser.parse(expr)

        if explicit_agents:
            subtasks = self._build_explicit_subtasks(task, explicit_agents)
        else:
            decomposer = TaskDecomposer()
            subtasks = decomposer.decompose(task)

        return self._executor.run(task, subtasks)

    def _build_explicit_subtasks(
        self, task: str, agents: list[str]
    ) -> list[SubTask]:
        _AGENT_TO_TOOL = {
            "claude": "claude-code",
            "codex": "codex-cli",
            "gemini": "gemini-cli",
            "ollama": "ollama",
        }
        _AGENT_TO_TYPE = {
            "claude": "impl",
            "codex": "tests",
            "gemini": "analyze",
            "ollama": "summarize",
        }
        subtasks = []
        for agent in agents:
            tool = _AGENT_TO_TOOL.get(agent, agent)
            task_type = _AGENT_TO_TYPE.get(agent, "impl")
            subtasks.append(
                SubTask(
                    task_type=task_type,
                    prompt=task,
                    preferred_tool=tool,
                    preferred_agent=agent,
                )
            )
        return subtasks
