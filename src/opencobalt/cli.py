"""OpenCobalt CLI.

Usage:
  opencobalt status
  opencobalt models
  opencobalt log [--summary TEXT]
  opencobalt memory status
  opencobalt memory export
  opencobalt context build
  opencobalt route TASK
  opencobalt verify
  opencobalt doctor
  opencobalt public-check
  opencobalt design brief
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from .core.ledger import Ledger
from .core.memory import MemoryStore
from .core.models import SessionEvent
from .core.models_discovery import discover_models, is_ollama_available
from .core.public_safety import scan_directory
from .core.router import route_task
from .core.verify import run_all

app = typer.Typer(
    name="opencobalt",
    help="Local-first AI orchestration and memory control plane.",
    no_args_is_help=True,
    add_completion=False,
)
memory_app = typer.Typer(help="Memory commands.")
app.add_typer(memory_app, name="memory")

console = Console()
err = Console(stderr=True, style="bold red")

_DB_PATH = Path(".opencobalt") / "ledger.db"
_EXPORT_PATH = Path(".opencobalt") / "exports"
_CONTEXT_PATH = Path(".opencobalt") / "context" / "latest.md"


def _ledger() -> Ledger:
    return Ledger(_DB_PATH)


@app.command()
def status() -> None:
    """Show system status: Python, Ollama, ledger, docs, public safety."""
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value")

    table.add_row("repo", str(Path(".").resolve()))
    table.add_row("python", sys.version.split()[0])

    ollama_ok = is_ollama_available()
    table.add_row("ollama", "[green]available[/green]" if ollama_ok else "[yellow]not found[/yellow]")

    models = discover_models()
    if models:
        table.add_row("models", ", ".join(m.name for m in models))
    else:
        table.add_row("models", "[yellow]none detected[/yellow]")

    ledger = _ledger()
    event_count = ledger.count_events()
    table.add_row("ledger", f"{event_count} events ({_DB_PATH})")

    readme_ok = Path("README.md").exists()
    table.add_row("README.md", "[green]present[/green]" if readme_ok else "[yellow]missing[/yellow]")

    docs_ok = Path("docs").is_dir()
    table.add_row("docs/", "[green]present[/green]" if docs_ok else "[yellow]missing[/yellow]")

    scan = scan_directory(Path("."))
    safety = "[green]clean[/green]" if scan.is_clean else f"[red]{len(scan.issues)} issue(s)[/red]"
    table.add_row("public-safety", safety)

    console.print(table)


@app.command()
def models() -> None:
    """List installed Ollama models. Does not fail if Ollama is missing."""
    available = is_ollama_available()
    if not available:
        console.print("[yellow]Ollama not found. Install from https://ollama.ai[/yellow]")
        return

    discovered = discover_models()
    if not discovered:
        console.print("[yellow]No models installed. Run: ollama pull llama3[/yellow]")
        return

    table = Table(title="Installed Models", box=box.SIMPLE)
    table.add_column("Name")
    table.add_column("ID")
    table.add_column("Size")
    table.add_column("Tier")

    for m in discovered:
        table.add_row(m.name, m.model_id, m.size, "[dim]worker[/dim]")

    console.print(table)
    console.print("[dim]Local Ollama models are worker-tier only.[/dim]")


@app.command("log")
def log_event(
    summary: str = typer.Option("manual log entry", "--summary", "-s", help="Event summary"),
    project: str = typer.Option("opencobalt", "--project", "-p"),
) -> None:
    """Write a session event to the ledger."""
    ledger = _ledger()
    event = SessionEvent(
        project=project,
        source="cli",
        event_type="manual_log",
        summary=summary,
    )
    ledger.insert_event(event)
    console.print(f"[green]Logged:[/green] {event.id}")
    console.print(f"  summary : {summary}")
    console.print(f"  db      : {_DB_PATH}")


@memory_app.command("status")
def memory_status() -> None:
    """Show memory record counts and paths."""
    ledger = _ledger()
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value")
    table.add_row("db path", str(_DB_PATH))
    table.add_row("event count", str(ledger.count_events()))
    table.add_row("memory records", str(ledger.count_memory_records()))
    table.add_row("export path", str(_EXPORT_PATH))
    console.print(table)


@memory_app.command("export")
def memory_export(
    project: str = typer.Option("opencobalt", "--project", "-p"),
) -> None:
    """Export memory records to markdown."""
    ledger = _ledger()
    store = MemoryStore(ledger)
    out = _EXPORT_PATH / f"{project}-memory.md"
    store.export_markdown(project, out)
    console.print(f"[green]Exported:[/green] {out}")


@app.command("context")
def context_build() -> None:
    """Build a context pack from README, docs, and src files."""
    from .core.context import build_context_pack
    pack = build_context_pack(project="opencobalt", output=_CONTEXT_PATH)
    console.print(f"[green]Context pack written:[/green] {_CONTEXT_PATH}")
    console.print(f"  files          : {len(pack.sources)}")
    console.print(f"  token estimate : ~{pack.token_estimate:,}")


@app.command()
def route(task: str = typer.Argument(..., help="Task description to route")) -> None:
    """Return a routing recommendation for a task."""
    decision = route_task(task, record=False)
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value")
    table.add_row("recommended", f"[bold]{decision.recommended_tool}[/bold]")
    table.add_row("tier", decision.tier)
    table.add_row("score", str(decision.score))
    table.add_row("reasoning", decision.reasoning)
    console.print(table)


@app.command()
def verify() -> None:
    """Run pytest and public-check. Record results to ledger."""
    ledger = _ledger()
    results = run_all(root=Path("."), ledger=ledger)
    for r in results:
        icon = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        console.print(f"{icon}  {r.command}: {r.output_summary}")
    if all(r.passed for r in results):
        console.print("[green]All checks passed.[/green]")
    else:
        raise typer.Exit(1)


@app.command()
def doctor() -> None:
    """Run a full system health check."""
    console.print("[bold]OpenCobalt Doctor[/bold]\n")
    status()
    console.print()
    models()


@app.command("public-check")
def public_check() -> None:
    """Scan the repo for public-safety issues."""
    scan = scan_directory(Path("."))
    if scan.is_clean:
        console.print("[green]Public safety: clean[/green]")
    else:
        err.print(scan.summary())
        raise typer.Exit(1)


design_app = typer.Typer(help="Design commands.")
app.add_typer(design_app, name="design")


@design_app.command("brief")
def design_brief(
    project: str = typer.Option("opencobalt", "--project", "-p"),
) -> None:
    """Show the DesignLab brief for this project (placeholder)."""
    console.print("[bold]DesignLab[/bold] -- design intelligence module")
    console.print()
    console.print("Status: [dim]planned -- see docs/DESIGNLAB.md[/dim]")
    console.print()
    console.print("Future capabilities:")
    for item in [
        "Generate design tokens from a project brief",
        "Enforce anti-slop UI rules",
        "Run Playwright screenshots and critique with vision model",
        "Flag generic AI-looking UI patterns",
        "Maintain local style memory across prompts",
    ]:
        console.print(f"  [dim]--[/dim] {item}")
