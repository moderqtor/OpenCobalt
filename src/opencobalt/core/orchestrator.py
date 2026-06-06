"""Multi-agent orchestration with live parallel execution and status display."""

from __future__ import annotations

import re
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import OrchestrationResult, SubTask
from .subagent_registry import SubagentRegistry

_console = Console()

_BINARY_MAP: dict[str, str] = {
    "claude-code": "claude",
    "codex-cli": "codex",
    "gemini-cli": "gemini",
    "ollama": "ollama",
}

_TOOL_TO_MODEL: dict[str, str] = {
    "claude-code": "claude",
    "codex-cli": "codex",
    "gemini-cli": "gemini",
    "ollama": "ollama",
}

_COBALT = "#7B9EFF"
_GREEN = "#3DFFA0"
_AMBER = "#FFD166"
_RED = "#FF5577"
_DIM = "#555555"


# ── Agent status (thread-safe) ─────────────────────────────────────────────────

class AgentStatus:
    """Thread-safe per-subtask status for the live display."""

    def __init__(self, subtask: SubTask, agent_id: str, tool: str) -> None:
        self.subtask = subtask
        self.agent_id = agent_id
        self.tool = tool
        self._state = "pending"
        self._elapsed: float = 0.0
        self._start: float = 0.0
        self._preview: str = ""
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            self._state = "running"
            self._start = time.monotonic()

    def tick(self) -> None:
        with self._lock:
            if self._state == "running" and self._start:
                self._elapsed = time.monotonic() - self._start

    def add_preview(self, text: str) -> None:
        """Update the preview line shown in the status table."""
        with self._lock:
            if self._start:
                self._elapsed = time.monotonic() - self._start
            stripped = text.strip()
            if stripped and not stripped.startswith("\x1b"):
                self._preview = stripped[:72]

    def finish(self, success: bool) -> None:
        with self._lock:
            self._state = "done" if success else "failed"
            if self._start:
                self._elapsed = time.monotonic() - self._start

    def snapshot(self) -> tuple[str, float, str]:
        """Return (state, elapsed_s, preview) atomically."""
        with self._lock:
            return self._state, self._elapsed, self._preview


# ── Status table ───────────────────────────────────────────────────────────────

def _elapsed_str(seconds: float) -> str:
    if seconds < 1:
        return "–"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}" if m else f"{s}s"


def _build_status_table(statuses: list[AgentStatus], task: str) -> Table:
    table = Table(
        show_header=True,
        header_style=f"bold {_COBALT}",
        border_style=_DIM,
        title=f"[bold {_COBALT}]orchestrating[/bold {_COBALT}]  [dim]{task[:64]}[/dim]",
        title_justify="left",
        padding=(0, 1),
        expand=True,
    )
    table.add_column("agent", style=_COBALT, width=18, no_wrap=True)
    table.add_column("tool", style="dim", width=11, no_wrap=True)
    table.add_column("status", width=11, no_wrap=True)
    table.add_column("time", justify="right", width=6, no_wrap=True)
    table.add_column("live", no_wrap=True)

    state_text = {
        "pending": Text("◯ pending", style=_DIM),
        "running": Text("⟳ running", style=_AMBER),
        "done":    Text("✓ done   ", style=_GREEN),
        "failed":  Text("✗ failed ", style=_RED),
    }

    for s in statuses:
        state, elapsed, preview = s.snapshot()
        elapsed_display = _elapsed_str(elapsed)

        if state == "running":
            filled = min(14, max(1, int(elapsed / 4)))
            bar = Text("█" * filled + "░" * (14 - filled), style=_COBALT)
            suffix = Text(f" {preview[:40]}", style="dim") if preview else Text("")
            live_col = Text.assemble(bar, suffix)
        elif state == "done":
            live_col = Text("█" * 14, style=_GREEN)
        elif state == "failed":
            live_col = Text("░" * 14, style=_RED)
        else:
            live_col = Text("░" * 14, style=_DIM)

        table.add_row(
            s.agent_id, s.tool,
            state_text.get(state, Text(state)),
            elapsed_display, live_col,
        )

    return table


# ── Synthesizer ────────────────────────────────────────────────────────────────

class ResultSynthesizer:
    """Merge per-subtask outputs into attributed text or Rich panels."""

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

    def print_rich(
        self,
        task: str,
        subtasks: list[SubTask],
        outputs: dict[str, str],
    ) -> None:
        """Display per-agent Rich panels for synthesis."""
        registry = SubagentRegistry()
        _console.print()
        for st in subtasks:
            spec = registry.get_for_task_type(st.task_type)
            label = spec.agent_id if spec else st.task_type
            output = outputs.get(st.id, "[no output]")
            is_error = output.startswith("[")
            border = _DIM if is_error else _COBALT
            display = output[:4000]
            if len(output) > 4000:
                display += "\n[dim]…output truncated[/dim]"
            title = (
                f"[bold {_COBALT}]{label}[/bold {_COBALT}]"
                f"  [dim]{st.task_type} · {st.preferred_tool}[/dim]"
            )
            _console.print(Panel(display, title=title, border_style=border, padding=(0, 1)))
        _console.print()


# ── Executor ───────────────────────────────────────────────────────────────────

class OrchestrationExecutor:
    """Dispatch subtasks in parallel with optional live Rich status display."""

    def __init__(self, max_workers: int = 6, timeout_s: int = 600) -> None:
        self._max_workers = max_workers
        self._timeout_s = timeout_s

    def run(
        self,
        task: str,
        subtasks: list[SubTask],
        show_live: bool = True,
    ) -> OrchestrationResult:
        t0 = time.monotonic()

        if not subtasks:
            return OrchestrationResult(
                task=task, subtasks=[], outputs={},
                synthesis=f"No subtasks produced for: {task}",
                elapsed_s=0.0, success=False, errors=["no subtasks"],
            )

        registry = SubagentRegistry()
        statuses: list[AgentStatus] = []
        for st in subtasks:
            spec = registry.get_for_task_type(st.task_type)
            agent_id = spec.agent_id if spec else st.task_type
            statuses.append(AgentStatus(st, agent_id, st.preferred_tool))

        status_by_id = {s.subtask.id: s for s in statuses}
        outputs: dict[str, str] = {}
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures: dict[Future, SubTask] = {
                pool.submit(self._execute_one, st, status_by_id[st.id]): st
                for st in subtasks
            }

            if show_live:
                with Live(
                    _build_status_table(statuses, task),
                    console=_console,
                    refresh_per_second=4,
                    transient=False,
                ) as live:
                    while not all(f.done() for f in futures):
                        for s in statuses:
                            s.tick()
                        live.update(_build_status_table(statuses, task))
                        time.sleep(0.25)
                    for s in statuses:
                        s.tick()
                    live.update(_build_status_table(statuses, task))
            else:
                # Tests and headless mode — just wait
                for _ in as_completed(futures, timeout=self._timeout_s * len(subtasks)):
                    pass

            for future, st in futures.items():
                try:
                    outputs[st.id] = future.result(timeout=10)
                except Exception as exc:
                    outputs[st.id] = f"[error: {exc}]"
                    errors.append(f"{st.task_type}: {exc}")

        elapsed = round(time.monotonic() - t0, 2)
        real_outputs = {k: v for k, v in outputs.items() if not v.startswith("[error")}
        success = len(real_outputs) > 0

        synthesizer = ResultSynthesizer()
        synthesis = synthesizer.synthesize(task, subtasks, outputs)

        return OrchestrationResult(
            task=task, subtasks=subtasks, outputs=outputs,
            synthesis=synthesis, elapsed_s=elapsed,
            success=success, errors=errors,
        )

    def _execute_one(self, subtask: SubTask, status: AgentStatus) -> str:
        """Wrap _dispatch_subtask with status tracking. Tests mock _dispatch_subtask."""
        status.start()
        output = self._dispatch_subtask(subtask)
        for line in output.splitlines()[:3]:
            status.add_preview(line)
        success = bool(output) and not output.startswith("[")
        status.finish(success=success)
        return output

    def _dispatch_subtask(self, subtask: SubTask) -> str:
        """Inner dispatch — checks availability, streams output. Mockable in tests."""
        from .council import stream_subprocess

        binary = _BINARY_MAP.get(subtask.preferred_tool, subtask.preferred_tool)
        model = _TOOL_TO_MODEL.get(subtask.preferred_tool, "claude")

        if not shutil.which(binary):
            return f"[{subtask.preferred_tool} not available — install {binary} or check PATH]"

        collected: list[str] = []
        for line in stream_subprocess(
            subtask.prompt,
            model=model,
            intent="implement",
            task_type=subtask.task_type,
        ):
            collected.append(line)

        output = "".join(collected).strip()
        return output or f"[{model}: no output]"


# ── DSL parser ─────────────────────────────────────────────────────────────────

class OrchestrationDSLParser:
    """Parse /orch DSL into (task, explicit_agents) pairs.

    Auto:     plain task string -> ("task", [])
    Explicit: "task" -> [claude:impl, codex:tests] -> merge
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

        agents = [
            part.split(":")[0].strip()
            for part in bracket_match.group(1).split(",")
            if part.strip()
        ]
        return task, agents


# ── Session ────────────────────────────────────────────────────────────────────

class OrchestrationSession:
    """Top-level entry point for /orch."""

    def __init__(self) -> None:
        self._parser = OrchestrationDSLParser()
        self._executor = OrchestrationExecutor()

    def run(self, expr: str, show_live: bool = True) -> OrchestrationResult:
        from .decomposer import TaskDecomposer

        task, explicit_agents = self._parser.parse(expr)

        if explicit_agents:
            subtasks = self._build_explicit_subtasks(task, explicit_agents)
        else:
            decomposer = TaskDecomposer()
            subtasks = decomposer.decompose(task)

        if show_live:
            self._print_preflight(task, subtasks)

        return self._executor.run(task, subtasks, show_live=show_live)

    def _print_preflight(self, task: str, subtasks: list[SubTask]) -> None:
        _console.print()
        _console.print(
            f"  [{_COBALT}]dispatching {len(subtasks)} agent"
            f"{'s' if len(subtasks) != 1 else ''}[/{_COBALT}]"
            f"  [dim]{task[:60]}[/dim]"
        )
        for st in subtasks:
            binary = _BINARY_MAP.get(st.preferred_tool, st.preferred_tool)
            available = shutil.which(binary) is not None
            icon = f"[{_GREEN}]✓[/{_GREEN}]" if available else f"[{_AMBER}]✗[/{_AMBER}]"
            _console.print(
                f"  {icon}  [{_COBALT}]{st.task_type:<12}[/{_COBALT}]"
                f"[dim]{st.preferred_tool}[/dim]"
            )
        _console.print()

    def _build_explicit_subtasks(self, task: str, agents: list[str]) -> list[SubTask]:
        _AGENT_TO_TOOL = {
            "claude": "claude-code", "codex": "codex-cli",
            "gemini": "gemini-cli", "ollama": "ollama",
        }
        _AGENT_TO_TYPE = {
            "claude": "impl", "codex": "tests",
            "gemini": "analyze", "ollama": "summarize",
        }
        return [
            SubTask(
                task_type=_AGENT_TO_TYPE.get(agent, "impl"),
                prompt=task,
                preferred_tool=_AGENT_TO_TOOL.get(agent, agent),
                preferred_agent=agent,
            )
            for agent in agents
        ]
