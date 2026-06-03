"""Interactive REPL for OpenCobalt."""

from __future__ import annotations

import subprocess
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.styles import Style
from rich.console import Console

from .core.background import BackgroundResult, BackgroundRunner
from .core.brief import BriefGenerator
from .core.ledger import Ledger
from .core.router import route_task

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
        self._runner = BackgroundRunner(max_workers=3)
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
        self._print_brief()
        console.print(
            "  [dim]Type a task to route it, or [bold]/[/bold] for commands. "
            "Ctrl+C to exit.[/dim]\n"
        )

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
        self._runner.shutdown()
        console.print("\n  [dim]Session ended.[/dim]\n")

    def _print_header(self) -> None:
        import importlib.metadata
        from datetime import datetime

        try:
            version = importlib.metadata.version("opencobalt")
        except Exception:
            version = "dev"
        now = datetime.now().strftime("%Y-%m-%d")
        console.print(
            f"\n  [bold {_COBALT}]OpenCobalt[/bold {_COBALT}]"
            f"  [dim]v{version} · {now}[/dim]\n"
            f"  [dim]{'-' * 52}[/dim]"
        )

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
        argv = ["opencobalt", cmd] + args
        subprocess.run(argv)

    def _route_and_open(self, task: str) -> None:
        decision = route_task(task, record=False)
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
            "cursor": "cursor",
            "ollama": None,
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
        console.print(f"\n  [{_AMBER}]background ready[/{_AMBER}]  [dim]{len(results)} model(s)[/dim]")
        for result in results:
            model = result.task_id.split(":")[-1] if ":" in result.task_id else result.task_id
            preview = (result.output[:80] + "...") if len(result.output) > 80 else result.output
            console.print(f"  [dim][{model}][/dim] {preview}")
        console.print("  [dim]run [bold]/council show[/bold] for full synthesis[/dim]\n")
