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
  opencobalt desktop
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
from .core.orchestrator import OrchestrationSession
from .core.public_safety import scan_directory
from .core.router import _TOOL_PROFILES, route_task
from .core.verify import run_all

app = typer.Typer(
    name="opencobalt",
    help="Local-first AI orchestration and memory control plane.",
    no_args_is_help=False,
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

skills_app = typer.Typer(help="Skill commands.")
app.add_typer(skills_app, name="skills")

# invoke_without_command keeps bare `opencobalt benchmark` working (tested in test_cli.py)
benchmark_app = typer.Typer(help="Benchmark commands.", invoke_without_command=True)
app.add_typer(benchmark_app, name="benchmark")

console = Console()
err = Console(stderr=True)

_DB_PATH = Path(".opencobalt") / "ledger.db"
_MEMORIES_DB = Path(".opencobalt") / "memories.db"
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


@app.callback(invoke_without_command=True)
def _main(ctx: typer.Context) -> None:
    """OpenCobalt: local-first AI orchestration shell."""
    if ctx.invoked_subcommand is None:
        from .shell import CobaltShell

        shell = CobaltShell(db_path=_DB_PATH, bridge_path=_MEMORIES_DB)
        shell.run()


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


@app.command("note")
def note(
    text: str = typer.Argument(..., help="Note content to store"),
    agent: str = typer.Option("user", "--agent", "-a", help="Agent name to tag this note"),
    tags: str = typer.Option("", "--tags", "-t", help="Comma-separated tags"),
) -> None:
    """Store a quick note in the memory bridge."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    metadata: dict = {"type": "note", "tags": tag_list}
    try:
        bridge = _memory_bridge()
        bridge.add(text, agent_id=agent, metadata=metadata)
    except Exception as exc:
        console.print(f"  [{_YELLOW}]memory bridge unavailable:[/{_YELLOW}]  {exc}")
        return
    console.print(f"  [{_GREEN}]Noted.[/{_GREEN}] [dim]Search it later with: opencobalt memory search[/dim]")
    console.print(f"  [dim]content : [/dim] {text[:80]}")


@app.command("day")
def day(
    date: str = typer.Option("", "--date", "-d", help="Date to show (YYYY-MM-DD). Defaults to today UTC."),
) -> None:
    """Show a daily summary: route decisions, notes, and session range."""
    import json as _json
    from datetime import date as _date
    from datetime import timezone

    if date:
        try:
            target_date = _date.fromisoformat(date)
        except ValueError:
            console.print(f"  [{_RED}]Invalid date format:[/{_RED}]  {date}  (use YYYY-MM-DD)")
            raise typer.Exit(1)
    else:
        target_date = datetime.now(tz=timezone.utc).date()

    target_str = target_date.isoformat()

    # Fetch route decisions
    try:
        ledger = _ledger()
        all_decisions = ledger.list_route_decisions(limit=500)
        routes = [
            d for d in all_decisions
            if (d.timestamp.date() if hasattr(d.timestamp, "date") else _date.fromisoformat(str(d.timestamp)[:10])) == target_date
        ]
    except Exception:
        routes = []

    # Fetch notes from memory bridge
    try:
        bridge = _memory_bridge()
        all_mems = bridge.recent(limit=500)
        notes = [
            m for m in all_mems
            if m.get("timestamp", "")[:10] == target_str
            and _json.loads(m.get("metadata", "{}")).get("type") == "note"
        ]
    except Exception:
        notes = []

    # Fetch events
    try:
        ledger = _ledger()
        all_events = ledger.list_events(limit=500)
        events = [
            e for e in all_events
            if (e.timestamp.date() if hasattr(e.timestamp, "date") else _date.fromisoformat(str(e.timestamp)[:10])) == target_date
        ]
    except Exception:
        events = []

    if not routes and not notes and not events:
        console.print(
            f"\n  No activity logged for {target_str}. "
            r"Start with: opencobalt route \[your task]"
            "\n"
        )
        return

    console.print(f"\n  [bold {_COBALT}]Day summary[/bold {_COBALT}]  [dim]{target_str}[/dim]\n")

    # Routes table
    console.print(f"  [bold]ROUTES TODAY ({len(routes)})[/bold]")
    if routes:
        rt = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
        rt.add_column("Time", style="dim")
        rt.add_column("Tool", style=f"{_COBALT}")
        rt.add_column("Tier", style="dim")
        rt.add_column("Task")
        for d in routes:
            ts = d.timestamp.strftime("%H:%M") if hasattr(d.timestamp, "strftime") else str(d.timestamp)[11:16]
            tc = _tier_color(d.tier)
            tool_str = f"[{tc}]{d.recommended_tool}[/{tc}]" if tc != "dim" else f"[dim]{d.recommended_tool}[/dim]"
            rt.add_row(ts, tool_str, d.tier, d.task[:50])
        console.print(rt)
    console.print()

    # Notes table
    console.print(f"  [bold]NOTES TODAY ({len(notes)})[/bold]")
    if notes:
        nt = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
        nt.add_column("Time", style="dim")
        nt.add_column("Agent", style="dim")
        nt.add_column("Content")
        for m in notes:
            ts = m.get("timestamp", "")[11:16]
            nt.add_row(ts, m.get("agent_id", ""), m.get("content", "")[:70])
        console.print(nt)
    console.print()

    # Sessions time range
    all_ts: list[str] = []
    for d in routes:
        all_ts.append(d.timestamp.isoformat() if hasattr(d.timestamp, "isoformat") else str(d.timestamp))
    for e in events:
        all_ts.append(e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp))
    if all_ts:
        earliest = min(all_ts)[:16].replace("T", " ")
        latest = max(all_ts)[:16].replace("T", " ")
        console.print(f"  [bold]SESSIONS[/bold]  [dim]{earliest} -- {latest}[/dim]")

    # Cost (month-to-date approximation -- no per-day breakdown)
    try:
        spend = CostTracker(_DB_PATH).monthly_spend()
        console.print(f"  [bold]COST[/bold]  [dim]~${spend:.4f} month-to-date (approx)[/dim]")
    except Exception:
        pass
    console.print()

def _memory_bridge():
    from .memory_bridge import MemoryBridge

    return MemoryBridge(db_path=_MEMORIES_DB)


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

    try:
        bridge = _memory_bridge()
        table.add_row("bridge db", str(_MEMORIES_DB))
        table.add_row("bridge entries", str(bridge.count()))
        if _MEMORIES_DB.exists():
            size_kb = _MEMORIES_DB.stat().st_size // 1024
            table.add_row("bridge size", f"{size_kb} KB")
    except Exception:
        table.add_row("bridge", "[dim]unavailable[/dim]")

    console.print(table)
    console.print()


@memory_app.command("add")
def memory_add(
    content: str = typer.Argument(..., help="Memory content to store"),
    namespace: str = typer.Option("general", "--namespace", "-n", help="Memory namespace"),
    project: str = typer.Option("opencobalt", "--project", "-p"),
    agent: str = typer.Option("", "--agent", "-a", help="Also write to bridge store for this agent"),
) -> None:
    """Write a memory record to the ledger. Pass --agent to also write to the bridge store."""
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
    console.print(f"  [dim]content   :[/dim]  {content[:80]}")

    if agent:
        try:
            bridge = _memory_bridge()
            bridge_id = bridge.add(content, agent_id=agent)
            console.print(f"  [dim]bridge id :[/dim]  {bridge_id}  [dim](agent: {agent})[/dim]")
        except Exception as exc:
            console.print(f"  [{_YELLOW}]bridge write failed:[/{_YELLOW}]  {exc}")

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


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search terms"),
    agent: str = typer.Option("", "--agent", "-a", help="Filter by agent name"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max results"),
) -> None:
    """Search the bridge memory store."""
    try:
        bridge = _memory_bridge()
        results = bridge.search(query, agent_id=agent, limit=limit)
    except Exception as exc:
        err.print(f"[{_RED}]bridge error:[/{_RED}]  {exc}")
        raise typer.Exit(1)

    console.print()
    if not results:
        console.print(f"  [dim]No results for:[/dim]  {query}\n")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Agent", style="dim")
    table.add_column("Content")
    table.add_column("Timestamp", style="dim")
    for r in results:
        table.add_row(r["agent_id"], r["content"][:80], r["timestamp"][:19])
    console.print(table)
    console.print(f"  [dim]{len(results)} result(s)[/dim]\n")


@memory_app.command("sessions")
def memory_sessions(
    limit: int = typer.Option(10, "--limit", "-l", help="Max sessions"),
) -> None:
    """List recent session summaries from the bridge store."""
    try:
        bridge = _memory_bridge()
        import json as _json

        rows = bridge.recent(limit=limit)
        summaries = [
            r for r in rows
            if _json.loads(r.get("metadata", "{}")).get("type") == "session_summary"
        ]
    except Exception as exc:
        err.print(f"[{_RED}]bridge error:[/{_RED}]  {exc}")
        raise typer.Exit(1)

    console.print()
    if not summaries:
        console.print("  [dim]No session summaries stored yet.[/dim]\n")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Session", style="dim")
    table.add_column("Agent", style="dim")
    table.add_column("Summary")
    table.add_column("Timestamp", style="dim")
    for r in summaries:
        table.add_row(r["session_id"][:12], r["agent_id"], r["content"][:60], r["timestamp"][:19])
    console.print(table)
    console.print(f"  [dim]{len(summaries)} session summary(ies)[/dim]\n")


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
    exec_: bool = typer.Option(False, "--exec", help="Open the winning tool after routing"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what --exec would do without opening anything"),
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
    console.print(
        "  [dim]To log what you did:[/dim]  "
        'opencobalt note "[what you accomplished]"'
    )
    console.print("  [dim]Context for this session:[/dim]  opencobalt brief --copy")

    if estimate:
        tracker = CostTracker(_DB_PATH)
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

    if exec_ or dry_run:
        _route_exec(decision.recommended_tool, task, dry_run=dry_run)

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
def orch(
    task: str = typer.Argument(..., help="Task to orchestrate across multiple agents"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full synthesis output"),
) -> None:
    """Dispatch a task to multiple specialized agents in parallel."""
    session = OrchestrationSession()
    console.print(f"\n  [bold]orchestrating[/bold]  [dim]{task[:60]}[/dim]\n")
    result = session.run(task)

    for st in result.subtasks:
        status = "ok" if st.id in result.outputs else "skipped"
        console.print(f"  [dim]{status}  {st.task_type} -> {st.preferred_tool}[/dim]")

    console.print()
    from rich.markup import escape as _escape
    lines = result.synthesis.splitlines()
    display_lines = lines if verbose else lines[:20]
    for line in display_lines:
        console.print(f"  {_escape(line)}")
    if not verbose and len(lines) > 20:
        console.print(f"  [dim]... {len(lines) - 20} more lines (use --verbose)[/dim]")

    status_str = "success" if result.success else "partial"
    console.print(f"\n  [dim]{status_str} · {result.elapsed_s}s[/dim]\n")

    if result.errors:
        for err in result.errors:
            console.print(f"  [dim]error: {err}[/dim]")


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

_OBS_DB = Path(".opencobalt") / "observability.db"


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

    try:
        from .observability import ObservabilitySession

        obs = ObservabilitySession(db_path=_OBS_DB)
        stats = obs.summary_stats()
        table.add_row("obs sessions", str(stats["total"]))
        if stats["total"] > 0:
            table.add_row("obs success rate", f"{stats['success_rate']:.0%}")
            table.add_row("obs total cost", f"${stats['total_cost_usd']:.6f}")
    except Exception:
        pass

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


@cost_app.command("reset")
def cost_reset(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Delete all cost records for the current calendar month."""
    if not confirm:
        console.print(f"\n  [{_YELLOW}]This will delete all cost records for the current month.[/{_YELLOW}]")
        console.print("  Re-run with --yes to confirm.\n")
        raise typer.Exit(0)

    tracker = CostTracker(_DB_PATH)
    tracker.reset_monthly_records()
    console.print(f"\n  [{_GREEN}]Monthly cost records cleared.[/{_GREEN}]\n")


# ── Skills commands ───────────────────────────────────────────────────────────

@skills_app.command("list")
def skills_list(
    agent: str = typer.Option(None, "--agent", "-a", help="Filter to skills compatible with this agent"),
) -> None:
    """List registered skills, optionally filtered by compatible agent."""
    from .skills.registry import list_skills

    skills = list_skills(agent=agent)
    console.print()

    if not skills:
        if agent:
            console.print(f"  [dim]No skills registered for agent: {agent}[/dim]\n")
        else:
            console.print("  [dim]No skills registered.[/dim]\n")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Name", style=f"{_COBALT}")
    table.add_column("Description")

    for entry in skills:
        table.add_row(entry["name"], entry["description"])

    header = f"Skills for agent: {agent}" if agent else "All skills"
    console.print(f"  [dim]{header}[/dim]")
    console.print(table)
    console.print(f"  [dim]{len(skills)} skill(s) registered.[/dim]\n")


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
    import time as _time

    agent = get_agent(agent_name)
    if agent is None:
        err.print(f"\n[{_RED}]Unknown agent: {agent_name}[/{_RED}]")
        err.print("  Run: opencobalt agents list\n")
        raise typer.Exit(1)

    # Start observability session
    obs_sid: str | None = None
    try:
        from .observability import ObservabilitySession

        obs = ObservabilitySession(db_path=_OBS_DB)
        obs_sid = obs.start_session(agent_id=agent_name, task=task, model=agent.tier)
    except Exception:
        pass

    t0 = _time.monotonic()
    success = True
    try:
        with console.status(f"[dim]Running {agent_name}...[/dim]", spinner="dots"):
            result = agent.run(task, dry_run=dry_run)
    except Exception:
        success = False
        raise
    finally:
        elapsed_ms = int((_time.monotonic() - t0) * 1000)
        # End observability session
        if obs_sid is not None:
            try:
                obs.end_session(obs_sid, success=success)
            except Exception:
                pass
        # Write result to memory bridge (opt-in: only when bridge accessible)
        if success and not dry_run:
            try:
                bridge = _memory_bridge()
                bridge.add(
                    content=result[:500],
                    agent_id=agent_name,
                    metadata={"task": task[:100], "latency_ms": elapsed_ms},
                )
            except Exception:
                pass

    console.print(
        f"\n  [bold {_COBALT}]{agent_name}[/bold {_COBALT}]"
        f"  [dim]{agent.tier} tier[/dim]\n"
    )
    console.print(result)
    console.print()


# ── Integrations commands ─────────────────────────────────────────────────────

@integrations_app.command("list")
def integrations_list() -> None:
    """List all registered integrations with tier, status, and capabilities."""
    from .integrations.registry import list_integrations
    profiles = list_integrations()
    console.print()
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Name", style=f"{_COBALT}")
    table.add_column("Tier", style="dim")
    table.add_column("Status")
    table.add_column("Capabilities", style="dim")

    for p in profiles:
        tc = _tier_color(p.tier)
        tier_str = f"[{tc}]{p.tier}[/{tc}]" if tc != "dim" else f"[dim]{p.tier}[/dim]"
        status_color = _GREEN if p.integration_status == "active" else (
            _YELLOW if p.integration_status == "available" else "dim"
        )
        status_str = f"[{status_color}]{p.integration_status}[/{status_color}]"
        caps = ", ".join(p.capabilities) if p.capabilities else "--"
        table.add_row(p.name, tier_str, status_str, caps)

    console.print(table)
    console.print(f"  [dim]{len(profiles)} integration(s) registered.[/dim]\n")


@integrations_app.command("check")
def integrations_check() -> None:
    """Run install_check() on all integrations and report which are active."""
    from .integrations.registry import REGISTRY

    console.print(f"\n  [bold {_COBALT}]Integrations check[/bold {_COBALT}]\n")

    active = []
    inactive = []
    for name, integration in REGISTRY.items():
        if integration.install_check():
            active.append(name)
        else:
            inactive.append(name)

    for name in sorted(active):
        console.print(f"  {_dot(True)}  {name}")
    for name in sorted(inactive):
        console.print(f"  {_dot(False, warn=True)}  [dim]{name}[/dim]")

    console.print()
    console.print(f"  [dim]{len(active)} active  {len(inactive)} not installed[/dim]\n")


# ── UI command ────────────────────────────────────────────────────────────────

@app.command("ui")
def ui_shell(
    port: int = typer.Option(5173, "--port", help="Vite dev server port"),
    api_port: int = typer.Option(8000, "--api-port", help="API server port"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Skip opening browser"),
) -> None:
    """Start the API server and React dashboard. Opens http://localhost:5173."""
    import shutil
    import subprocess
    import time as _time
    import webbrowser

    if not shutil.which("npm"):
        err.print(f"\n[{_RED}]npm not found.[/{_RED}]  Install Node.js from https://nodejs.org\n")
        raise typer.Exit(1)

    ui_dir = Path("ui")
    if not ui_dir.exists():
        err.print(f"\n[{_RED}]ui/ directory not found.[/{_RED}]  Run from the project root.\n")
        raise typer.Exit(1)

    need_install = (
        not (ui_dir / "node_modules").exists()
        or not (ui_dir / "node_modules" / "lucide-react").exists()
    )
    if need_install:
        console.print("\n  [dim]Installing UI dependencies...[/dim]")
        r = subprocess.run(["npm", "install"], cwd=ui_dir, check=False)
        if r.returncode != 0:
            err.print(f"\n[{_RED}]npm install failed.[/{_RED}]\n")
            raise typer.Exit(1)

    console.print(
        f"\n  [bold {_COBALT}]OpenCobalt UI[/bold {_COBALT}]"
        f"  [dim]starting...[/dim]\n"
    )

    procs: list[subprocess.Popen] = []
    try:
        api_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "opencobalt.api_server:app",
             "--port", str(api_port), "--log-level", "warning"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(api_proc)

        vite_proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(port)],
            cwd=ui_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(vite_proc)

        console.print(f"  [dim]API server :[/dim]  http://localhost:{api_port}")
        console.print(f"  [{_GREEN}]Dashboard running at[/{_GREEN}]  http://localhost:{port}")
        console.print("  [dim]Ctrl+C to stop.[/dim]\n")

        # Wait for servers to start, then verify API is up before opening browser
        _time.sleep(3)
        import urllib.error
        import urllib.request
        try:
            urllib.request.urlopen(f"http://localhost:{api_port}/api/status", timeout=3)
        except urllib.error.URLError:
            # API failed -- could be missing server extras
            if api_proc.poll() is not None:
                err.print(
                    f"\n[{_RED}]API server failed to start.[/{_RED}]  "
                    f"Run: pip install -e '.[server]'\n"
                )
                vite_proc.terminate()
                raise typer.Exit(1)

        if not no_browser:
            webbrowser.open(f"http://localhost:{port}")

        for p in procs:
            p.wait()

    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        console.print("\n  [dim]Stopped.[/dim]\n")


# ── Desktop command ───────────────────────────────────────────────────────────

def _check_cargo_tauri() -> bool:
    """Return True when the Rust Tauri CLI is available as `cargo tauri`."""
    import subprocess

    result = subprocess.run(
        ["cargo", "tauri", "--version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


@app.command("desktop")
def desktop_shell(
    api_port: int = typer.Option(8000, "--api-port", help="FastAPI server port"),
) -> None:
    """Start FastAPI in-process and launch the Tauri desktop app."""
    import shutil
    import subprocess
    import threading
    import time as _time
    import urllib.error
    import urllib.request

    ui_dir = Path("ui")
    if not ui_dir.exists():
        err.print(f"\n[{_RED}]ui/ directory not found.[/{_RED}]  Run from the project root.\n")
        raise typer.Exit(1)

    if not (ui_dir / "src-tauri").exists():
        err.print(f"\n[{_RED}]ui/src-tauri/ not found.[/{_RED}]  Tauri project is missing.\n")
        raise typer.Exit(1)

    if not shutil.which("npm"):
        err.print(f"\n[{_RED}]npm not found.[/{_RED}]  Install Node.js from https://nodejs.org\n")
        raise typer.Exit(1)

    if not shutil.which("cargo"):
        err.print(f"\n[{_RED}]cargo not found.[/{_RED}]  Install Rust from https://rustup.rs\n")
        raise typer.Exit(1)

    if not _check_cargo_tauri():
        err.print(
            f"\n[{_RED}]cargo tauri not found.[/{_RED}]  "
            "Install Tauri CLI with: cargo install tauri-cli --version '^2'\n"
        )
        raise typer.Exit(1)

    try:
        import uvicorn
    except ImportError:
        err.print(f"\n[{_RED}]uvicorn not found.[/{_RED}]  Run: pip install -e '.[server]'\n")
        raise typer.Exit(1) from None

    config = uvicorn.Config(
        "opencobalt.api_server:app",
        host="127.0.0.1",
        port=api_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)

    console.print(
        f"\n  [bold {_COBALT}]OpenCobalt Desktop[/bold {_COBALT}]"
        f"  [dim]starting...[/dim]\n"
    )
    thread.start()
    _time.sleep(1)

    try:
        urllib.request.urlopen(f"http://127.0.0.1:{api_port}/api/status", timeout=3)
    except urllib.error.URLError:
        server.should_exit = True
        thread.join(timeout=5)
        err.print(
            f"\n[{_RED}]FastAPI server failed to start.[/{_RED}]  "
            f"Port {api_port} may already be in use.\n"
        )
        raise typer.Exit(1) from None

    tauri_proc: subprocess.Popen | None = None
    return_code = 0
    try:
        console.print(f"  [dim]FastAPI server:[/dim]  http://127.0.0.1:{api_port}")
        console.print("  [dim]Launching Tauri desktop app...[/dim]\n")
        tauri_proc = subprocess.Popen(["cargo", "tauri", "dev"], cwd=ui_dir)
        return_code = tauri_proc.wait()
    except KeyboardInterrupt:
        return_code = 0
    finally:
        if tauri_proc and tauri_proc.poll() is None:
            tauri_proc.terminate()
            try:
                tauri_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tauri_proc.kill()
        server.should_exit = True
        thread.join(timeout=5)
        console.print("\n  [dim]Stopped desktop services.[/dim]\n")

    if return_code != 0:
        raise typer.Exit(return_code)


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


@benchmark_app.callback(invoke_without_command=True)
def benchmark(ctx: typer.Context) -> None:
    """Route a set of representative tasks and show the full scoring breakdown.

    Run with no subcommand to get the router breakdown. Use subcommands
    (status, record) to interact with the persistent benchmark store.
    """
    if ctx.invoked_subcommand is not None:
        return

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


@benchmark_app.command("status")
def benchmark_status() -> None:
    """Show the agent leaderboard from the benchmark store."""
    from .core.benchmark import BenchmarkStore

    store = BenchmarkStore(_DB_PATH)
    leaderboard = store.get_leaderboard(n=10)

    console.print(f"\n  [bold {_COBALT}]Benchmark Leaderboard[/bold {_COBALT}]\n")

    if not leaderboard:
        console.print("  [dim]No benchmark records yet.[/dim]")
        console.print("  [dim]Run: opencobalt benchmark record \"task\" --agent NAME[/dim]\n")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Rank", style="dim", justify="right")
    table.add_column("Agent", style=f"{_COBALT}")
    table.add_column("Runs", justify="right", style="dim")
    table.add_column("Win rate", justify="right")
    table.add_column("Avg latency", justify="right", style="dim")
    table.add_column("Score", justify="right")

    for i, entry in enumerate(leaderboard, start=1):
        win_pct = f"{entry['win_rate'] * 100:.1f}%"
        latency = f"{entry['avg_latency_ms']:.0f} ms"
        score = f"{entry['composite_score']:.4f}"
        table.add_row(str(i), entry["agent_id"], str(entry["total"]), win_pct, latency, score)

    console.print(table)
    console.print(f"  [dim]{len(leaderboard)} agent(s) on board.[/dim]\n")


@benchmark_app.command("record")
def benchmark_record(
    task: str = typer.Argument(..., help="Task description"),
    agent: str = typer.Option(..., "--agent", "-a", help="Agent name"),
    latency: int = typer.Option(..., "--latency", "-l", help="Latency in ms"),
    success: bool = typer.Option(..., "--success/--fail", help="Whether the task succeeded"),
    task_type: str = typer.Option("general", "--task-type", "-t", help="Task type category"),
    model_used: str = typer.Option("unknown", "--model", "-m", help="Model used"),
    tier: str = typer.Option("worker", "--tier", help="Agent tier"),
    score: float = typer.Option(0.0, "--score", "-s", help="Quality score 0.0-1.0"),
) -> None:
    """Record a benchmark result manually."""
    import uuid

    from .core.benchmark import BenchmarkRecord, BenchmarkStore

    record = BenchmarkRecord(
        agent_id=agent,
        task_id=str(uuid.uuid4()),
        task_type=task_type,
        latency_ms=latency,
        success=success,
        model_used=model_used,
        tier=tier,
        score=score,
    )
    store = BenchmarkStore(_DB_PATH)
    store.record(record)

    # Mirror to observability store for cross-system tracking
    try:
        from .observability import ObservabilitySession

        obs = ObservabilitySession(db_path=_OBS_DB)
        sid = obs.start_session(agent_id=agent, task=task, model=model_used)
        obs.end_session(sid, success=success)
    except Exception:
        pass

    status_str = f"[{_GREEN}]success[/{_GREEN}]" if success else f"[{_RED}]fail[/{_RED}]"
    console.print(f"\n  [{_GREEN}]Recorded[/{_GREEN}]  [dim]{record.id}[/dim]")
    console.print(f"  [dim]agent   :[/dim]  {agent}")
    console.print(f"  [dim]task    :[/dim]  {task[:60]}")
    console.print(f"  [dim]latency :[/dim]  {latency} ms")
    console.print(f"  [dim]result  :[/dim]  {status_str}\n")


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

khoj_app = typer.Typer(help="Khoj sidecar commands.")
app.add_typer(khoj_app, name="khoj")


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


# ── Khoj commands ─────────────────────────────────────────────────────────────

@khoj_app.command("status")
def khoj_status() -> None:
    """Check if the Khoj sidecar is reachable on localhost:42110."""
    import urllib.error
    import urllib.request

    _KHOJ_URL = "http://localhost:42110"
    console.print()
    try:
        with urllib.request.urlopen(f"{_KHOJ_URL}/api/health", timeout=3) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            version = "unknown"
            if '"version"' in body:
                import json as _json

                data = _json.loads(body)
                version = data.get("version", "unknown")
            console.print(
                f"  {_dot(True)}  [dim]khoj[/dim]  "
                f"[{_GREEN}]up[/{_GREEN}]  [dim]version {version} · {_KHOJ_URL}[/dim]"
            )
    except urllib.error.URLError:
        console.print(
            f"  {_dot(False, warn=True)}  [dim]khoj[/dim]  "
            f"[{_YELLOW}]down[/{_YELLOW}]  [dim]not reachable at {_KHOJ_URL}[/dim]"
        )
        console.print("  [dim]Start with:[/dim]  cd ~/.khoj && docker-compose up -d")
    console.print()


# ── Brief command ──────────────────────────────────────────────────────────────

@app.command()
def brief(
    days: int = typer.Option(7, "--days", "-d", help="How far back to look (days)"),
    copy: bool = typer.Option(False, "--copy", "-c", help="Copy output to clipboard (pbcopy/xclip)"),
    fmt: str = typer.Option("markdown", "--format", "-f", help="Output format: markdown or plain"),
) -> None:
    """Generate a temporal context brief from session history. Paste into any AI tool."""
    from .core.brief import BriefGenerator

    gen = BriefGenerator(_ledger(), bridge_path=_MEMORIES_DB)
    output = gen.generate(days=days)

    if fmt == "plain":
        import re as _re
        output = _re.sub(r"#+ ", "", output)
        output = _re.sub(r"\*\*(.+?)\*\*", r"\1", output)
        output = _re.sub(r"_(.+?)_", r"\1", output)

    if copy:
        import platform
        import subprocess as _sp
        try:
            if platform.system() == "Darwin":
                _sp.run(["pbcopy"], input=output.encode(), check=True)
            else:
                _sp.run(["xclip", "-selection", "clipboard"], input=output.encode(), check=True)
            console.print(f"  [{_GREEN}]Copied to clipboard.[/{_GREEN}]  {len(output.split())} words\n")
        except (FileNotFoundError, Exception) as exc:
            err.print(f"  [{_YELLOW}]Clipboard copy failed:[/{_YELLOW}]  {exc}\n")
    else:
        console.print(output)


# ── Install-hooks command ──────────────────────────────────────────────────────

@app.command("install-hooks")
def install_hooks(
    uninstall: bool = typer.Option(False, "--uninstall", help="Remove OpenCobalt hooks"),
    status_only: bool = typer.Option(False, "--status", help="Show which hooks are installed"),
) -> None:
    """Install (or remove) git hooks that auto-log commits and verify before push."""
    import subprocess as _sp

    from .core.hooks import HookManager

    # Find .git/hooks directory
    try:
        result_git = _sp.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=True,
        )
        git_dir = Path(result_git.stdout.strip())
        hooks_dir = git_dir / "hooks"
    except Exception:
        err.print(f"\n  [{_RED}]Not in a git repository.[/{_RED}]\n")
        raise typer.Exit(1)

    mgr = HookManager()

    if status_only:
        statuses = mgr.status(hooks_dir)
        console.print(f"\n  [bold {_COBALT}]Hook status[/bold {_COBALT}]  [dim]{hooks_dir}[/dim]\n")
        for name, installed in statuses.items():
            dot = _dot(installed)
            label = f"[{_GREEN}]installed[/{_GREEN}]" if installed else "[dim]not installed[/dim]"
            console.print(f"  {dot}  {name:<14}  {label}")
        console.print()
        return

    if uninstall:
        results = mgr.uninstall(hooks_dir)
        console.print(f"\n  [bold {_COBALT}]Uninstall hooks[/bold {_COBALT}]\n")
        for name, outcome in results.items():
            icon = f"[{_GREEN}]removed[/{_GREEN}]" if outcome == "removed" else f"[dim]{outcome}[/dim]"
            console.print(f"  {name:<14}  {icon}")
        console.print()
        return

    results = mgr.install(hooks_dir)
    console.print(f"\n  [bold {_COBALT}]Install hooks[/bold {_COBALT}]  [dim]{hooks_dir}[/dim]\n")
    for name, outcome in results.items():
        color = _GREEN if outcome == "installed" else _YELLOW
        icon = f"[{color}]{outcome}[/{color}]"
        console.print(f"  {name:<14}  {icon}")
    console.print()


# ── Council command ────────────────────────────────────────────────────────────

@app.command()
def council(
    task: str = typer.Argument(..., help="Task or question to consult on"),
    models_str: str = typer.Option("", "--models", "-m", help="Comma-separated models (claude,gemini,ollama)"),
    no_synthesis: bool = typer.Option(False, "--no-synthesis", help="Show raw responses only"),
    save: bool = typer.Option(False, "--save", help="Save result to memory bridge"),
) -> None:
    """Consult multiple AI models in parallel. Synthesises agreements and flags disagreements."""
    from .core.council import CouncilSession

    models = [m.strip() for m in models_str.split(",") if m.strip()] or None

    console.print(f"\n  [bold {_COBALT}]COUNCIL[/bold {_COBALT}]  [dim]{task[:60]}[/dim]\n")

    with console.status("[dim]Consulting models...[/dim]", spinner="dots"):
        session = CouncilSession()
        result = session.consult(task, models=models, synthesize=not no_synthesis)

    model_list = ", ".join(result.responses.keys()) or "none"
    agreement_pct = f"{result.agreement_score * 100:.0f}%"

    from rich.panel import Panel
    console.print(Panel(
        f"  Task: {task[:60]}\n  Models: {model_list}\n  Agreement: {agreement_pct}",
        title="[dim]Council Result[/dim]",
        border_style="dim",
    ))

    for model_name, response in result.responses.items():
        color = _tier_color("executive") if model_name != "ollama" else "dim"
        console.print(f"\n  [{color}][{model_name.upper()}][/{color}]")
        for line in response.splitlines()[:8]:
            console.print(f"  [dim]{line}[/dim]")

    if result.agreements:
        console.print(f"\n  [{_GREEN}]AGREED[/{_GREEN}]")
        for a in result.agreements:
            console.print(f"  [dim]+[/dim]  {a}")

    if result.disagreements:
        console.print(f"\n  [{_YELLOW}]VARIED[/{_YELLOW}]")
        for d in result.disagreements:
            console.print(f"  [dim]~[/dim]  {d}")

    if result.synthesis:
        console.print("\n  [bold]SYNTHESIS[/bold]")
        for line in result.synthesis.splitlines():
            console.print(f"  {line}")

    if result.recommended_action:
        console.print(f"\n  [bold {_COBALT}]RECOMMENDATION[/bold {_COBALT}]  {result.recommended_action}")

    if save and result.synthesis:
        try:
            bridge = _memory_bridge()
            bridge.add(
                content=f"Council on '{task[:60]}': {result.synthesis[:300]}",
                agent_id="council",
                metadata={"type": "council", "agreement": result.agreement_score},
            )
            console.print(f"  [{_GREEN}]Saved to memory bridge.[/{_GREEN}]")
        except Exception:
            pass

    console.print()


# ── Debate command ─────────────────────────────────────────────────────────────

@app.command()
def debate(
    question: str = typer.Argument(..., help="Question or position to debate"),
    for_model: str = typer.Option("", "--for-model", help="Model to argue FOR"),
    against_model: str = typer.Option("", "--against-model", help="Model to argue AGAINST"),
    judge: str = typer.Option("", "--judge", help="Adjudicator model"),
    save: bool = typer.Option(False, "--save", help="Save debate result to memory bridge"),
) -> None:
    """Two models argue for/against a position. A third adjudicates."""
    from .core.debate import DebateSession

    console.print(f"\n  [bold {_COBALT}]DEBATE[/bold {_COBALT}]  [dim]{question[:60]}[/dim]\n")

    with console.status("[dim]Running debate...[/dim]", spinner="dots"):
        session = DebateSession()
        result = session.run(
            question=question,
            for_model=for_model or None,
            against_model=against_model or None,
            judge_model=judge or None,
        )

    from rich.panel import Panel
    console.print(Panel(
        f"  FOR ({result.for_model}) vs AGAINST ({result.against_model})\n"
        f"  Judge: {result.judge_model}",
        title=f"[dim]Debate: {question[:50]}[/dim]",
        border_style="dim",
    ))

    console.print(f"\n  [{_GREEN}]FOR ({result.for_model})[/{_GREEN}]")
    for line in result.for_argument.splitlines()[:6]:
        console.print(f"  [dim]{line}[/dim]")

    console.print(f"\n  [{_RED}]AGAINST ({result.against_model})[/{_RED}]")
    for line in result.against_argument.splitlines()[:6]:
        console.print(f"  [dim]{line}[/dim]")

    console.print(f"\n  [bold]JUDGMENT ({result.judge_model})[/bold]")
    for line in result.judgment.splitlines()[:8]:
        console.print(f"  [dim]{line}[/dim]")

    winner_color = _GREEN if result.winner == "FOR" else _RED
    console.print(f"\n  [{winner_color}]WINNER: {result.winner}[/{winner_color}]")

    if result.recommendation:
        console.print(f"\n  [bold {_COBALT}]RECOMMENDATION[/bold {_COBALT}]  {result.recommendation[:120]}")

    if save and result.judgment:
        try:
            bridge = _memory_bridge()
            bridge.add(
                content=f"Debate on '{question[:60]}': Winner={result.winner}. {result.recommendation[:200]}",
                agent_id="debate",
                metadata={"type": "debate", "winner": result.winner},
            )
            console.print(f"  [{_GREEN}]Saved to memory bridge.[/{_GREEN}]")
        except Exception:
            pass

    console.print()


# ── Skills evolve command (stub) ────────────────────────────────────────────────

@skills_app.command("evolve")
def skills_evolve(
    skill_name: str = typer.Argument(..., help="Skill name to evolve"),
    task: str = typer.Option("", "--task", "-t", help="Test task to evaluate against"),
    auto_promote: bool = typer.Option(False, "--auto-promote", help="Promote without asking"),
) -> None:
    """Evaluate a skill against a task and promote if it improves. (Stub -- deferred.)"""
    from .core.skill_evolver import SkillEvolver

    evolver = SkillEvolver()
    result = evolver.evolve(skill_name=skill_name, test_task=task, auto_promote=auto_promote)

    console.print(f"\n  [bold {_COBALT}]Skill Evolution[/bold {_COBALT}]  {skill_name}\n")
    console.print(f"  [{_YELLOW}]{result.notes}[/{_YELLOW}]")
    console.print(f"  [dim]Current version: {result.version}[/dim]\n")


# ── Route exec helper ──────────────────────────────────────────────────────────

_TOOL_LAUNCH: dict[str, list[str]] = {
    "claude-code": ["claude"],
    "codex-cli": ["codex"],
    "gemini-cli": ["gemini"],
    "cursor": ["cursor", "."],
    "ollama": [],  # print-only, never auto-exec
}

_TOOL_INSTALL: dict[str, str] = {
    "claude-code": "npm install -g @anthropic-ai/claude-code",
    "codex-cli": "npm install -g @openai/codex",
    "gemini-cli": "npm install -g @google/gemini-cli",
    "cursor": "Download from https://cursor.sh",
    "ollama": "Download from https://ollama.ai",
}


def _route_exec(tool: str, task: str, dry_run: bool = False) -> None:
    import shutil
    import subprocess as _sp

    cmd = _TOOL_LAUNCH.get(tool, [])
    binary = cmd[0] if cmd else None

    # Copy brief to clipboard
    _clipboard_brief(dry_run, tool=tool)

    if tool == "ollama":
        console.print("\n  [dim]Ollama (worker-tier) -- run manually:[/dim]")
        console.print(f"  ollama run llama3 \"{task[:60]}\"")
        return

    if dry_run:
        if binary and shutil.which(binary):
            console.print(f"\n  [dim]--dry-run: would run[/dim]  {' '.join(cmd)}")
        elif binary:
            console.print(f"\n  [dim]--dry-run: {binary} not found -- would print install instructions[/dim]")
        return

    if not binary or not shutil.which(binary):
        install = _TOOL_INSTALL.get(tool, "Check tool documentation")
        console.print(f"\n  [{_YELLOW}]{tool} not found.[/{_YELLOW}]  Install: {install}")
        return

    console.print(f"\n  [{_GREEN}]Opening {tool}...[/{_GREEN}]")
    _sp.Popen(cmd)  # noqa: S603


def _clipboard_brief(dry_run: bool = False, tool: str = "the tool") -> None:
    import platform
    import subprocess as _sp

    from .core.brief import BriefGenerator
    try:
        gen = BriefGenerator(_ledger(), bridge_path=_MEMORIES_DB)
        output = gen.generate(days=7)
        if dry_run:
            console.print(f"  [dim]--dry-run: would copy brief ({len(output.split())} words) to clipboard[/dim]")
            return
        if platform.system() == "Darwin":
            _sp.run(["pbcopy"], input=output.encode(), check=True)
            console.print(f"  [{_GREEN}]Context copied to clipboard.[/{_GREEN}]  Paste it into {tool} when it opens.")
        else:
            _sp.run(["xclip", "-selection", "clipboard"], input=output.encode(), check=False)
    except Exception:
        pass
