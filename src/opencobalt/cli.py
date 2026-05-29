"""OpenCobalt CLI.

Usage:
  opencobalt status
  opencobalt models
  opencobalt route TASK
  opencobalt history [--limit N]
  opencobalt stats
  opencobalt benchmark
  opencobalt log [--summary TEXT]
  opencobalt memory status
  opencobalt memory add TEXT
  opencobalt memory export
  opencobalt context
  opencobalt verify
  opencobalt export
  opencobalt doctor
  opencobalt public-check
  opencobalt tui
  opencobalt agents list
  opencobalt agents run NAME TASK
  opencobalt integrations list
  opencobalt cost status
  opencobalt cost set-mode MODE
  opencobalt config get KEY
  opencobalt config set KEY VALUE
  opencobalt config list
  opencobalt ui
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

from .agents.registry import get_agent
from .agents.registry import list_agents as _list_agents
from .core.cost import CostTracker
from .core.ledger import Ledger
from .core.memory import MemoryStore
from .core.models import MemoryRecord, SessionEvent
from .core.models_discovery import discover_models, is_ollama_available
from .core.public_safety import scan_directory
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

config_app = typer.Typer(help="Configuration commands.")
app.add_typer(config_app, name="config")

session_app = typer.Typer(help="Session commands.")
app.add_typer(session_app, name="session")

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
    console.print("  [bold]System[/bold]")
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

    console.print("  [bold]Models[/bold]")
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

    console.print("  [bold]Ledger[/bold]")
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

    console.print("  [bold]Docs[/bold]")
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

    console.print("  [bold]Safety[/bold]")
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
    console.print("  [dim]Local Ollama models are worker-tier only.[/dim]\n")


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


@app.command("log-list")
def log_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of events to show"),
    project: str = typer.Option(None, "--project", "-p", help="Filter by project"),
) -> None:
    """List recent session events from the ledger."""
    ledger = _ledger()
    events = ledger.list_events(limit=limit, project=project)

    if not events:
        console.print("\n  [dim]No events recorded yet.[/dim]")
        console.print("  [dim]Run: opencobalt log --summary \"your note\"[/dim]\n")
        return

    console.print()
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Time", style="dim")
    table.add_column("Type", style="dim")
    table.add_column("Summary")

    for e in events:
        ts = e.timestamp.strftime("%m-%d %H:%M") if hasattr(e.timestamp, "strftime") else str(e.timestamp)[:11]
        table.add_row(ts, e.event_type, e.summary[:70])

    console.print(table)
    console.print(f"  [dim]{len(events)} event(s).[/dim]\n")


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


@memory_app.command("add")
def memory_add(
    content: str = typer.Argument(..., help="Memory content to store"),
    namespace: str = typer.Option("general", "--namespace", "-n", help="Memory namespace"),
    project: str = typer.Option("opencobalt", "--project", "-p"),
) -> None:
    """Write a memory record to the ledger."""
    ledger = _ledger()
    record = MemoryRecord(
        project=project,
        namespace=namespace,
        content=content,
        source="cli",
    )
    ledger.insert_memory_record(record)
    console.print(f"\n  [{_GREEN}]Stored[/{_GREEN}]  [dim]{record.id}[/dim]")
    console.print(f"  [dim]namespace :[/dim]  {namespace}")
    console.print(f"  [dim]content   :[/dim]  {content[:80]}\n")


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
def context_build(
    summarize: bool = typer.Option(False, "--summarize", "-s", help="Summarize the context pack via Ollama after building"),
) -> None:
    """Build a context pack from README, docs, and src files."""
    from .core.context import build_context_pack

    with console.status("[dim]Compiling context...[/dim]", spinner="dots"):
        pack = build_context_pack(project="opencobalt", output=_CONTEXT_PATH)

    console.print(f"\n  [{_GREEN}]Context pack written[/{_GREEN}]  {_CONTEXT_PATH}")
    console.print(f"  [dim]files          :[/dim]  {len(pack.sources)}")
    console.print(f"  [dim]token estimate :[/dim]  ~{pack.token_estimate:,}")

    if summarize:
        agent = get_agent("summarizer")
        if agent is None:
            console.print("  [dim]summarizer agent not available[/dim]")
        else:
            # Use the first 2000 chars of the context pack as input (keep cost low)
            snippet = pack.content[:2000]
            with console.status("[dim]Summarizing via Ollama...[/dim]", spinner="dots"):
                summary = agent.run(f"Summarize this project context in 3 sentences: {snippet}")
            console.print("\n  [dim]Project summary (Ollama):[/dim]")
            console.print(f"  {summary}")
    console.print()


@app.command("context-diff")
def context_diff() -> None:
    """Show what changed in the context pack since the last build."""
    import difflib
    prev = _CONTEXT_PATH.parent / "previous.md"
    curr = _CONTEXT_PATH

    if not curr.exists():
        console.print("\n  [dim]No context pack found. Run: opencobalt context[/dim]\n")
        return
    if not prev.exists():
        console.print("\n  [dim]No previous version found. Run opencobalt context twice to enable diff.[/dim]\n")
        return

    old_lines = prev.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = curr.read_text(encoding="utf-8").splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile="previous", tofile="latest", n=2))

    if not diff:
        console.print("\n  [dim]No changes since last build.[/dim]\n")
        return

    added = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
    console.print("\n  [bold]Context diff[/bold]  [dim]previous -> latest[/dim]")
    console.print(f"  [{_GREEN}]+{added}[/{_GREEN}]  [{_RED}]-{removed}[/{_RED}]  lines changed\n")

    for ln in diff[:60]:
        ln = ln.rstrip("\n")
        if ln.startswith("+") and not ln.startswith("+++"):
            console.print(f"  [{_GREEN}]{ln}[/{_GREEN}]")
        elif ln.startswith("-") and not ln.startswith("---"):
            console.print(f"  [{_RED}]{ln}[/{_RED}]")
        elif ln.startswith("@@"):
            console.print(f"  [dim]{ln}[/dim]")
    if len(diff) > 60:
        console.print(f"\n  [dim]... {len(diff) - 60} more lines[/dim]")
    console.print()


@app.command()
def route(
    task: str = typer.Argument(..., help="Task description to route"),
    no_record: bool = typer.Option(False, "--no-record", help="Skip writing decision to ledger"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-tool keyword matches"),
    estimate: bool = typer.Option(False, "--estimate", help="Show estimated API cost per tier (assumes ~2K tokens)"),
) -> None:
    """Return a routing recommendation with full score table. Logs to ledger by default."""
    with console.status("[dim]Scoring...[/dim]", spinner="dots"):
        decision = route_task(task, record=False)

    # Tag with active session if one is running, then record
    from .core.session import SessionManager
    session_name = SessionManager(_DB_PATH).active()
    if session_name:
        decision.metadata["_session"] = session_name
    if not no_record:
        _ledger().insert_route_decision(decision)

    header = f'\n  [bold]Routing:[/bold] [dim]"{task}"[/dim]'
    if session_name:
        header += f'  [dim](session: {session_name})[/dim]'
    console.print(header + "\n")

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Tool")
    table.add_column("Tier", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Matched keywords", style="dim")
    table.add_column("")

    task_lower = task.lower()
    sorted_tools = sorted(decision.scores, key=lambda t: decision.scores[t], reverse=True)
    for tool_name in sorted_tools:
        s = decision.scores[tool_name]
        tier = _TOOL_PROFILES[tool_name]["tier"]
        tc = _tier_color(tier)
        is_winner = tool_name == decision.recommended_tool
        name_str = f"[{tc}]{tool_name}[/{tc}]" if tc != "dim" else f"[dim]{tool_name}[/dim]"
        marker = f"[{_GREEN}]recommended[/{_GREEN}]" if is_winner else ""
        score_str = f"[bold]{s}[/bold]" if is_winner else str(s)
        matched = [kw for kw in _TOOL_PROFILES[tool_name]["keywords"] if kw in task_lower]
        kw_str = ", ".join(matched[:4]) if (matched and verbose) else ""
        table.add_row(name_str, tier, score_str, kw_str, marker)

    console.print(table)
    console.print(f"  [dim]{decision.reasoning}[/dim]")

    if estimate:
        tracker = CostTracker(_DB_PATH)
        # Estimate cost for ~2K input + ~500 output tokens per tier's representative model
        est_models = [
            ("claude-opus-4", "executive tier"),
            ("claude-sonnet-4-6", "manager tier"),
            ("ollama", "worker tier (free)"),
        ]
        console.print("\n  [dim]Cost estimate (~2K input / 500 output tokens):[/dim]")
        for model_id, label in est_models:
            cost = tracker.estimate_cost(model_id, input_tokens=2000, output_tokens=500)
            cost_str = "free" if cost == 0.0 else f"${cost:.4f}"
            console.print(f"  [dim]{label:<22}[/dim]  {cost_str}")
    console.print()


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
def lint() -> None:
    """Run ruff on src/ and tests/ and report results."""
    import subprocess

    console.print(f"\n  [bold {_COBALT}]Lint[/bold {_COBALT}]  [dim]ruff check src/ tests/[/dim]\n")

    try:
        result = subprocess.run(
            ["ruff", "check", "src/", "tests/"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        err.print(f"\n  [{_YELLOW}]ruff not found.[/{_YELLOW}] Install: pip install ruff\n")
        raise typer.Exit(1)

    if result.returncode == 0:
        console.print(f"  [{_GREEN}]All checks passed.[/{_GREEN}]  No issues found.\n")
    else:
        lines = (result.stdout + result.stderr).strip().split("\n")
        for line in lines[:30]:
            console.print(f"  [dim]{line}[/dim]")
        if len(lines) > 30:
            console.print(f"  [dim]... {len(lines) - 30} more lines[/dim]")
        console.print(f"\n  [{_RED}]Lint issues found.[/{_RED}]  Run: ruff check src/ tests/ --fix\n")

        # Route suggestion: which tool should fix this?
        decision = route_task("fix linting and code style issues", record=False)
        tc = _tier_color(decision.tier)
        tool = f"[{tc}]{decision.recommended_tool}[/{tc}]" if tc != "dim" else f"[dim]{decision.recommended_tool}[/dim]"
        console.print(f"  [dim]Suggested tool:[/dim]  {tool}  [dim](score {decision.score})[/dim]\n")
        raise typer.Exit(1)


@app.command()
def doctor() -> None:
    """Run a full system health check: status, models, lint, CI config."""
    status()
    console.print()
    models()
    console.print()

    # Extra doctor checks
    console.print("  [bold]Checks[/bold]")
    console.print(f"  [dim]{'─' * 42}[/dim]")

    # pyproject.toml
    pyproject_ok = Path("pyproject.toml").exists()
    console.print(
        f"  {_dot(pyproject_ok)}  [dim]pyproject.toml[/dim]  "
        f"{'present' if pyproject_ok else f'[{_RED}]missing[/{_RED}]'}"
    )

    # CI workflow
    ci_ok = Path(".github/workflows/ci.yml").exists()
    console.print(
        f"  {_dot(ci_ok)}  [dim]CI workflow   [/dim]  "
        f"{'present' if ci_ok else f'[{_YELLOW}]missing[/{_YELLOW}]'}"
    )

    # examples/
    examples_ok = Path("examples").is_dir() and any(Path("examples").glob("*.py"))
    console.print(
        f"  {_dot(examples_ok)}  [dim]examples/     [/dim]  "
        f"{'present' if examples_ok else f'[{_YELLOW}]missing[/{_YELLOW}]'}"
    )

    # ui/
    ui_ok = Path("ui/package.json").exists()
    console.print(
        f"  {_dot(ui_ok)}  [dim]UI shell      [/dim]  "
        f"{'present' if ui_ok else f'[{_YELLOW}]missing[/{_YELLOW}]'}"
    )

    # CHANGELOG
    changelog_ok = Path("CHANGELOG.md").exists()
    console.print(
        f"  {_dot(changelog_ok)}  [dim]CHANGELOG.md  [/dim]  "
        f"{'present' if changelog_ok else f'[{_YELLOW}]missing[/{_YELLOW}]'}"
    )
    console.print()


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
            events = ledger.list_events(limit=6)
        except Exception:
            events = []

        if not events:
            body = "[dim]No events recorded.[/dim]"
        else:
            rows = []
            for e in reversed(events):
                ts = e.timestamp.strftime("%H:%M") if hasattr(e.timestamp, "strftime") else str(e.timestamp)[:5]
                rows.append(f"[dim]{ts}[/dim]  {e.event_type:<18}  {e.summary[:38]}")
            body = "\n".join(rows)

        return Panel(body, title="[dim]Recent Events[/dim]", border_style="dim", expand=True)

    def _make_routes_panel() -> Panel:
        try:
            ledger = _ledger()
            decisions = ledger.list_route_decisions(limit=6)
        except Exception:
            decisions = []

        if not decisions:
            body = "[dim]No route decisions yet.[/dim]\n[dim]Run: opencobalt route \"your task\"[/dim]"
        else:
            rows = []
            for d in decisions:
                ts = d.timestamp.strftime("%H:%M") if hasattr(d.timestamp, "strftime") else str(d.timestamp)[:5]
                tc = _tier_color(d.tier)
                tool = f"[{tc}]{d.recommended_tool:<13}[/{tc}]" if tc != "dim" else f"[dim]{d.recommended_tool:<13}[/dim]"
                rows.append(f"[dim]{ts}[/dim]  {tool}  {d.task[:28]}")
            body = "\n".join(rows)

        return Panel(body, title="[dim]Route Decisions[/dim]", border_style="dim", expand=True)

    def _make_cost_panel() -> Panel:
        try:
            tracker = CostTracker(_DB_PATH)
            spend = tracker.monthly_spend()
            cap = tracker.monthly_cap()
            mode = tracker.get_routing_mode()
            over = tracker.is_over_budget()
            spend_color = _RED if over else _GREEN
            body = (
                f"{_dot(not over)}  spend    [{spend_color}]${spend:.4f}[/{spend_color}] / ${cap:.2f}\n"
                f"{_dot(True)}   mode     {mode}\n"
                f"{_dot(True)}   api      [dim]disabled (default)[/dim]"
            )
        except Exception:
            body = "[dim]Cost tracker unavailable.[/dim]"

        return Panel(body, title="[dim]Cost Control[/dim]", border_style="dim", expand=True)

    def _make_layout() -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
        )
        layout["body"].split_column(
            Layout(name="top"),
            Layout(name="bottom"),
        )
        layout["body"]["top"].split_row(
            Layout(name="status"),
            Layout(name="routes"),
        )
        layout["body"]["bottom"].split_row(
            Layout(name="events"),
            Layout(name="cost"),
        )
        return layout

    layout = _make_layout()
    console.print("  [dim]OpenCobalt TUI -- Ctrl+C to exit[/dim]\n")

    try:
        with Live(layout, refresh_per_second=1, screen=True):
            while True:
                layout["header"].update(_make_header())
                layout["body"]["top"]["status"].update(_make_status_panel())
                layout["body"]["top"]["routes"].update(_make_routes_panel())
                layout["body"]["bottom"]["events"].update(_make_events_panel())
                layout["body"]["bottom"]["cost"].update(_make_cost_panel())
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
        err.print("  Run: opencobalt agents list\n")
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
    console.print("  UI shell lives at [dim]./ui/[/dim]\n")
    console.print("  Start it with:")
    console.print("\n    [dim]cd ui && npm install && npm run dev[/dim]\n")
    console.print("  Then open [dim]http://localhost:5173[/dim]\n")
    console.print("  [dim]Note: backend not wired. Future phase.[/dim]\n")


# ── Stats command ─────────────────────────────────────────────────────────────

@app.command()
def stats() -> None:
    """Show analytics from the ledger: route counts, tier breakdown, top tools."""
    from collections import Counter
    from datetime import timedelta, timezone

    ledger = _ledger()
    decisions = ledger.list_route_decisions(limit=500)
    events = ledger.list_events(limit=500)
    results = ledger.list_verification_results(limit=50)

    console.print(f"\n  [bold {_COBALT}]Ledger Stats[/bold {_COBALT}]\n")

    # Overall counts
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Metric", style="dim")
    table.add_column("Value")
    table.add_row("route decisions", str(len(decisions)))
    table.add_row("session events", str(len(events)))
    table.add_row("verifications run", str(len(results)))
    passed = sum(1 for r in results if r.passed)
    if results:
        table.add_row("verification pass rate", f"{passed}/{len(results)}")
    console.print(table)

    if decisions:
        # Tier breakdown
        console.print("\n  [dim]Tier breakdown[/dim]")
        tier_counts: Counter = Counter(d.tier for d in decisions)
        tier_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        tier_table.add_column("Tier", style="dim")
        tier_table.add_column("Count", justify="right")
        tier_table.add_column("Bar")
        total = len(decisions)
        for tier in ("executive", "manager", "worker"):
            count = tier_counts.get(tier, 0)
            bar_len = int(20 * count / total) if total else 0
            tc = _tier_color(tier)
            bar = f"[{tc}]{'█' * bar_len}[/{tc}][dim]{'░' * (20 - bar_len)}[/dim]"
            tier_table.add_row(tier, str(count), bar)
        console.print(tier_table)

        # Top tools
        console.print("\n  [dim]Top tools[/dim]")
        tool_counts: Counter = Counter(d.recommended_tool for d in decisions)
        tool_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        tool_table.add_column("Tool")
        tool_table.add_column("Count", justify="right", style="dim")
        for tool, count in tool_counts.most_common(5):
            tier = _TOOL_PROFILES.get(tool, {}).get("tier", "")
            tc = _tier_color(tier)
            name_str = f"[{tc}]{tool}[/{tc}]" if tc != "dim" else f"[dim]{tool}[/dim]"
            tool_table.add_row(name_str, str(count))
        console.print(tool_table)

        # Recent activity (last 7 days)
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=7)
        recent = [
            d for d in decisions
            if (d.timestamp if hasattr(d.timestamp, "tzinfo") and d.timestamp.tzinfo else d.timestamp) >= cutoff
        ]
        console.print(f"\n  [dim]Last 7 days:[/dim]  {len(recent)} route decision(s)\n")
    else:
        console.print("\n  [dim]No route decisions yet. Run: opencobalt route \"your task\"[/dim]\n")


# ── History command ───────────────────────────────────────────────────────────

@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of decisions to show"),
) -> None:
    """Show recent route decisions from the ledger."""
    ledger = _ledger()
    decisions = ledger.list_route_decisions(limit=limit)

    if not decisions:
        console.print("\n  [dim]No route decisions recorded yet.[/dim]")
        console.print("  [dim]Run: opencobalt route \"your task\"[/dim]\n")
        return

    console.print()
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Time", style="dim")
    table.add_column("Tool", style=f"{_COBALT}")
    table.add_column("Tier", style="dim")
    table.add_column("Score", justify="right", style="dim")
    table.add_column("Task")

    for d in decisions:
        ts = d.timestamp.strftime("%m-%d %H:%M") if hasattr(d.timestamp, "strftime") else str(d.timestamp)[:11]
        tc = _tier_color(d.tier)
        tool_str = f"[{tc}]{d.recommended_tool}[/{tc}]" if tc != "dim" else f"[dim]{d.recommended_tool}[/dim]"
        task_short = d.task[:55] + "..." if len(d.task) > 55 else d.task
        table.add_row(ts, tool_str, d.tier, str(d.score), task_short)

    console.print(table)
    console.print(f"  [dim]{len(decisions)} decision(s). Run with --limit N for more.[/dim]\n")


# ── Config commands ───────────────────────────────────────────────────────────

@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Config key to read"),
) -> None:
    """Get a config value."""
    from .core.config import Config
    cfg = Config(_DB_PATH)
    val = cfg.get(key)
    if val is None:
        err.print(f"\n[{_YELLOW}]Key not set:[/{_YELLOW}]  {key}\n")
        raise typer.Exit(1)
    console.print(f"\n  [dim]{key}[/dim]  {val}\n")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key"),
    value: str = typer.Argument(..., help="Value to store"),
) -> None:
    """Set a config value."""
    from .core.config import Config
    cfg = Config(_DB_PATH)
    cfg.set(key, value)
    console.print(f"\n  [{_GREEN}]Set[/{_GREEN}]  [dim]{key}[/dim]  =  {value}\n")


@config_app.command("list")
def config_list() -> None:
    """Show all config keys and values."""
    from .core.config import Config
    cfg = Config(_DB_PATH)
    all_cfg = cfg.list_all()

    if not all_cfg:
        console.print("\n  [dim]No config values set.[/dim]\n")
        return

    console.print()
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value")
    for k, v in all_cfg.items():
        table.add_row(k, v)
    console.print(table)
    console.print()


# ── Benchmark command ─────────────────────────────────────────────────────────

_BENCHMARK_TASKS = [
    "design the authentication module architecture",
    "summarize this session log",
    "write unit tests for the router",
    "fix the null pointer exception in events.py",
    "tag these meeting notes for the knowledge base",
    "analyze all files in the codebase for security issues",
    "refactor the context compiler module",
    "extract key decisions from this transcript",
    "review the public safety scanner for edge cases",
    "implement the agent registry API",
]


@app.command()
def benchmark() -> None:
    """Route a set of representative tasks and show the full scoring breakdown."""
    console.print(f"\n  [bold {_COBALT}]Benchmark[/bold {_COBALT}]  [dim]{len(_BENCHMARK_TASKS)} tasks[/dim]\n")

    with console.status("[dim]Routing all tasks...[/dim]", spinner="dots"):
        decisions = [route_task(t, record=False) for t in _BENCHMARK_TASKS]

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Task", no_wrap=False)
    table.add_column("Tool")
    table.add_column("Tier", style="dim")
    table.add_column("Score", justify="right", style="dim")

    from collections import Counter
    tier_counts: Counter = Counter()

    for d in decisions:
        tc = _tier_color(d.tier)
        tool_str = f"[{tc}]{d.recommended_tool}[/{tc}]" if tc != "dim" else f"[dim]{d.recommended_tool}[/dim]"
        task_short = d.task[:50] + "..." if len(d.task) > 50 else d.task
        table.add_row(task_short, tool_str, d.tier, str(d.score))
        tier_counts[d.tier] += 1

    console.print(table)

    summary = "  ".join(f"[dim]{tier}:[/dim] {count}" for tier, count in sorted(tier_counts.items()))
    console.print(f"  {summary}\n")


# ── Export command ────────────────────────────────────────────────────────────

@app.command()
def export() -> None:
    """Export the full ledger to a timestamped markdown report."""
    from datetime import timezone
    ledger = _ledger()
    now = datetime.now(tz=timezone.utc)
    slug = now.strftime("%Y-%m-%d-%H%M")
    out_dir = _EXPORT_PATH
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"ledger-{slug}.md"

    events = ledger.list_events(limit=200)
    decisions = ledger.list_route_decisions(limit=100)
    results = ledger.list_verification_results(limit=50)

    lines: list[str] = [
        "# OpenCobalt Ledger Export",
        "",
        f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Summary",
        "",
        "| Table | Count |",
        "|-------|-------|",
        f"| Events | {len(events)} |",
        f"| Route decisions | {len(decisions)} |",
        f"| Verification results | {len(results)} |",
        "",
    ]

    if decisions:
        lines += ["## Route Decisions", "", "| Time | Task | Tool | Tier | Score |", "|------|------|------|------|-------|"]
        for d in decisions:
            ts = d.timestamp.strftime("%Y-%m-%d %H:%M") if hasattr(d.timestamp, "strftime") else str(d.timestamp)[:16]
            lines.append(f"| {ts} | {d.task[:60]} | {d.recommended_tool} | {d.tier} | {d.score} |")
        lines.append("")

    if events:
        lines += ["## Events", "", "| Time | Type | Summary |", "|------|------|---------|"]
        for e in events:
            ts = e.timestamp.strftime("%Y-%m-%d %H:%M") if hasattr(e.timestamp, "strftime") else str(e.timestamp)[:16]
            lines.append(f"| {ts} | {e.event_type} | {e.summary[:80]} |")
        lines.append("")

    if results:
        lines += ["## Verification Results", "", "| Time | Command | Passed | Summary |", "|------|---------|--------|---------|"]
        for r in results:
            ts = r.timestamp.strftime("%Y-%m-%d %H:%M") if hasattr(r.timestamp, "strftime") else str(r.timestamp)[:16]
            passed = "yes" if r.passed else "no"
            lines.append(f"| {ts} | {r.command} | {passed} | {r.output_summary[:60]} |")
        lines.append("")

    out.write_text("\n".join(lines))

    console.print(f"\n  [{_GREEN}]Exported[/{_GREEN}]  {out}")
    console.print(f"  [dim]{len(decisions)} decisions  {len(events)} events  {len(results)} results[/dim]\n")


# ── Session commands ──────────────────────────────────────────────────────────

@session_app.command("start")
def session_start(
    name: str = typer.Argument(..., help="Session name (e.g. auth-refactor, sprint-12)"),
) -> None:
    """Start a named work session. Route decisions and events are tagged with this name."""
    from .core.session import SessionManager
    mgr = SessionManager(_DB_PATH)
    current = mgr.active()
    if current:
        console.print(f"\n  [{_YELLOW}]Session already active:[/{_YELLOW}]  {current}")
        console.print("  [dim]Run: opencobalt session end[/dim]\n")
        raise typer.Exit(1)
    mgr.start(name)
    console.print(f"\n  [{_GREEN}]Session started[/{_GREEN}]  {name}\n")


@session_app.command("end")
def session_end() -> None:
    """End the active session."""
    from .core.session import SessionManager
    mgr = SessionManager(_DB_PATH)
    name = mgr.end()
    if name:
        console.print(f"\n  [{_GREEN}]Session ended[/{_GREEN}]  {name}\n")
    else:
        console.print("\n  [dim]No active session.[/dim]\n")


@session_app.command("show")
def session_show() -> None:
    """Show the active session and recent decisions within it."""
    from .core.session import SessionManager
    mgr = SessionManager(_DB_PATH)
    name = mgr.active()
    started = mgr.started_at()

    if not name:
        console.print("\n  [dim]No active session.[/dim]")
        console.print("  [dim]Run: opencobalt session start \"name\"[/dim]\n")
        return

    console.print(f"\n  [bold {_COBALT}]Session[/bold {_COBALT}]  {name}")
    if started:
        console.print(f"  [dim]started:[/dim]  {started[:16]}")

    # Show decisions tagged with this session
    ledger = _ledger()
    all_decisions = ledger.list_route_decisions(limit=200)
    decisions = [d for d in all_decisions if d.metadata.get("_session") == name]

    if decisions:
        console.print(f"  [dim]{len(decisions)} route decision(s) this session[/dim]")
        console.print()
        table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
        table.add_column("Time", style="dim")
        table.add_column("Tool", style=f"{_COBALT}")
        table.add_column("Tier", style="dim")
        table.add_column("Task")
        for d in decisions:
            ts = d.timestamp.strftime("%H:%M") if hasattr(d.timestamp, "strftime") else str(d.timestamp)[:5]
            table.add_row(ts, d.recommended_tool, d.tier, d.task[:50])
        console.print(table)
    else:
        console.print("  [dim]No route decisions yet in this session.[/dim]")
        console.print("  [dim]Run: opencobalt route \"your task\"[/dim]")
    console.print()


design_app = typer.Typer(help="Design commands.")
app.add_typer(design_app, name="design")


@design_app.command("brief")
def design_brief(
    project: str = typer.Option("opencobalt", "--project", "-p"),
) -> None:
    """Show the DesignLab brief for this project (placeholder)."""
    console.print(f"\n  [bold {_COBALT}]DesignLab[/bold {_COBALT}]  [dim]design intelligence module[/dim]\n")
    console.print("  Status: [dim]planned -- see docs/DESIGNLAB.md[/dim]\n")
    console.print("  Future capabilities:")
    for item in [
        "Generate design tokens from a project brief",
        "Enforce anti-slop UI rules across prompts",
        "Run Playwright screenshots and critique with vision model",
        "Flag generic AI-looking UI patterns",
        "Maintain local style memory across sessions",
    ]:
        console.print(f"  [dim]--[/dim]  {item}")
    console.print()
