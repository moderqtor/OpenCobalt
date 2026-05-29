"""OpenCobalt CLI.

Usage:
  opencobalt status
  opencobalt models
  opencobalt log [--summary TEXT]
  opencobalt memory status
  opencobalt memory export
  opencobalt context
  opencobalt route TASK
  opencobalt verify
  opencobalt doctor
  opencobalt public-check
  opencobalt tui
  opencobalt design brief
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .core.cost import CostTracker
from .core.ledger import Ledger
from .core.memory import MemoryStore
from .core.models import SessionEvent
from .core.models_discovery import discover_models, is_ollama_available
from .core.public_safety import scan_directory
from .agents.registry import get_agent, list_agents as _list_agents
from .core.router import _TOOL_PROFILES, route_task
from .core.verify import run_all

app = typer.Typer(
    name="opencobalt",
    help="Local-first AI orchestration and memory control plane.",
    no_args_is_help=True,
    add_completion=False,
)
memory_app = typer.Typer(help="Memory commands.")
app.add_typer(memory_app, name="memory")

cost_app = typer.Typer(help="Cost control commands.")
app.add_typer(cost_app, name="cost")

agents_app = typer.Typer(help="Agent commands.")
app.add_typer(agents_app, name="agents")

integrations_app = typer.Typer(help="Integration commands.")
app.add_typer(integrations_app, name="integrations")

console = Console()
err = Console(stderr=True)

_DB_PATH = Path(".opencobalt") / "ledger.db"
_EXPORT_PATH = Path(".opencobalt") / "exports"
_CONTEXT_PATH = Path(".opencobalt") / "context" / "latest.md"

_COBALT = "#3B7CF4"
_GREEN = "#22c55e"
_YELLOW = "#f59e0b"
_RED = "#ef4444"


def _ledger() -> Ledger:
    return Ledger(_DB_PATH)


def _dot(ok: bool, warn: bool = False) -> str:
    if ok:
        return f"[{_GREEN}]●[/{_GREEN}]"
    if warn:
        return f"[{_YELLOW}]●[/{_YELLOW}]"
    return f"[{_RED}]●[/{_RED}]"


def _tier_color(tier: str) -> str:
    return {
        "executive": _COBALT,
        "manager": _YELLOW,
        "worker": "dim",
    }.get(tier, "")


@app.command()
def status() -> None:
    """Show system status: Python, Ollama, ledger, docs, public safety."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    console.print(
        f"\n  [bold {_COBALT}]OPENCOBALT[/bold {_COBALT}]"
        f"  [dim]control plane · {now}[/dim]\n"
    )

    checks_ok = 0
    checks_total = 0

    # ── System ────────────────────────────────────────────
    console.print(f"  [bold]System[/bold]")
    console.print(f"  [dim]{'─' * 42}[/dim]")
    console.print(f"  {_dot(True)}  [dim]python    [/dim]  {sys.version.split()[0]}")
    console.print(f"  {_dot(True)}  [dim]repo      [/dim]  {Path('.').resolve()}")
    checks_ok += 2
    checks_total += 2
    console.print()

    # ── Models ────────────────────────────────────────────
    with console.status("[dim]Querying Ollama...[/dim]", spinner="dots"):
        ollama_ok = is_ollama_available()
        models = discover_models() if ollama_ok else []

    console.print(f"  [bold]Models[/bold]")
    console.print(f"  [dim]{'─' * 42}[/dim]")
    if ollama_ok:
        console.print(f"  {_dot(True)}  [dim]ollama    [/dim]  available [dim](worker-tier)[/dim]")
        checks_ok += 1
    else:
        console.print(
            f"  {_dot(False, warn=True)}  [dim]ollama    [/dim]  "
            f"[{_YELLOW}]not found[/{_YELLOW}] [dim]-- install from ollama.ai[/dim]"
        )
    checks_total += 1

    if models:
        for m in models:
            console.print(f"  {_dot(True)}  [dim]{m.name:<12}[/dim]  {m.size}")
            checks_ok += 1
            checks_total += 1
    else:
        console.print(f"  {_dot(False, warn=True)}  [dim]models    [/dim]  [{_YELLOW}]none detected[/{_YELLOW}]")
        checks_total += 1
    console.print()

    # ── Ledger ────────────────────────────────────────────
    ledger = _ledger()
    event_count = ledger.count_events()
    memory_count = ledger.count_memory_records()
    ledger_ok = _DB_PATH.exists()

    console.print(f"  [bold]Ledger[/bold]")
    console.print(f"  [dim]{'─' * 42}[/dim]")
    console.print(
        f"  {_dot(ledger_ok)}  [dim]database  [/dim]  "
        f"{event_count} events  [dim]·  {_DB_PATH}[/dim]"
    )
    console.print(f"  {_dot(True)}  [dim]memory    [/dim]  {memory_count} records")
    checks_ok += 2
    checks_total += 2
    console.print()

    # ── Docs ──────────────────────────────────────────────
    readme_ok = Path("README.md").exists()
    docs_ok = Path("docs").is_dir()
    context_ok = _CONTEXT_PATH.exists()

    console.print(f"  [bold]Docs[/bold]")
    console.print(f"  [dim]{'─' * 42}[/dim]")
    console.print(
        f"  {_dot(readme_ok)}  [dim]README.md [/dim]  "
        f"{'present' if readme_ok else f'[{_YELLOW}]missing[/{_YELLOW}]'}"
    )
    console.print(
        f"  {_dot(docs_ok)}  [dim]docs/     [/dim]  "
        f"{'present' if docs_ok else f'[{_YELLOW}]missing[/{_YELLOW}]'}"
    )
    console.print(
        f"  {_dot(context_ok, warn=True)}  [dim]context   [/dim]  "
        + (str(_CONTEXT_PATH) if context_ok else "[dim]not built -- run: opencobalt context[/dim]")
    )
    checks_ok += sum([readme_ok, docs_ok, context_ok])
    checks_total += 3
    console.print()

    # ── Safety ────────────────────────────────────────────
    with console.status("[dim]Scanning...[/dim]", spinner="dots"):
        scan = scan_directory(Path("."))
    safety_ok = scan.is_clean

    console.print(f"  [bold]Safety[/bold]")
    console.print(f"  [dim]{'─' * 42}[/dim]")
    if safety_ok:
        console.print(f"  {_dot(True)}  [dim]scan      [/dim]  clean")
    else:
        console.print(
            f"  {_dot(False)}  [dim]scan      [/dim]  "
            f"[{_RED}]{len(scan.issues)} issue(s)[/{_RED}]"
        )
        for issue in scan.issues[:3]:
            console.print(f"             [dim]{issue}[/dim]")
    checks_ok += 1 if safety_ok else 0
    checks_total += 1
    console.print()

    # ── Health bar ────────────────────────────────────────
    bar_width = 32
    filled = int(bar_width * checks_ok / max(checks_total, 1))
    bar = (
        f"[{_COBALT}]{'█' * filled}[/{_COBALT}]"
        f"[dim]{'░' * (bar_width - filled)}[/dim]"
    )
    console.print(f"  {bar}  [dim]{checks_ok}/{checks_total} healthy[/dim]\n")


@app.command()
def models() -> None:
    """List installed Ollama models (worker-tier only)."""
    with console.status("[dim]Querying Ollama...[/dim]", spinner="dots"):
        available = is_ollama_available()
        discovered = discover_models() if available else []

    if not available:
        console.print(f"  [{_YELLOW}]Ollama not found.[/{_YELLOW}] Install from https://ollama.ai")
        return

    if not discovered:
        console.print(f"  [{_YELLOW}]No models installed.[/{_YELLOW}] Run: ollama pull llama3")
        return

    console.print()
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Name", style=f"{_COBALT}")
    table.add_column("Model ID", style="dim")
    table.add_column("Size")
    table.add_column("Tier", style="dim")

    for m in discovered:
        table.add_row(m.name, m.model_id, m.size, "worker")

    console.print(table)
    console.print(f"  [dim]Local Ollama models are worker-tier only.[/dim]\n")


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
    console.print(f"\n  [{_GREEN}]Logged[/{_GREEN}]  [dim]{event.id}[/dim]")
    console.print(f"  [dim]summary :[/dim]  {summary}")
    console.print(f"  [dim]db      :[/dim]  {_DB_PATH}\n")


@memory_app.command("status")
def memory_status() -> None:
    """Show memory record counts and paths."""
    ledger = _ledger()
    console.print()
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value")
    table.add_row("db path", str(_DB_PATH))
    table.add_row("event count", str(ledger.count_events()))
    table.add_row("memory records", str(ledger.count_memory_records()))
    table.add_row("export path", str(_EXPORT_PATH))
    console.print(table)
    console.print()


@memory_app.command("export")
def memory_export(
    project: str = typer.Option("opencobalt", "--project", "-p"),
) -> None:
    """Export memory records to markdown."""
    ledger = _ledger()
    store = MemoryStore(ledger)
    out = _EXPORT_PATH / f"{project}-memory.md"
    store.export_markdown(project, out)
    console.print(f"\n  [{_GREEN}]Exported[/{_GREEN}]  {out}\n")


@app.command("context")
def context_build() -> None:
    """Build a context pack from README, docs, and src files."""
    from .core.context import build_context_pack

    with console.status("[dim]Compiling context...[/dim]", spinner="dots"):
        pack = build_context_pack(project="opencobalt", output=_CONTEXT_PATH)

    console.print(f"\n  [{_GREEN}]Context pack written[/{_GREEN}]  {_CONTEXT_PATH}")
    console.print(f"  [dim]files          :[/dim]  {len(pack.sources)}")
    console.print(f"  [dim]token estimate :[/dim]  ~{pack.token_estimate:,}\n")


@app.command()
def route(task: str = typer.Argument(..., help="Task description to route")) -> None:
    """Return a routing recommendation with full score table."""
    with console.status("[dim]Scoring...[/dim]", spinner="dots"):
        decision = route_task(task, record=False)

    console.print(f'\n  [bold]Routing:[/bold] [dim]"{task}"[/dim]\n')

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Tool")
    table.add_column("Tier", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("")

    sorted_tools = sorted(decision.scores, key=lambda t: decision.scores[t], reverse=True)
    for tool_name in sorted_tools:
        s = decision.scores[tool_name]
        tier = _TOOL_PROFILES[tool_name]["tier"]
        tc = _tier_color(tier)
        is_winner = tool_name == decision.recommended_tool
        name_str = f"[{tc}]{tool_name}[/{tc}]" if tc != "dim" else f"[dim]{tool_name}[/dim]"
        marker = f"[{_GREEN}]recommended[/{_GREEN}]" if is_winner else ""
        score_str = f"[bold]{s}[/bold]" if is_winner else str(s)
        table.add_row(name_str, tier, score_str, marker)

    console.print(table)
    console.print(f"  [dim]{decision.reasoning}[/dim]\n")


@app.command()
def verify() -> None:
    """Run pytest and public-check. Record results to ledger."""
    ledger = _ledger()
    console.print()
    with console.status("[dim]Running verification...[/dim]", spinner="dots"):
        results = run_all(root=Path("."), ledger=ledger)

    for r in results:
        icon = f"[{_GREEN}]PASS[/{_GREEN}]" if r.passed else f"[{_RED}]FAIL[/{_RED}]"
        console.print(f"  {icon}  {r.command}: {r.output_summary}")

    console.print()
    if all(r.passed for r in results):
        console.print(f"  [{_GREEN}]All checks passed.[/{_GREEN}]\n")
    else:
        console.print(f"  [{_RED}]One or more checks failed.[/{_RED}]\n")
        raise typer.Exit(1)


@app.command()
def doctor() -> None:
    """Run a full system health check."""
    status()
    console.print()
    models()


@app.command("public-check")
def public_check() -> None:
    """Scan the repo for public-safety issues before pushing."""
    with console.status("[dim]Scanning...[/dim]", spinner="dots"):
        scan = scan_directory(Path("."))

    if scan.is_clean:
        console.print(f"\n  [{_GREEN}]Public safety: clean[/{_GREEN}]\n")
    else:
        err.print(f"\n[{_RED}]{scan.summary()}[/{_RED}]\n")
        raise typer.Exit(1)


@app.command()
def tui() -> None:
    """Launch a live terminal dashboard. Press Ctrl+C to exit."""
    _REFRESH = 2

    def _make_header() -> Panel:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return Panel(
            Text(f"OPENCOBALT  control plane · {now}", style=f"bold {_COBALT}"),
            box=box.SIMPLE,
            expand=True,
        )

    def _make_status_panel() -> Panel:
        lines: list[str] = []
        ollama_ok = is_ollama_available()
        lines.append(f"{_dot(True)}  python   {sys.version.split()[0]}")
        lines.append(f"{_dot(ollama_ok, warn=True)}  ollama   {'available' if ollama_ok else 'not found'}")
        ledger = _ledger()
        lines.append(f"{_dot(True)}  events   {ledger.count_events()}")
        lines.append(f"{_dot(True)}  memory   {ledger.count_memory_records()} records")
        readme_ok = Path("README.md").exists()
        lines.append(f"{_dot(readme_ok)}  README   {'present' if readme_ok else 'missing'}")
        return Panel(
            "\n".join(lines),
            title="[dim]Status[/dim]",
            border_style="dim",
            expand=True,
        )

    def _make_events_panel() -> Panel:
        try:
            ledger = _ledger()
            events = ledger.list_events(limit=8)
        except Exception:
            events = []

        if not events:
            body = "[dim]No events recorded.[/dim]"
        else:
            rows = []
            for e in reversed(events):
                ts = e.timestamp.strftime("%H:%M") if hasattr(e.timestamp, "strftime") else str(e.timestamp)[:5]
                rows.append(f"[dim]{ts}[/dim]  {e.event_type:<18}  {e.summary[:40]}")
            body = "\n".join(rows)

        return Panel(body, title="[dim]Recent Events[/dim]", border_style="dim", expand=True)

    def _make_layout() -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
        )
        layout["body"].split_row(
            Layout(name="status"),
            Layout(name="events"),
        )
        return layout

    layout = _make_layout()
    console.print(f"  [dim]OpenCobalt TUI -- Ctrl+C to exit[/dim]\n")

    try:
        with Live(layout, refresh_per_second=1, screen=True):
            while True:
                layout["header"].update(_make_header())
                layout["status"].update(_make_status_panel())
                layout["events"].update(_make_events_panel())
                time.sleep(_REFRESH)
    except KeyboardInterrupt:
        pass


# ── Cost commands ─────────────────────────────────────────────────────────────

@cost_app.command("status")
def cost_status() -> None:
    """Show monthly spend, per-run cap, available budget, and routing mode."""
    tracker = CostTracker(_DB_PATH)
    spend = tracker.monthly_spend()
    cap = tracker.monthly_cap()
    remaining = tracker.budget_remaining()
    per_run = tracker.per_run_cap()
    mode = tracker.get_routing_mode()
    over = tracker.is_over_budget()

    console.print()
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Metric", style="dim")
    table.add_column("Value")

    spend_color = _RED if over else _GREEN
    table.add_row("monthly spend", f"[{spend_color}]${spend:.4f}[/{spend_color}]")
    table.add_row("monthly cap", f"${cap:.2f}")
    table.add_row("per-run cap", f"${per_run:.2f}")
    remaining_color = _RED if remaining < 0 else _YELLOW if remaining < 1.0 else _GREEN
    table.add_row("remaining", f"[{remaining_color}]${remaining:.4f}[/{remaining_color}]")
    table.add_row("routing mode", mode)

    console.print(table)
    console.print()


@cost_app.command("set-mode")
def cost_set_mode(
    mode: str = typer.Argument(..., help="Routing mode: cheap, standard, or frontier"),
) -> None:
    """Change the active routing mode (cheap | standard | frontier)."""
    tracker = CostTracker(_DB_PATH)
    try:
        tracker.set_routing_mode(mode)
        console.print(f"\n  [{_GREEN}]Routing mode set to[/{_GREEN}]  {mode}\n")
    except ValueError as exc:
        err.print(f"\n[{_RED}]Error:[/{_RED}]  {exc}\n")
        raise typer.Exit(1) from exc


# ── Agents commands ───────────────────────────────────────────────────────────

@agents_app.command("list")
def agents_list() -> None:
    """Show all registered agents with tier and capabilities."""
    profiles = _list_agents()
    console.print()
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Name", style=f"{_COBALT}")
    table.add_column("Tier", style="dim")
    table.add_column("Capabilities")
    table.add_column("Local", style="dim")

    for p in profiles:
        tc = _tier_color(p.tier)
        name_str = f"[{tc}]{p.name}[/{tc}]" if tc != "dim" else f"[dim]{p.name}[/dim]"
        caps = ", ".join(p.capabilities) if p.capabilities else "--"
        local = "yes" if p.local_only else "no"
        table.add_row(name_str, p.tier, caps, local)

    console.print(table)
    console.print(f"  [dim]{len(profiles)} agent(s) registered.[/dim]\n")


@agents_app.command("run")
def agents_run(
    agent_name: str = typer.Argument(..., help="Name of the agent to run"),
    task: str = typer.Argument(..., help="Task description to pass to the agent"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Describe what would happen without calling external services"),
) -> None:
    """Run a named agent against a task description."""
    agent = get_agent(agent_name)
    if agent is None:
        err.print(f"\n[{_RED}]Unknown agent: {agent_name}[/{_RED}]")
        err.print(f"  Run: opencobalt agents list\n")
        raise typer.Exit(1)

    with console.status(f"[dim]Running {agent_name}...[/dim]", spinner="dots"):
        result = agent.run(task, dry_run=dry_run)

    console.print(
        f"\n  [bold {_COBALT}]{agent_name}[/bold {_COBALT}]"
        f"  [dim]{agent.tier} tier[/dim]\n"
    )
    console.print(result)
    console.print()


# ── Integrations commands ─────────────────────────────────────────────────────

@integrations_app.command("list")
def integrations_list() -> None:
    """List all registered integrations and their install status."""
    from .integrations.registry import list_integrations
    profiles = list_integrations()
    console.print()
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Name", style=f"{_COBALT}")
    table.add_column("Installed", style="dim")
    table.add_column("Description")
    table.add_column("Source", style="dim")

    for p in profiles:
        installed = f"[{_GREEN}]yes[/{_GREEN}]" if p.installed else f"[{_YELLOW}]no[/{_YELLOW}]"
        table.add_row(p.name, installed, p.description, p.source_url)

    console.print(table)
    console.print(f"  [dim]{len(profiles)} integration(s) registered.[/dim]\n")


# ── UI command ────────────────────────────────────────────────────────────────

@app.command("ui")
def ui_shell() -> None:
    """Print instructions for starting the UI shell."""
    console.print(
        f"\n  [bold {_COBALT}]OpenCobalt UI[/bold {_COBALT}]"
        f"  [dim]web dashboard shell[/dim]\n"
    )
    console.print(f"  UI shell lives at [dim]./ui/[/dim]\n")
    console.print(f"  Start it with:")
    console.print(f"\n    [dim]cd ui && npm install && npm run dev[/dim]\n")
    console.print(f"  Then open [dim]http://localhost:5173[/dim]\n")
    console.print(f"  [dim]Note: backend not wired. Future phase.[/dim]\n")


design_app = typer.Typer(help="Design commands.")
app.add_typer(design_app, name="design")


@design_app.command("brief")
def design_brief(
    project: str = typer.Option("opencobalt", "--project", "-p"),
) -> None:
    """Show the DesignLab brief for this project (placeholder)."""
    console.print(f"\n  [bold {_COBALT}]DesignLab[/bold {_COBALT}]  [dim]design intelligence module[/dim]\n")
    console.print(f"  Status: [dim]planned -- see docs/DESIGNLAB.md[/dim]\n")
    console.print(f"  Future capabilities:")
    for item in [
        "Generate design tokens from a project brief",
        "Enforce anti-slop UI rules across prompts",
        "Run Playwright screenshots and critique with vision model",
        "Flag generic AI-looking UI patterns",
        "Maintain local style memory across sessions",
    ]:
        console.print(f"  [dim]--[/dim]  {item}")
    console.print()
