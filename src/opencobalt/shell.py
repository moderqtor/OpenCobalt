"""Interactive REPL for OpenCobalt."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.console import Console

from .core.background import BackgroundResult, BackgroundRunner, TestWatcher
from .core.brief import BriefGenerator
from .core.learning_router import LearningRouter
from .core.ledger import Ledger
from .core.overlay import OverlayController

_COBALT = "#7B9EFF"
_GREEN = "#3DFFA0"
_AMBER = "#FFD166"
_DIM = "#555555"

_STYLE = Style.from_dict({
    "prompt": f"bold {_COBALT}",
    "prompt.app": f"bold {_COBALT}",
    "prompt.sep": _DIM,
    "": "",
})

console = Console()


class CobaltShell:
    """Interactive cobalt shell."""

    _CLI_COMMANDS = [
        "route",
        "brief",
        "status",
        "history",
        "stats",
        "benchmark",
        "telemetry",
        "verify",
        "lint",
        "doctor",
        "public-check",
        "context",
        "export",
        "log",
        "note",
        "day",
        "memory",
        "agents",
        "skills",
        "integrations",
        "cost",
        "config",
        "session",
        "hooks",
        "council",
        "debate",
        "orch",
        "auto",
        "mission",
        "limits",
        "policy",
        "converge",
        "install-hooks",
        "tui",
        "ui",
        "opportunities",
        "approvals",
        "missions",
        "evolve",
        "why",
        "receipts",
        "plans",
    ]

    def __init__(self, db_path: Path, bridge_path: Path) -> None:
        self._db_path = db_path
        self._bridge_path = bridge_path
        self._ledger = Ledger(db_path)
        self._learning_router = LearningRouter(self._ledger)
        self._runner = BackgroundRunner(max_workers=3)
        self._watcher = TestWatcher(self._runner)
        self._council_cache: dict[str, list[BackgroundResult]] = {}
        self._overlay = OverlayController(
            ledger=self._ledger,
            route_runner=self._route_and_open,
            convergence_runner=self._run_converge,
            auto_runner=self._run_auto,
            mission_runner=self._run_mission,
        )
        self._session: PromptSession = PromptSession(
            completer=WordCompleter(
                [f"/{command}" for command in self._CLI_COMMANDS] + ["/pipe", "/graph"],
                match_middle=False,
                sentence=True,
            ),
            style=_STYLE,
        )

    def run(self) -> None:
        """Run the main prompt loop."""
        self._print_header()
        self._ensure_session_branch()
        self._print_brief()
        console.print(
            "  [dim]Type a task to route it, or [bold]/[/bold] for commands. "
            "Ctrl+C to exit.[/dim]\n"
        )

        self._watcher.start()
        try:
            while True:
                self._drain_and_notify()
                status = self.render_status()
                try:
                    text = self._session.prompt(
                        HTML("<prompt.app>opencobalt</prompt.app> <prompt.sep>›</prompt.sep> "),
                        bottom_toolbar=HTML(f"<style fg='{_DIM}'>{status}</style>"),
                    )
                except KeyboardInterrupt:
                    break
                except EOFError:
                    break

                text = text.strip()
                if text:
                    self.dispatch(text)
        finally:
            self.on_exit()

    def dispatch(self, text: str) -> None:
        """Route input to a slash command or the task router."""
        if text == "/":
            self._show_palette()
            return
        if text.startswith("/"):
            parts = text[1:].split(None, 1)
            cmd = parts[0]
            if len(parts) > 1 and cmd == "route":
                args = [parts[1]]
            else:
                args = parts[1].split() if len(parts) > 1 else []
            self._run_command(cmd, args)
            return
        self._overlay.handle_prompt(text)

    def render_status(self) -> str:
        """Return a one-line status string for the toolbar."""
        parts = []
        try:
            count = self._ledger.count_memory_records()
            parts.append(f"memory {count}")
        except Exception:
            pass
        pending = self._runner.drain()
        if pending:
            self._council_cache.setdefault("pending", []).extend(pending)
            parts.append(f"ready {len(pending)} background - /council show")
        parts.append("watching src/")
        return "  ·  ".join(parts)

    def list_slash_commands(self) -> list[str]:
        """Return all registered slash command names."""
        return list(self._CLI_COMMANDS) + ["pipe", "graph"]

    def on_exit(self) -> None:
        """Shut down background work and print a session footer."""
        self._watcher.stop()
        self._runner.shutdown()

        try:
            decisions = self._ledger.list_route_decisions(limit=50)
            tool_counts: dict[str, int] = {}
            for d in decisions:
                tool_counts[d.recommended_tool] = tool_counts.get(d.recommended_tool, 0) + 1
            summary_lines = ["Session ended."]
            if tool_counts:
                parts = " · ".join(
                    f"{t} ×{n}"
                    for t, n in sorted(tool_counts.items(), key=lambda x: -x[1])
                )
                summary_lines.append(f"routes: {parts}")
        except Exception:
            summary_lines = ["Session ended."]

        try:
            import platform
            import subprocess as _sp

            gen = BriefGenerator(self._ledger, bridge_path=self._bridge_path)
            brief_text = gen.generate(days=1)
            if platform.system() == "Darwin":
                _sp.run(["pbcopy"], input=brief_text.encode(), check=True, capture_output=True)
                summary_lines.append("brief copied to clipboard — paste into next session")
        except Exception:
            pass

        console.print("\n  [dim]" + "\n  ".join(summary_lines) + "[/dim]\n")

    def _print_header(self) -> None:
        import importlib.metadata
        import time
        from datetime import datetime

        try:
            version = importlib.metadata.version("opencobalt")
        except Exception:
            version = "dev"
        now = datetime.now().strftime("%Y-%m-%d")

        LOGO = [
            "   ◈ ◈ ◈   ",
            " ◈       ◈ ",
            "◈    ●    ◈",
            " ◈       ◈ ",
            "   ◈ ◈ ◈   ",
        ]
        LINES = [
            f"[bold {_COBALT}]OpenCobalt[/bold {_COBALT}]  [dim]v{version}[/dim]",
            f"[dim]{now}[/dim]",
            "",
            "[dim]local SQLite · deterministic routing · telemetry scoring[/dim]",
        ]

        console.print()
        for i, line in enumerate(LOGO):
            logo_part = f"[bold {_COBALT}]{line}[/bold {_COBALT}]"
            text_part = f"  {LINES[i]}" if i < len(LINES) else ""
            console.print(f"  {logo_part}{text_part}")
            time.sleep(0.04)
        for line in LINES[len(LOGO):]:
            console.print(f"               {line}")
            time.sleep(0.03)
        console.print(f"\n  [dim]{'─' * 56}[/dim]")

    def _print_brief(self) -> None:
        try:
            gen = BriefGenerator(self._ledger, bridge_path=self._bridge_path)
            brief = gen.generate_startup()
            console.print()
            for line in brief.splitlines():
                if line.startswith("!"):
                    console.print(f"  [{_AMBER}]{line}[/{_AMBER}]")
                elif line.startswith("✓"):
                    console.print(f"  [dim]{line}[/dim]")
                else:
                    console.print(f"  [dim]{line}[/dim]")
            console.print()
        except Exception:
            pass

    def _show_palette(self) -> None:
        console.print("\n  [bold]Commands[/bold]  [dim]Tab to complete · /cmd args[/dim]\n")
        cols = [self._CLI_COMMANDS[i:i + 3] for i in range(0, len(self._CLI_COMMANDS), 3)]
        for row in cols:
            line = "  ".join(f"[{_COBALT}]/{command:<18}[/{_COBALT}]" for command in row)
            console.print(f"  {line}")
        console.print(f"  [{_COBALT}]/pipe[/{_COBALT}]  [{_COBALT}]/graph[/{_COBALT}]\n")

    def _run_command(self, cmd: str, args: list[str]) -> None:
        """Invoke a CLI command via subprocess, inheriting the terminal."""
        if cmd == "pipe":
            self._run_pipe(" ".join(args))
            return
        if cmd == "orch":
            self._run_orch(" ".join(args))
            return
        if cmd == "auto":
            self._run_auto(" ".join(args))
            return
        if cmd == "mission":
            self._run_mission(" ".join(args))
            return
        if cmd in {"limits", "policy"}:
            subprocess.run(["opencobalt", cmd] + args)
            return
        if cmd == "converge":
            self._run_converge(" ".join(args))
            return
        if cmd == "graph":
            self._run_graph(args)
            return
        if cmd == "council":
            if not args or args[0] == "show":
                self._show_council_cache()
            elif args[0] in {"coordinate", "review", "ideate", "resolve"}:
                content = " ".join(args[1:]) or args[0]
                subprocess.run(["opencobalt", "council", "--mode", args[0], content])
            else:
                subprocess.run(["opencobalt", "council"] + args)
            return
        argv = ["opencobalt", cmd] + args
        subprocess.run(argv)

    def _run_pipe(self, expr: str) -> None:
        from rich.console import Console as RichConsole

        from .core.pipeline import Pipeline

        c = RichConsole()
        try:
            pipe = Pipeline()
            task, steps = pipe.parse(f'/pipe "{expr}"' if not expr.startswith('"') else f"/pipe {expr}")
            c.print(f"\n  [dim]Pipeline: {len(steps)} steps[/dim]\n")
            for index, step in enumerate(steps, 1):
                hint = f" {step.hint}" if step.hint else ""
                c.print(f"  [dim]step {index}/{len(steps)}[/dim]  {step.tool}{hint}")
            c.print()
            result = pipe.run(task, steps)
            if result.success:
                c.print(f"  [bold {_GREEN}]VERIFIED ✓[/bold {_GREEN}]  [dim]pipeline complete[/dim]")
            else:
                c.print("  [bold #FF5577]pipeline stopped[/bold #FF5577]")
                for error in result.errors:
                    c.print(f"  [dim]{error}[/dim]")
        except ValueError as exc:
            c.print(f"  [{_AMBER}]pipeline error:[/{_AMBER}]  {exc}")

    def _run_orch(self, expr: str) -> None:
        from .core.orchestrator import OrchestrationSession, ResultSynthesizer

        if not expr.strip():
            console.print(
                f"  [{_AMBER}]Usage:[/{_AMBER}]  /orch \"task\""
                " or /orch \"task\" -> [claude:impl, codex:tests] -> merge"
            )
            return

        session = OrchestrationSession()
        result = session.run(expr, show_live=True)

        # Rich panel display per agent
        synthesizer = ResultSynthesizer()
        synthesizer.print_rich(result.task, result.subtasks, result.outputs)

        elapsed_str = f"{result.elapsed_s:.1f}s"
        agent_word = "agent" if len(result.subtasks) == 1 else "agents"
        console.print(
            f"  [dim]completed in {elapsed_str}"
            f" · {len(result.subtasks)} {agent_word}"
            f" · {'success' if result.success else 'partial'}[/dim]\n"
        )

        try:
            from .core.models import MultiRouteDecision
            decision = MultiRouteDecision(
                task=result.task,
                subtasks=result.subtasks,
                tools_used=[s.preferred_tool for s in result.subtasks],
                result_id=result.id,
            )
            from .core.ledger import Ledger
            Ledger(self._db_path).insert_multi_route_decision(decision)
        except Exception:
            pass

    def _run_converge(self, task: str) -> None:
        from .core.auto_committer import AutoCommitter
        from .core.convergence_orchestrator import ConvergenceOrchestrator

        if not task.strip():
            console.print(
                f"  [{_AMBER}]Usage:[/{_AMBER}]  /converge \"task\""
                "  |  /converge --resume"
            )
            return

        resume_id: str | None = None
        actual_task = task.strip()

        if actual_task == "--resume":
            sessions = self._ledger.list_convergence_sessions(limit=1)
            if not sessions:
                console.print("  [dim]No sessions to resume.[/dim]")
                return
            last = sessions[0]
            if last["status"] not in ("running", "failed", "interrupted"):
                console.print(
                    f"  [dim]Last session {last['id'][:8]} is already {last['status']}.[/dim]"
                )
                return
            resume_id = last["id"]
            actual_task = last["seed_task"]

        orch = ConvergenceOrchestrator(
            committer=AutoCommitter(),
            ledger=self._ledger,
        )
        orch.run(actual_task, resume_session_id=resume_id)

    def _run_auto(self, task: str) -> None:
        from .core.auto_orchestrator import (
            AutoOrchestrator,
            render_auto_mission_record,
            render_auto_plan,
        )
        from .core.mission_engine import (
            MissionEngine,
            render_auto_route_promotion_report,
        )

        if not task.strip():
            console.print(
                f"  [{_AMBER}]Usage:[/{_AMBER}]  /auto \"goal\""
                "  Plans the internal route without starting external runtimes."
            )
            return

        envelope: str | None = None
        budget: str | None = None
        execute = False
        create_mission = False
        promote = False
        goal_parts: list[str] = []
        parts = shlex.split(task)
        index = 0
        while index < len(parts):
            token = parts[index]
            if token == "--envelope" and index + 1 < len(parts):
                envelope = parts[index + 1]
                index += 2
                continue
            if token == "--budget" and index + 1 < len(parts):
                budget = parts[index + 1]
                index += 2
                continue
            if token == "--execute":
                execute = True
                index += 1
                continue
            if token in ("--create-mission", "--mission"):
                create_mission = True
                index += 1
                continue
            if token == "--promote":
                promote = True
                index += 1
                continue
            goal_parts.append(token)
            index += 1

        goal = " ".join(goal_parts).strip()
        if not goal:
            console.print(
                f"  [{_AMBER}]Usage:[/{_AMBER}]  /auto \"goal\""
                "  Plans the internal route without starting external runtimes."
            )
            return

        if promote and not create_mission:
            console.print(f"  [{_AMBER}]--promote requires --create-mission[/{_AMBER}]")
            return

        try:
            orchestrator = AutoOrchestrator()
            if create_mission:
                record = orchestrator.create_mission(
                    goal,
                    envelope_id=envelope,
                    cognitive_budget_id=budget,
                    execute=execute,
                    db_path=self._db_path,
                    root=Path("."),
                )
                plan = record.plan
                promotion_report = (
                    MissionEngine(db_path=self._db_path).promote_auto_route(
                        record.mission_id
                    )
                    if promote
                    else None
                )
            else:
                record = None
                promotion_report = None
                plan = orchestrator.plan(
                    goal,
                    envelope_id=envelope,
                    cognitive_budget_id=budget,
                    execute=execute,
                )
        except ValueError as exc:
            console.print(f"  [{_AMBER}]{exc}[/{_AMBER}]")
            return
        console.print()
        console.print(render_auto_plan(plan))
        if record is not None:
            console.print()
            console.print(render_auto_mission_record(record))
        if promotion_report is not None:
            console.print()
            console.print(render_auto_route_promotion_report(promotion_report))
        console.print()

    def _run_mission(self, task: str) -> None:
        if not task.strip():
            console.print(
                f"  [{_AMBER}]Usage:[/{_AMBER}]  /mission --hours 5 \"seed goal\""
            )
            return
        subprocess.run(["opencobalt", "mission"] + shlex.split(task))

    def _show_council_cache(self) -> None:
        all_results = []
        for results in self._council_cache.values():
            all_results.extend(results)
        if not all_results:
            console.print("  [dim]No background council results yet.[/dim]")
            return
        for result in all_results[-6:]:
            model = result.task_id.split(":")[-1] if ":" in result.task_id else result.task_id
            console.print(f"\n  [bold][{model.upper()}][/bold]")
            for line in result.output.splitlines()[:6]:
                console.print(f"  [dim]{line}[/dim]")
        self._council_cache.clear()

    def _run_graph(self, args: list[str]) -> None:
        from .core.knowledge import KnowledgeGraph

        kg = KnowledgeGraph()
        if not args:
            console.print("  [dim]Usage: /graph why <file>  |  /graph <question>  |  /graph ingest[/dim]")
            return
        if args[0] == "ingest":
            n1 = kg.ingest_git_log()
            n2 = kg.ingest_imports(Path("src"))
            console.print(f"  [dim]Ingested {n1} commits, {n2} import edges[/dim]")
            return
        if args[0] == "why" and len(args) > 1:
            result = kg.why(args[1])
        else:
            result = kg.query(" ".join(args))
        console.print(result)

    def _route_and_open(self, task: str) -> None:
        if task.startswith("/"):
            self._overlay.handle_prompt(task)
            return
        task = self._refine_prompt(task)
        decision = self._learning_router.route(task)
        try:
            self._ledger.insert_route_decision(decision)
        except Exception:
            pass

        try:
            from .core.router import _TOOL_PROFILES
            tier_hits: set[str] = set()
            task_lower = task.lower()
            for profile in _TOOL_PROFILES.values():
                if any(kw in task_lower for kw in profile["keywords"]):
                    tier_hits.add(profile["tier"])
            if len(tier_hits) >= 2:
                console.print("  [dim][multi] try /orch for parallel dispatch[/dim]")
        except Exception:
            pass

        tier_color = {
            "executive": _COBALT,
            "manager": _AMBER,
            "worker": _DIM,
        }.get(decision.tier, _DIM)
        console.print(
            f"\n  [{tier_color}]→ {decision.recommended_tool}[/{tier_color}]"
            f"  [dim]score {decision.score} · {decision.tier}[/dim]"
        )

        self._copy_brief_to_clipboard()
        self._open_tool(decision.recommended_tool, task)
        self._queue_background_council(task, decision.id)
        from .core.verify import verify_async
        verify_async(self._runner, root=Path("."), ledger=self._ledger)

    def _refine_prompt(self, task: str) -> str:
        """Return the prompt unchanged; model refinement needs ExecutionEngine."""
        return task

    def _ensure_session_branch(self) -> None:
        """Create a session-scoped git branch if the tree is clean."""
        import shutil
        from datetime import datetime

        if not shutil.which("git"):
            return
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
            )
            if status.stdout.strip():
                return
            date_str = datetime.now().strftime("%Y-%m-%d")
            branch = f"oc/{date_str}-session"
            existing = subprocess.run(
                ["git", "rev-parse", "--verify", branch],
                capture_output=True, text=True, timeout=5,
            )
            if existing.returncode == 0:
                return
            subprocess.run(
                ["git", "checkout", "-b", branch],
                capture_output=True, text=True, timeout=5,
            )
            console.print(f"  [dim]branch: {branch}[/dim]")
        except Exception:
            pass

    def _copy_brief_to_clipboard(self) -> None:
        try:
            import platform

            if platform.system() != "Darwin":
                return
            gen = BriefGenerator(self._ledger, bridge_path=self._bridge_path)
            brief_text = gen.generate(days=7)
            subprocess.run(
                ["pbcopy"],
                input=brief_text.encode(),
                check=True,
                capture_output=True,
            )
            console.print("  [dim]brief copied to clipboard[/dim]")
        except Exception:
            pass

    def _open_tool(self, tool: str, task: str = "") -> None:
        from .core.runtime_boundary import (
            legacy_runtime_block_message_for_runtime,
            normalize_runtime_id,
        )

        _ = task
        runtime = normalize_runtime_id(tool)
        if runtime is not None:
            console.print(f"  {legacy_runtime_block_message_for_runtime(runtime)}", markup=False)
            return
        console.print(f"  [{_AMBER}]{tool} cannot be launched by the shell[/{_AMBER}]")

    def _queue_background_council(self, task: str, task_id: str) -> None:
        import shutil

        from .core.council import consult_subprocess

        for model in ("codex", "antigravity"):
            binary = {"codex": "codex", "antigravity": "agy"}[model]
            if shutil.which(binary):
                self._runner.submit(
                    f"{task_id}:{model}",
                    consult_subprocess,
                    task,
                    model,
                )

    def _drain_and_notify(self) -> None:
        results = self._runner.drain()
        if not results:
            return
        council_results = []
        for result in results:
            if result.task_id == "test-watch":
                self._notify_test_watch(result)
            elif result.task_id == "verify-async":
                console.print(f"\n  [dim]verify: {result.output}[/dim]")
            else:
                council_results.append(result)
        if council_results:
            console.print(
                f"\n  [{_AMBER}]background ready[/{_AMBER}]"
                f"  [dim]{len(council_results)} model(s)[/dim]"
            )
            for result in council_results:
                model = result.task_id.split(":")[-1] if ":" in result.task_id else result.task_id
                preview = (result.output[:80] + "...") if len(result.output) > 80 else result.output
                console.print(f"  [dim][{model}][/dim] {preview}")
            console.print("  [dim]run [bold]/council show[/bold] for full synthesis[/dim]\n")

    def _notify_test_watch(self, result: BackgroundResult) -> None:
        output = result.output or result.error or ""
        if "failed" in output.lower() or "error" in output.lower():
            console.print("\n  [bold red]TESTS FAILING[/bold red]")
            for line in output.splitlines()[:5]:
                console.print(f"  [dim]{line}[/dim]")
        elif "passed" in output.lower():
            console.print("\n  [bold green]tests ok[/bold green]")
