"""Autonomous long-running execution engine.

Continuously decomposes, routes, and executes tasks across all available CLI
agents in parallel. Rotates tool usage to avoid burning any single provider's
usage limits. Designed to run for hours unattended.

Usage in shell: /auto <seed task>
Usage in CLI:   opencobalt auto "Build a calendar app with AI scheduling"
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_console = Console()

_COBALT = "#7B9EFF"
_GREEN = "#3DFFA0"
_AMBER = "#FFD166"
_RED = "#FF5577"
_DIM = "#555555"

# Tool rotation: keeps usage spread across providers
_TOOL_ROTATION = ["claude-code", "codex-cli", "google-antigravity", "ollama"]


@dataclass
class AutonomousTask:
    """One unit of work in the autonomous queue."""
    id: str
    task: str
    tool: str
    task_type: str
    status: str = "queued"  # queued | running | done | failed
    output: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    iteration: int = 0

    @property
    def elapsed(self) -> float:
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        if self.started_at:
            return time.monotonic() - self.started_at
        return 0.0


@dataclass
class AutonomousSession:
    """Tracks the state of a long-running autonomous execution."""
    seed_task: str
    started_at: float = field(default_factory=time.monotonic)
    iterations: int = 0
    tasks: list[AutonomousTask] = field(default_factory=list)
    log_path: Path | None = None
    total_output_chars: int = 0

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def active_tasks(self) -> list[AutonomousTask]:
        return [t for t in self.tasks if t.status == "running"]

    @property
    def done_tasks(self) -> list[AutonomousTask]:
        return [t for t in self.tasks if t.status in ("done", "failed")]


class AutonomousRunner:
    """Orchestrates long-running autonomous multi-agent execution.

    Rotates through available tools, decomposes tasks from outputs of
    previous iterations, and runs until max_iterations or max_hours.
    """

    def __init__(
        self,
        max_iterations: int = 20,
        max_hours: float = 5.0,
        log_dir: Path | None = None,
    ) -> None:
        self._max_iter = max_iterations
        self._max_hours = max_hours
        self._log_dir = log_dir or Path(".opencobalt") / "auto_logs"
        self._tool_index = 0  # for rotation

    def run(self, seed_task: str) -> AutonomousSession:
        """Start a long-running autonomous session."""
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_dir / f"auto_{int(time.time())}.md"

        session = AutonomousSession(seed_task=seed_task, log_path=log_path)
        self._log(session, f"# Autonomous Session\n\n**Seed:** {seed_task}\n\n---\n")

        available_tools = self._available_tools()
        if not available_tools:
            _console.print(f"  [{_AMBER}]No CLI tools available. Install claude, codex, agy, or ollama.[/{_AMBER}]")
            return session

        _console.print()
        _console.print(Panel(
            f"[bold {_COBALT}]{seed_task}[/bold {_COBALT}]\n\n"
            f"[dim]tools: {', '.join(available_tools)}[/dim]\n"
            f"[dim]max: {self._max_iter} iterations · {self._max_hours}h[/dim]",
            title=f"[bold {_COBALT}]autonomous mode[/bold {_COBALT}]",
            border_style=_COBALT,
        ))
        _console.print()

        # Decompose seed task into initial subtasks
        from .decomposer import TaskDecomposer
        decomposer = TaskDecomposer()
        subtasks = decomposer.decompose(seed_task)

        # Enqueue initial tasks
        for st in subtasks:
            if st.preferred_tool in available_tools:
                task_obj = AutonomousTask(
                    id=st.id,
                    task=st.prompt,
                    tool=st.preferred_tool,
                    task_type=st.task_type,
                    iteration=0,
                )
                session.tasks.append(task_obj)

        # Main execution loop
        while session.iterations < self._max_iter and session.elapsed < self._max_hours * 3600:
            queued = [t for t in session.tasks if t.status == "queued"]
            if not queued:
                # Try to generate follow-up tasks from completed outputs
                follow_ups = self._generate_followups(session, available_tools)
                if not follow_ups:
                    _console.print(f"  [{_DIM}]autonomous: no more tasks to generate. session complete.[/{_DIM}]")
                    break
                session.tasks.extend(follow_ups)
                queued = follow_ups

            session.iterations += 1
            _console.print(
                f"  [{_COBALT}]iteration {session.iterations}[/{_COBALT}]"
                f"  [dim]{len(queued)} task(s) queued[/dim]"
            )

            # Run the next batch of queued tasks
            batch = queued[:len(available_tools)]  # run up to N at once
            self._run_batch(session, batch)

            # Log iteration results
            for t in batch:
                self._log(session, f"\n## Iteration {session.iterations}: {t.task_type} ({t.tool})\n\n{t.output}\n\n---\n")
                session.total_output_chars += len(t.output)

        self._print_summary(session)
        _console.print(f"  [dim]log saved: {log_path}[/dim]\n")
        return session

    def _run_batch(self, session: AutonomousSession, tasks: list[AutonomousTask]) -> None:
        """Execute a batch of tasks in parallel."""
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(len(tasks), 6)) as pool:
            futures = {pool.submit(self._execute_task, t): t for t in tasks}

            with Live(
                self._build_batch_table(tasks, session),
                console=_console,
                refresh_per_second=4,
            ) as live:
                while not all(f.done() for f in futures):
                    live.update(self._build_batch_table(tasks, session))
                    time.sleep(0.25)
                live.update(self._build_batch_table(tasks, session))

            for future, task in futures.items():
                try:
                    future.result(timeout=5)
                except Exception as exc:
                    task.status = "failed"
                    task.output = f"[error: {exc}]"
                    task.finished_at = time.monotonic()

    def _execute_task(self, task: AutonomousTask) -> None:
        """Execute a single autonomous task in-place."""
        from .council import stream_subprocess

        task.status = "running"
        task.started_at = time.monotonic()

        model_map = {
            "claude-code": "claude",
            "codex-cli": "codex",
            "google-antigravity": "antigravity",
            "ollama": "ollama",
        }
        model = model_map.get(task.tool, "claude")

        collected: list[str] = []
        try:
            for line in stream_subprocess(
                task.task,
                model=model,
                intent="implement",
                task_type=task.task_type,
                autonomous=True,
            ):
                collected.append(line)

            output = "".join(collected).strip()
            task.output = output or f"[{model}: no output]"
            task.status = "done" if output and not output.startswith("[") else "failed"
        except Exception as exc:
            task.output = f"[error: {exc}]"
            task.status = "failed"

        task.finished_at = time.monotonic()

    def _generate_followups(
        self, session: AutonomousSession, available_tools: list[str]
    ) -> list[AutonomousTask]:
        """Generate follow-up tasks from completed outputs."""
        if not session.done_tasks:
            return []

        # Use the last done task's output to ideate next steps
        last_done = [t for t in session.done_tasks if t.output and not t.output.startswith("[")]
        if not last_done:
            return []

        latest = last_done[-1]
        ideation_prompt = (
            f"Original goal: {session.seed_task}\n\n"
            f"Completed: {latest.task_type} task. Output summary:\n{latest.output[:500]}\n\n"
            f"What is the single most valuable next implementation step? "
            f"Reply with ONLY a one-line task description. No explanation."
        )

        from .council import consult_subprocess
        next_task_desc = consult_subprocess(
            ideation_prompt,
            model="ollama" if shutil.which("ollama") else "claude",
            intent="advise",
            timeout=30,
        ).strip()

        if not next_task_desc or next_task_desc.startswith("[") or len(next_task_desc) < 5:
            return []

        # Route to next available tool (rotate)
        next_tool = self._rotate_tool(available_tools)

        # Determine task type from the description
        task_type = self._classify_task(next_task_desc)

        uid = f"auto-{int(time.time())}-{session.iterations}"
        return [AutonomousTask(
            id=uid,
            task=next_task_desc,
            tool=next_tool,
            task_type=task_type,
            iteration=session.iterations,
        )]

    def _rotate_tool(self, available: list[str]) -> str:
        """Round-robin tool selection."""
        for _ in range(len(_TOOL_ROTATION)):
            tool = _TOOL_ROTATION[self._tool_index % len(_TOOL_ROTATION)]
            self._tool_index += 1
            if tool in available:
                return tool
        return available[0]

    def _classify_task(self, task_desc: str) -> str:
        """Keyword-based task type classification."""
        lower = task_desc.lower()
        if any(w in lower for w in ("test", "spec", "coverage", "assert")):
            return "tests"
        if any(w in lower for w in ("document", "readme", "docs", "comment")):
            return "docs"
        if any(w in lower for w in ("review", "audit", "security", "check")):
            return "review"
        if any(w in lower for w in ("analyze", "analyse", "examine", "scan")):
            return "analyze"
        if any(w in lower for w in ("summarize", "summary", "brief")):
            return "summarize"
        return "impl"

    def _available_tools(self) -> list[str]:
        """Return tools available on PATH."""
        tool_to_binary = {
            "claude-code": "claude",
            "codex-cli": "codex",
            "google-antigravity": "agy",
            "ollama": "ollama",
        }
        return [tool for tool, binary in tool_to_binary.items() if shutil.which(binary)]

    def _build_batch_table(self, tasks: list[AutonomousTask], session: AutonomousSession) -> Table:
        table = Table(
            show_header=True,
            header_style=f"bold {_COBALT}",
            border_style=_DIM,
            title=f"[bold {_COBALT}]auto[/bold {_COBALT}]  [dim]iteration {session.iterations} · {self._fmt_elapsed(session.elapsed)}[/dim]",
            title_justify="left",
            padding=(0, 1),
            expand=True,
        )
        table.add_column("type", style=_COBALT, width=12, no_wrap=True)
        table.add_column("tool", style="dim", width=11, no_wrap=True)
        table.add_column("status", width=10, no_wrap=True)
        table.add_column("elapsed", justify="right", width=7, no_wrap=True)

        state_text = {
            "queued":  Text("◯ queued ", style=_DIM),
            "running": Text("⟳ running", style=_AMBER),
            "done":    Text("✓ done   ", style=_GREEN),
            "failed":  Text("✗ failed ", style=_RED),
        }
        for t in tasks:
            elapsed_str = self._fmt_elapsed(t.elapsed) if t.started_at else "–"
            table.add_row(
                t.task_type, t.tool,
                state_text.get(t.status, Text(t.status)),
                elapsed_str,
            )
        return table

    def _fmt_elapsed(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h{m:02d}m"
        if m:
            return f"{m}:{s:02d}"
        return f"{s}s"

    def _log(self, session: AutonomousSession, text: str) -> None:
        if session.log_path:
            try:
                with open(session.log_path, "a", encoding="utf-8") as f:
                    f.write(text)
            except Exception:
                pass

    def _print_summary(self, session: AutonomousSession) -> None:
        done = [t for t in session.tasks if t.status == "done"]
        failed = [t for t in session.tasks if t.status == "failed"]
        _console.print(Panel(
            f"[{_GREEN}]✓ {len(done)} completed[/{_GREEN}]  "
            f"[{_RED}]✗ {len(failed)} failed[/{_RED}]\n"
            f"[dim]{session.iterations} iterations · {self._fmt_elapsed(session.elapsed)} · "
            f"{session.total_output_chars:,} chars generated[/dim]",
            title=f"[bold {_COBALT}]autonomous session complete[/bold {_COBALT}]",
            border_style=_COBALT,
        ))
