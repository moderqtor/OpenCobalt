"""Interactive REPL for OpenCobalt."""

from __future__ import annotations

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

_COBALT = "#7B9EFF"
_GREEN = "#3DFFA0"
_AMBER = "#FFD166"
_DIM = "#555555"

_STYLE = Style.from_dict({
    "prompt": f"bold {_COBALT}",
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
        "install-hooks",
        "tui",
        "ui",
    ]

    def __init__(self, db_path: Path, bridge_path: Path) -> None:
        self._db_path = db_path
        self._bridge_path = bridge_path
        self._ledger = Ledger(db_path)
        self._learning_router = LearningRouter(self._ledger)
        self._runner = BackgroundRunner(max_workers=3)
        self._watcher = TestWatcher(self._runner)
        self._council_cache: dict[str, list[BackgroundResult]] = {}
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
                        HTML("<ansicyan>›</ansicyan> "),
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
        self._route_and_open(text)

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
            "[dim]local-first AI orchestration[/dim]",
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
        console.print(f"\n  [dim]{'─' * 48}[/dim]")

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
        if cmd == "graph":
            self._run_graph(args)
            return
        if cmd == "council" and args and args[0] == "show":
            self._show_council_cache()
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
        task = self._refine_prompt(task)
        decision = self._learning_router.route(task)
        try:
            self._ledger.insert_route_decision(decision)
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
        self._open_tool(decision.recommended_tool)
        self._queue_background_council(task, decision.id)
        from .core.verify import verify_async
        verify_async(self._runner, root=Path("."), ledger=self._ledger)

    def _refine_prompt(self, task: str) -> str:
        """Optionally refine the prompt via a local Ollama model. No-ops if unavailable."""
        import shutil

        if not shutil.which("ollama"):
            return task
        try:
            system = (
                "You are a prompt optimizer. Rewrite the user's task to be more precise, "
                "specific, and actionable while preserving the original intent. "
                "Output ONLY the rewritten task — no explanation, no preamble."
            )
            result = subprocess.run(
                ["ollama", "run", "llama3", f"System: {system}\n\nTask: {task}"],
                capture_output=True, text=True, timeout=12,
            )
            refined = result.stdout.strip()
            if refined and len(refined) < 500 and refined != task:
                console.print(f"  [dim]refined → {refined[:80]}{'…' if len(refined)>80 else ''}[/dim]")
                return refined
        except Exception:
            pass
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

    def _open_tool(self, tool: str) -> None:
        import shutil

        binaries = {
            "claude-code": "claude",
            "codex-cli": "codex",
            "gemini-cli": "gemini",
            "antigravity-cli": "antigravity",
            "github-cli": "gh",
            "cursor": "cursor",
            "ollama": None,
            "obsidian": None,
        }
        binary = binaries.get(tool, tool)
        if binary is None:
            console.print("  [dim]ollama: run manually from another pane[/dim]")
            return
        if not shutil.which(binary):
            console.print(f"  [{_AMBER}]{binary} not on PATH[/{_AMBER}]  [dim]check install[/dim]")
            return
        console.print(f"  [dim]opening {binary}...[/dim]\n")
        subprocess.Popen([binary])

    def _queue_background_council(self, task: str, task_id: str) -> None:
        import shutil

        from .core.council import consult_subprocess

        for model in ("codex", "gemini"):
            binary = {"codex": "codex", "gemini": "gemini"}[model]
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
