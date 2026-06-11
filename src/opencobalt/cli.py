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
  opencobalt run TASK [--runtime R] [--execute] [--yes]
  opencobalt receipts list|inspect|verify
  opencobalt artifacts attach|verify|list
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

telemetry_app = typer.Typer(help="Telemetry commands.", invoke_without_command=True)
app.add_typer(telemetry_app, name="telemetry")

converge_app = typer.Typer(help="Convergence protocol commands.", invoke_without_command=True)
app.add_typer(converge_app, name="converge")

policy_app = typer.Typer(help="Autonomy policy commands.")
app.add_typer(policy_app, name="policy")

limits_app = typer.Typer(help="Usage limit observation commands.")
app.add_typer(limits_app, name="limits")

receipts_app = typer.Typer(help="Work receipt commands (receipt-backed execution).")
app.add_typer(receipts_app, name="receipts")

artifacts_app = typer.Typer(help="Execution artifact commands (hash, attach, verify).")
app.add_typer(artifacts_app, name="artifacts")

plans_app = typer.Typer(help="Stored execution plan commands (list, inspect, execute).")
app.add_typer(plans_app, name="plans")

opportunities_app = typer.Typer(
    help="Autonomous opportunity engine (brainstorm, score, report, plan)."
)
app.add_typer(opportunities_app, name="opportunities")

console = Console()
err = Console(stderr=True)

_DB_PATH = Path(".opencobalt") / "ledger.db"
_TELEMETRY_DB_PATH = Path(".opencobalt") / "telemetry.db"
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


def _split_cli_actions(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


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
) -> None:
    """Dispatch a task to multiple specialized agents in parallel with live status."""
    from .core.orchestrator import OrchestrationSession, ResultSynthesizer  # noqa: PLC0415

    session = OrchestrationSession()
    result = session.run(task, show_live=True)

    synthesizer = ResultSynthesizer()
    synthesizer.print_rich(result.task, result.subtasks, result.outputs)

    agent_word = "agent" if len(result.subtasks) == 1 else "agents"
    console.print(
        f"  [dim]completed in {result.elapsed_s:.1f}s"
        f" · {len(result.subtasks)} {agent_word}"
        f" · {'success' if result.success else 'partial'}[/dim]\n"
    )


@app.command()
def auto(
    task: str = typer.Argument(..., help="Seed task for autonomous multi-hour execution"),
    iterations: int = typer.Option(20, "--iterations", "-n", help="Max iterations"),
    hours: float = typer.Option(5.0, "--hours", "-t", help="Max runtime in hours"),
    use_limits: str = typer.Option(
        "balanced",
        "--use-limits",
        help="Autonomy profile: balanced, aggressive, max, cheap, or executive",
    ),
    converge: bool = typer.Option(
        False, "--converge", help="Use convergence protocol (DAG + gating) instead of autonomous runner"
    ),
) -> None:
    """Run an autonomous multi-agent session for hours."""
    if converge:
        from .core.convergence_orchestrator import ConvergenceOrchestrator
        orch = ConvergenceOrchestrator(ledger=_ledger())
        orch.run(task)
        return
    from .core.autonomy_engine import AutonomyEngine

    engine = AutonomyEngine(ledger=_ledger(), max_iterations=iterations)
    run = engine.start(task, profile=use_limits, hours=hours)
    tasks = _ledger().list_autonomy_tasks(run["id"])
    console.print(f"\n  [bold {_COBALT}]Autonomy run[/bold {_COBALT}]  [dim]{run['id'][:8]}[/dim]")
    console.print(f"  [dim]profile:[/dim] {run['profile']}  [dim]hours:[/dim] {hours:g}")
    console.print(f"  [dim]tasks:[/dim]   {len(tasks)} checkpointed")
    console.print("  [dim]external tools are not called until task execution is explicitly run[/dim]\n")


@app.command("overlay")
def overlay(
    prompt: str = typer.Argument(..., help="Plain prompt to classify and dispatch"),
) -> None:
    """Classify a prompt through the Phase 14 overlay."""
    from .core.overlay import OverlayController

    controller = OverlayController(ledger=_ledger())
    classification = controller.classify(prompt)
    console.print(f"\n  [bold {_COBALT}]Overlay[/bold {_COBALT}]  [dim]{classification.mode}[/dim]")
    console.print(f"  [dim]prompt:[/dim]  {classification.prompt}")
    console.print(f"  [dim]profile:[/dim] {classification.profile}")
    if classification.hours is not None:
        console.print(f"  [dim]hours:[/dim]   {classification.hours:g}")
    console.print()


@app.command("mission")
def mission(
    task: str = typer.Argument(..., help="Open-ended mission goal"),
    hours: float = typer.Option(5.0, "--hours", help="Max runtime in hours"),
    profile: str = typer.Option("balanced", "--profile", help="Autonomy profile"),
    allow: str = typer.Option("", "--allow", help="Comma-separated allowed action envelope"),
    deny: str = typer.Option("", "--deny", help="Comma-separated denied actions"),
) -> None:
    """Create a checkpointed mission plan without external actions."""
    from .core.artifact_bus import ArtifactBus
    from .core.autonomy_policy import PermissionEnvelope
    from .core.mission import MissionPlanner

    envelope = PermissionEnvelope(
        allowed_actions=_split_cli_actions(allow),
        denied_actions=_split_cli_actions(deny),
    )
    planner = MissionPlanner(ledger=_ledger(), artifact_bus=ArtifactBus())
    result = planner.plan(seed_goal=task, profile=profile, envelope=envelope)
    console.print(f"\n  [bold {_COBALT}]Mission[/bold {_COBALT}]  [dim]{result['run_id'][:8]}[/dim]")
    console.print(f"  [dim]goal:[/dim]    {task}")
    console.print(f"  [dim]profile:[/dim] {profile}  [dim]hours:[/dim] {hours:g}")
    console.print(f"  [dim]plan:[/dim]    {result['selected_plan']['title']}")
    console.print("  [dim]permission envelope recorded; no external action was taken[/dim]\n")


@converge_app.callback(invoke_without_command=True)
def converge_cmd(
    ctx: typer.Context,
    task: str = typer.Option("", "--task", "-t", help="Task to converge on"),
    resume: str = typer.Option("", "--resume", help="Resume interrupted session by ID"),
    push_on_converge: bool = typer.Option(
        False, "--push-on-converge", help="Push to remote after successful convergence"
    ),
) -> None:
    """Run convergence protocol: decompose task, execute DAG waves, verify, commit."""
    if ctx.invoked_subcommand is not None:
        return
    if not task and not resume:
        console.print("  [dim]Usage: opencobalt converge --task \"task\" | --resume SESSION_ID[/dim]")
        return
    from .core.auto_committer import AutoCommitter
    from .core.convergence_orchestrator import ConvergenceOrchestrator

    actual_task = task
    resume_id: str | None = None
    if resume:
        resume_id = resume
        if not actual_task:
            row = _ledger().get_convergence_session(resume)
            actual_task = row["seed_task"] if row else ""
        if not actual_task:
            err.print(f"  Session not found: {resume}")
            raise typer.Exit(1)

    orch = ConvergenceOrchestrator(
        committer=AutoCommitter(push_on_converge=push_on_converge),
        ledger=_ledger(),
    )
    orch.run(actual_task, resume_session_id=resume_id)


@converge_app.command("history")
def converge_history(
    limit: int = typer.Option(10, "--limit", "-n", help="Max sessions to show"),
) -> None:
    """List recent convergence sessions."""
    sessions = _ledger().list_convergence_sessions(limit=limit)
    if not sessions:
        console.print("\n  [dim]No convergence sessions found.[/dim]\n")
        return

    console.print()
    table = Table(title="Convergence Sessions", box=box.SIMPLE, padding=(0, 2))
    table.add_column("ID", style=_COBALT, width=10, no_wrap=True)
    table.add_column("Task", width=40)
    table.add_column("Status", width=12)
    table.add_column("Waves", justify="right", width=6)
    table.add_column("Retries", justify="right", width=8)
    for s in sessions:
        table.add_row(
            s["id"][:8],
            s["seed_task"][:40],
            s["status"],
            str(s["total_waves"]),
            str(s["total_retries"]),
        )
    console.print(table)
    console.print(f"  [dim]{len(sessions)} session(s)[/dim]\n")


@converge_app.command("show")
def converge_show(
    session_id: str = typer.Argument(..., help="Session ID (or prefix) to inspect"),
) -> None:
    """Show wave results and artifact summary for a convergence session."""
    ledger = _ledger()
    session = ledger.get_convergence_session(session_id)
    if not session:
        sessions = ledger.list_convergence_sessions(limit=100)
        matches = [s for s in sessions if s["id"].startswith(session_id)]
        if not matches:
            err.print(f"\n  Session not found: {session_id}\n")
            raise typer.Exit(1)
        session = matches[0]

    console.print(f"\n  [bold {_COBALT}]Session {session['id'][:8]}[/bold {_COBALT}]")
    console.print(f"  [dim]task:[/dim]    {session['seed_task']}")
    console.print(f"  [dim]status:[/dim]  {session['status']}")
    console.print(f"  [dim]waves:[/dim]   {session['total_waves']}  "
                  f"[dim]retries:[/dim] {session['total_retries']}")
    if session.get("commit_sha"):
        console.print(f"  [dim]commit:[/dim]  {session['commit_sha']}")

    wave_results = ledger.get_wave_results(session["id"])
    if wave_results:
        console.print(f"\n  [dim]Wave results ({len(wave_results)}):[/dim]")
        for wr in wave_results:
            ok = f"[{_GREEN}]v[/{_GREEN}]" if wr["passed"] else f"[{_RED}]x[/{_RED}]"
            console.print(
                f"    wave {wr['wave']} retry {wr['retry_count']}  {ok}  "
                f"[dim]{str(wr['feedback'])[:60]}[/dim]"
            )
    console.print()


@converge_app.command("run")
def converge_run(
    task: str = typer.Argument(..., help="Task to converge on"),
    push_on_converge: bool = typer.Option(
        False, "--push-on-converge", help="Push to remote after successful convergence"
    ),
) -> None:
    """Run convergence protocol on a task."""
    from .core.auto_committer import AutoCommitter
    from .core.convergence_orchestrator import ConvergenceOrchestrator

    orch_session = ConvergenceOrchestrator(
        committer=AutoCommitter(push_on_converge=push_on_converge),
        ledger=_ledger(),
    )
    orch_session.run(task)


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
def doctor(
    integration: str | None = typer.Argument(None, help="Optional integration diagnostic target"),
) -> None:
    """Run a full system health check, or inspect one integration."""
    if integration in {"antigravity", "google-antigravity", "agy"}:
        _doctor_antigravity()
        return
    if integration is not None:
        console.print(f"\n  [{_YELLOW}]Unknown doctor target:[/{_YELLOW}] {integration}\n")
        raise typer.Exit(1)

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


def _doctor_antigravity() -> None:
    from .integrations.antigravity_integration import discover_antigravity_runtime

    result = discover_antigravity_runtime(ledger=_ledger())
    console.print(f"\n  [bold {_COBALT}]Google Antigravity CLI[/bold {_COBALT}]  [dim]agy[/dim]\n")
    console.print(
        f"  {_dot(result['installed'])}  [dim]on PATH       [/dim]  "
        f"{result['path'] if result['path'] else f'[{_YELLOW}]agy not on PATH[/{_YELLOW}]'}"
    )
    version = result["version"]
    version_text = version["value"] if version["ok"] else f"[{_YELLOW}]{version['error']}[/{_YELLOW}]"
    console.print(
        f"  {_dot(version['ok'])}  [dim]agy --version [/dim]  "
        f"{version_text}"
    )
    help_result = result["help"]
    help_text = "available" if help_result["ok"] else f"[{_YELLOW}]{help_result['error']}[/{_YELLOW}]"
    console.print(
        f"  {_dot(help_result['ok'])}  [dim]agy --help    [/dim]  "
        f"{help_text}"
    )
    console.print("\n  [bold]Capabilities[/bold]")
    for name, capability in result["capabilities"].items():
        supported = capability["supported"]
        source = capability["source"]
        evidence = capability.get("evidence") or ""
        if supported is True:
            state = f"[{_GREEN}]yes[/{_GREEN}]"
        elif supported is False:
            state = f"[{_RED}]no[/{_RED}]"
        else:
            state = f"[{_YELLOW}]unknown[/{_YELLOW}]"
        console.print(f"  {name:<24} {state:<18} [dim]{source} {evidence}[/dim]")
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


# ── Phase 14 policy and limits commands ───────────────────────────────────────

@policy_app.command("show")
def policy_show() -> None:
    """Show the current autonomy policy defaults."""
    from .core.autonomy_policy import PolicyStore

    policy = PolicyStore(_DB_PATH).get_policy()
    console.print()
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value")
    for key in (
        "profile",
        "use_limits",
        "auto_test",
        "auto_retry",
        "auto_commit",
        "auto_push",
        "api_usage",
        "push_requires_explicit",
    ):
        table.add_row(key, str(getattr(policy, key)).lower())
    console.print(table)
    console.print()


@policy_app.command("set")
def policy_set(
    key: str = typer.Argument(..., help="Policy key to set"),
    value: str = typer.Argument(..., help="Policy value"),
) -> None:
    """Set an autonomy policy value in SQLite config."""
    from .core.autonomy_policy import PolicyStore

    PolicyStore(_DB_PATH).set(key, value)
    console.print(f"\n  [{_GREEN}]Policy updated[/{_GREEN}]  [dim]{key}={value}[/dim]\n")


@limits_app.command("status")
def limits_status() -> None:
    """Show observed usage limit signals."""
    observations = _ledger().list_usage_observations(limit=20)
    console.print(f"\n  [bold {_COBALT}]Usage observations[/bold {_COBALT}]\n")
    if not observations:
        console.print("  [dim]No usage observations recorded yet.[/dim]\n")
        return
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Tool")
    table.add_column("Event", style="dim")
    table.add_column("Task", style="dim")
    table.add_column("Success", style="dim")
    table.add_column("Message")
    for item in observations:
        table.add_row(
            item["tool"],
            item["event_type"],
            item["task_type"],
            str(item["success"]).lower(),
            item["message"][:60],
        )
    console.print(table)
    console.print(f"  [dim]{len(observations)} observation(s)[/dim]\n")


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
def benchmark_status(
    telemetry: bool = typer.Option(False, "--telemetry", help="Show category scores from telemetry store"),
) -> None:
    """Show the agent leaderboard from the benchmark store."""
    if telemetry:
        from .core.telemetry import TelemetryStore
        t_store = TelemetryStore(_TELEMETRY_DB_PATH)
        board = t_store.get_leaderboard()
        console.print(f"\n  [bold {_COBALT}]Benchmark (Telemetry)[/bold {_COBALT}]\n")
        if not board:
            console.print("  [dim]No scored runs yet.[/dim]\n")
            return
        table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
        table.add_column("Agent", style=f"{_COBALT}")
        table.add_column("Runs", justify="right", style="dim")
        table.add_column("Overall", justify="right")
        table.add_column("Quality", justify="right", style="dim")
        table.add_column("Adherence", justify="right", style="dim")
        for entry in board:
            table.add_row(
                entry["agent_id"], str(entry["total"]),
                f"{entry['avg_overall']:.0f}",
                f"{entry.get('avg_output_quality') or 0:.0f}",
                f"{entry.get('avg_prompt_adherence') or 0:.0f}",
            )
        console.print(table)
        console.print()
        return
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
    mode: str = typer.Option("advise", "--mode", help="Council mode: advise, coordinate, review, ideate, resolve"),
    models_str: str = typer.Option("", "--models", "-m", help="Comma-separated models (claude,gemini,ollama)"),
    no_synthesis: bool = typer.Option(False, "--no-synthesis", help="Show raw responses only"),
    save: bool = typer.Option(False, "--save", help="Save result to memory bridge"),
) -> None:
    """Consult multiple AI models in parallel. Synthesises agreements and flags disagreements."""
    if mode != "advise":
        from .core.artifact_bus import ArtifactBus, ArtifactType
        from .core.council_protocol import CouncilProtocol

        type_by_mode = {
            "coordinate": ArtifactType.HANDOFF,
            "review": ArtifactType.OBJECTION,
            "ideate": ArtifactType.IDEA,
            "resolve": ArtifactType.DECISION,
        }
        try:
            artifact = CouncilProtocol(ArtifactBus()).publish(
                session_id="council",
                mode=mode,
                artifact_type=type_by_mode.get(mode, ArtifactType.CLAIM),
                content=task,
                producer="council-cli",
            )
        except ValueError as exc:
            err.print(f"\n[{_RED}]Error:[/{_RED}]  {exc}\n")
            raise typer.Exit(1) from exc
        console.print(
            f"\n  [bold {_COBALT}]Council {mode}[/bold {_COBALT}]"
            f"  [dim]artifact {artifact.id[:8]}[/dim]\n"
        )
        console.print(f"  [dim]type:[/dim] {artifact.type}")
        console.print(f"  [dim]text:[/dim] {task}\n")
        return

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


@telemetry_app.callback(invoke_without_command=True)
def telemetry(ctx: typer.Context) -> None:
    """Telemetry capture, scoring, and export."""
    if ctx.invoked_subcommand is None:
        console.print("[dim]Use: opencobalt telemetry <subcommand>[/dim]")
        console.print("[dim]Subcommands: status, show, runs, scores, score, export[/dim]")


@telemetry_app.command("status")
def telemetry_status() -> None:
    """Summary of scored runs and top agent."""
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    runs = store.list_runs(limit=1000)
    scored = [r for r in runs if r["status"] == "scored"]
    last_day = [r for r in runs if r.get("started_at", 0) > (time.time() - 86400)]
    ollama_count = 0
    heuristic_count = 0
    for r in scored:
        s = store.get_score(r["id"])
        if s and s["judge"].startswith("ollama"):
            ollama_count += 1
        elif s:
            heuristic_count += 1

    console.print(f"\n  [bold {_COBALT}]Telemetry Status[/bold {_COBALT}]\n")
    console.print(f"  Total runs:     {len(runs)}")
    console.print(f"  Scored runs:    {len(scored)}")
    console.print(f"  Last 24h:       {len(last_day)}")
    console.print(f"  Ollama-scored:  {ollama_count}")
    console.print(f"  Heuristic-only: {heuristic_count}")

    board = store.get_leaderboard()
    if board:
        top = board[0]
        console.print(f"  Top agent:      {top['agent_id']} (avg {top['avg_overall']:.0f})\n")
    else:
        console.print()


@telemetry_app.command("runs")
def telemetry_runs(
    limit: int = typer.Option(20, "--limit", "-n"),
    agent: str = typer.Option(None, "--agent", "-a"),
    run_type: str = typer.Option(None, "--type", "-t"),
) -> None:
    """List recent telemetry runs with their scores."""
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    runs = store.list_runs(limit=limit, agent_id=agent, run_type=run_type)

    console.print(f"\n  [bold {_COBALT}]Recent Runs[/bold {_COBALT}]\n")
    if not runs:
        console.print("  [dim]No runs recorded yet.[/dim]\n")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("ID", style="dim")
    table.add_column("Type")
    table.add_column("Agent", style=f"{_COBALT}")
    table.add_column("Prompt")
    table.add_column("Score", justify="right")
    table.add_column("Status", style="dim")

    for r in runs:
        score_row = store.get_score(r["id"])
        score_str = str(score_row["overall"]) if score_row else "-"
        prompt_short = r["seed_prompt"][:40] + "..." if len(r["seed_prompt"]) > 40 else r["seed_prompt"]
        table.add_row(r["id"][:8], r["run_type"], r["agent_id"], prompt_short, score_str, r["status"])

    console.print(table)


@telemetry_app.command("show")
def telemetry_show(run_id: str = typer.Argument(...)) -> None:
    """Full breakdown for one run."""
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    run = store.get_run(run_id)
    if run is None:
        console.print(f"[red]Run not found: {run_id}[/red]")
        raise typer.Exit(1)

    score = store.get_score(run_id)
    console.print(f"\n  [bold {_COBALT}]Run: {run['seed_prompt']}[/bold {_COBALT}]\n")
    console.print(f"  ID:      {run['id']}")
    console.print(f"  Type:    {run['run_type']}")
    console.print(f"  Agent:   {run['agent_id']}")
    console.print(f"  Status:  {run['status']}")
    if run.get("summary"):
        console.print(f"\n  {run['summary']}")

    if score:
        console.print(f"\n  [bold]Overall Score: {score['overall']}/100[/bold] ({score['judge']})\n")
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        for cat, label in [
            ("output_quality", "Output Quality"),
            ("prompt_adherence", "Prompt Adherence"),
            ("novel_ideation", "Novel Ideation"),
            ("context_handling", "Context Handling"),
            ("tool_appropriateness", "Tool Appropriateness"),
            ("token_efficiency", "Token Efficiency"),
            ("latency_score", "Latency"),
            ("task_decomposition", "Task Decomposition"),
            ("agent_selection", "Agent Selection"),
            ("convergence_quality", "Convergence Quality"),
        ]:
            val = score.get(cat)
            table.add_row(label, str(val) if val is not None else "-")
        console.print(table)
        if score.get("judge_reasoning"):
            console.print(f"\n  [dim]{score['judge_reasoning']}[/dim]")
    console.print()


@telemetry_app.command("scores")
def telemetry_scores() -> None:
    """Agent leaderboard by category."""
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    board = store.get_leaderboard()

    console.print(f"\n  [bold {_COBALT}]Telemetry Leaderboard[/bold {_COBALT}]\n")
    if not board:
        console.print("  [dim]No scored runs yet.[/dim]\n")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Agent", style=f"{_COBALT}")
    table.add_column("Runs", justify="right", style="dim")
    table.add_column("Overall", justify="right")
    table.add_column("Quality", justify="right", style="dim")
    table.add_column("Adherence", justify="right", style="dim")
    table.add_column("Efficiency", justify="right", style="dim")

    for entry in board:
        table.add_row(
            entry["agent_id"],
            str(entry["total"]),
            f"{entry['avg_overall']:.0f}",
            f"{entry.get('avg_output_quality') or 0:.0f}",
            f"{entry.get('avg_prompt_adherence') or 0:.0f}",
            f"{entry.get('avg_token_efficiency') or 0:.0f}",
        )
    console.print(table)
    console.print()


@telemetry_app.command("score")
def telemetry_score_run(run_id: str = typer.Argument(...)) -> None:
    """Score or rescore a run."""
    from .core.ollama_judge import OllamaJudge
    from .core.scoring_engine import ScoringEngine
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    run = store.get_run(run_id)
    if run is None:
        console.print(f"[red]Run not found: {run_id}[/red]")
        raise typer.Exit(1)

    from .core.config import Config
    model = Config(_DB_PATH).get("ollama_judge_model") or "llama3"
    judge = OllamaJudge(model=model)
    with console.status("[dim]Scoring...[/dim]", spinner="dots"):
        result = ScoringEngine(store, judge=judge).score(run_id)
    console.print(f"  Overall: {result['overall']}/100 ({result['judge']})\n")


@telemetry_app.command("export")
def telemetry_export(
    output: str = typer.Option(None, "--output", "-o", help="Directory to write .md files"),
) -> None:
    """Export scored runs to markdown files."""
    from pathlib import Path as _Path

    from .core.config import Config
    from .core.markdown_exporter import MarkdownExporter
    from .core.telemetry import TelemetryStore

    store = TelemetryStore(_TELEMETRY_DB_PATH)
    export_dir = _Path(output) if output else None
    if export_dir is None:
        cfg = Config(_DB_PATH)
        export_dir_str = cfg.get("telemetry_export_path")
        if not export_dir_str:
            console.print("[red]No export path configured.[/red]")
            console.print("[dim]Set one with: opencobalt config set telemetry_export_path <dir>[/dim]")
            raise typer.Exit(1)
        export_dir = _Path(export_dir_str)

    runs = store.list_runs(limit=10000)
    exporter = MarkdownExporter()
    count = 0
    for r in runs:
        score = store.get_score(r["id"])
        if score is None:
            continue
        exporter.export_run(r, score, export_dir)
        count += 1

    console.print(f"  Exported {count} run(s) to {export_dir}\n")


# ── Receipt-Backed Execution v0 ───────────────────────────────────────────────

_RISK_COLORS = {"green": _GREEN, "yellow": _YELLOW, "red": _RED, "black": "bold red"}


def _execution_engine():
    from .execution import ExecutionEngine, ExecutionStore

    return ExecutionEngine(store=ExecutionStore(_DB_PATH))


def _redact_execution_text(text: str) -> str:
    from .execution.runner import redact_text

    return redact_text(text)


def _redact_execution_argv(argv: list[str]) -> list[str]:
    from .execution.runner import redact_argv

    return redact_argv(argv)


def _risk_str(level: str) -> str:
    color = _RISK_COLORS.get(level, "dim")
    return f"[{color}]{level}[/{color}]"


@app.command("run")
def run_task(
    task: str = typer.Argument(..., help="Task to plan and optionally execute"),
    runtime: str | None = typer.Option(None, "--runtime", help="Runtime id (google-antigravity, ollama, noop). Routed if omitted."),
    model: str | None = typer.Option(None, "--model", help="Model to request, if the runtime supports selection"),
    execute: bool = typer.Option(False, "--execute", help="Actually run the command (default is dry-run)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only; never start a subprocess (default behavior)"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Request runtime sandbox mode if supported"),
    timeout: int | None = typer.Option(None, "--timeout", help="Timeout in seconds for execution"),
    yes: bool = typer.Option(False, "--yes", help="Approve red-risk execution explicitly"),
    caffeinate: bool = typer.Option(
        False,
        "--caffeinate",
        help="Keep the Mac awake while this run is in progress (macOS only, off by default)",
    ),
) -> None:
    """Plan a task against an agent runtime and write a verifiable receipt.

    Defaults to dry-run. Execution is policy-gated: green/yellow tasks need
    --execute, red tasks need --execute --yes, black tasks are blocked.
    """
    from .execution.caffeinate import keep_awake

    engine = _execution_engine()
    try:
        with keep_awake(caffeinate and execute and not dry_run) as awake:
            outcome = engine.run_task(
                task,
                runtime=runtime,
                model=model,
                sandbox=sandbox,
                execute=execute and not dry_run,
                approved=yes,
                timeout_seconds=timeout,
            )
    except KeyError as exc:
        err.print(f"  [red]{exc.args[0]}[/red]")
        raise typer.Exit(1) from None
    except ValueError as exc:
        err.print(f"  [red]Command construction failed: {exc}[/red]")
        raise typer.Exit(1) from None

    plan = outcome.plan
    if awake:
        console.print("  [dim]Caffeinate:[/dim] active")
    console.print(f'\n  [bold]Task:[/bold] [dim]"{_redact_execution_text(task)}"[/dim]')
    console.print(
        f"  [dim]Runtime:[/dim] {plan.runtime}"
        f"  [dim]Risk:[/dim] {_risk_str(plan.risk_level)}"
        f"  [dim]Approval:[/dim] {'required' if plan.approval_required else 'no'}"
        f"  [dim]Mode:[/dim] {'dry-run' if plan.dry_run else 'execute'}"
    )
    for step in plan.steps:
        console.print(f"  [dim]Command:[/dim] {' '.join(_redact_execution_argv(step.command_argv))}")
    console.print(f"  [dim]Plan:[/dim] {plan.plan_id}")

    if not outcome.policy.allowed:
        console.print(f"  [{_YELLOW}]Blocked:[/{_YELLOW}] {outcome.policy.reason}")
    elif outcome.result is not None:
        r = outcome.result
        status_color = _GREEN if r.status == "succeeded" else _RED
        console.print(
            f"  [dim]Status:[/dim] [{status_color}]{r.status}[/{status_color}]"
            f"  [dim]Exit:[/dim] {r.return_code}"
            f"  [dim]Duration:[/dim] {r.duration_ms}ms"
        )
        if r.stdout_preview:
            console.print(f"  [dim]Output:[/dim] {_redact_execution_text(r.stdout_preview[:400])}")
        if r.error:
            console.print(f"  [{_RED}]Error:[/{_RED}] {r.error}")
    else:
        console.print("  [dim]Dry-run: no subprocess started. Plan and receipt stored.[/dim]")

    receipt = outcome.receipt
    console.print(
        f"  [dim]Receipt:[/dim] {receipt.receipt_id}"
        f"  [dim]Verification:[/dim] {receipt.verification_status}"
    )
    if receipt.artifact_ids:
        console.print(f"  [dim]Artifacts:[/dim] {len(receipt.artifact_ids)} hashed")
    console.print()
    if not outcome.policy.allowed and not plan.dry_run:
        raise typer.Exit(2)


def _resolve_plan(store, plan_id: str):
    plan = store.get_plan(plan_id)
    if plan is None:
        matches = [p for p in store.list_plans(limit=500) if p.plan_id.startswith(plan_id)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            err.print(f"  [red]Ambiguous plan prefix: {plan_id}[/red]")
            raise typer.Exit(1)
    return plan


@plans_app.command("list")
def plans_list(
    limit: int = typer.Option(20, "--limit", help="Max plans to show"),
) -> None:
    """List stored execution plans, newest first."""
    from .execution import ExecutionStore

    plans = ExecutionStore(_DB_PATH).list_plans(limit=limit)
    if not plans:
        console.print("\n  [dim]No plans stored yet. Try: opencobalt run \"hello\" --runtime noop[/dim]\n")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Plan", style="dim", max_width=14)
    table.add_column("Runtime")
    table.add_column("Risk")
    table.add_column("Mode")
    table.add_column("Task", style="dim", max_width=48)
    for plan in plans:
        table.add_row(
            plan.plan_id[:12],
            plan.runtime,
            _risk_str(plan.risk_level),
            "dry-run" if plan.dry_run else "execute",
            plan.task[:60],
        )
    console.print()
    console.print(table)
    console.print(f"  [dim]{len(plans)} plan(s). Inspect: opencobalt plans inspect <id>[/dim]\n")


@plans_app.command("inspect")
def plans_inspect(
    plan_id: str = typer.Argument(..., help="Plan id (full or unique prefix)"),
) -> None:
    """Show one stored plan: steps, command, risk, and approval needs."""
    from .execution import ExecutionStore

    store = ExecutionStore(_DB_PATH)
    plan = _resolve_plan(store, plan_id)
    if plan is None:
        err.print(f"  [red]Plan not found: {plan_id}[/red]")
        raise typer.Exit(1)

    console.print(f"\n  [bold]Plan[/bold] {plan.plan_id}")
    console.print(f"  [dim]Task:[/dim] {_redact_execution_text(plan.task)}")
    console.print(
        f"  [dim]Runtime:[/dim] {plan.runtime}"
        f"  [dim]Risk:[/dim] {_risk_str(plan.risk_level)}"
        f"  [dim]Approval required:[/dim] {'yes' if plan.approval_required else 'no'}"
        f"  [dim]Mode:[/dim] {'dry-run' if plan.dry_run else 'execute'}"
    )
    for step in plan.steps:
        console.print(
            f"  [dim]Step:[/dim] {' '.join(_redact_execution_argv(step.command_argv))}"
            f"  [dim]status:[/dim] {step.status}"
            f"  [dim]timeout:[/dim] {step.timeout_seconds}s"
        )
    console.print(f"  [dim]Replay:[/dim] opencobalt plans execute {plan.plan_id[:12]}\n")


@plans_app.command("execute")
def plans_execute(
    plan_id: str = typer.Argument(..., help="Plan id (full or unique prefix) to replay"),
    execute: bool = typer.Option(False, "--execute", help="Actually run the stored command (default is dry-run)"),
    yes: bool = typer.Option(False, "--yes", help="Approve red-risk replay explicitly"),
    timeout: int | None = typer.Option(None, "--timeout", help="Timeout in seconds for execution"),
    caffeinate: bool = typer.Option(
        False,
        "--caffeinate",
        help="Keep the Mac awake while this replay is in progress (macOS only, off by default)",
    ),
) -> None:
    """Replay a stored plan through the policy gate and write a new receipt.

    The stored command plan is reused as-is; risk is re-gated the same way
    as opencobalt run: dry-run by default, red needs --execute --yes, black
    stays blocked.
    """
    from .execution.caffeinate import keep_awake

    engine = _execution_engine()
    resolved = _resolve_plan(engine.store, plan_id)
    if resolved is None:
        err.print(f"  [red]Plan not found: {plan_id}[/red]")
        raise typer.Exit(1)

    try:
        with keep_awake(caffeinate and execute) as awake:
            outcome = engine.replay_plan(
                resolved.plan_id,
                execute=execute,
                approved=yes,
                timeout_seconds=timeout,
            )
    except ValueError as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from None

    plan = outcome.plan
    if awake:
        console.print("  [dim]Caffeinate:[/dim] active")
    console.print(f"\n  [bold]Replay of[/bold] {resolved.plan_id[:12]} [dim]as[/dim] {plan.plan_id}")
    console.print(
        f"  [dim]Runtime:[/dim] {plan.runtime}"
        f"  [dim]Risk:[/dim] {_risk_str(plan.risk_level)}"
        f"  [dim]Mode:[/dim] {'dry-run' if plan.dry_run else 'execute'}"
    )
    for step in plan.steps:
        console.print(f"  [dim]Command:[/dim] {' '.join(_redact_execution_argv(step.command_argv))}")

    if not outcome.policy.allowed:
        console.print(f"  [{_YELLOW}]Blocked:[/{_YELLOW}] {outcome.policy.reason}")
    elif outcome.result is not None:
        r = outcome.result
        status_color = _GREEN if r.status == "succeeded" else _RED
        console.print(
            f"  [dim]Status:[/dim] [{status_color}]{r.status}[/{status_color}]"
            f"  [dim]Exit:[/dim] {r.return_code}"
            f"  [dim]Duration:[/dim] {r.duration_ms}ms"
        )
        if r.error:
            console.print(f"  [{_RED}]Error:[/{_RED}] {r.error}")
    else:
        console.print("  [dim]Dry-run: no subprocess started. Plan and receipt stored.[/dim]")

    receipt = outcome.receipt
    console.print(
        f"  [dim]Receipt:[/dim] {receipt.receipt_id}"
        f"  [dim]Verification:[/dim] {receipt.verification_status}"
    )
    console.print()
    if not outcome.policy.allowed and not plan.dry_run:
        raise typer.Exit(2)


@receipts_app.command("list")
def receipts_list(
    runtime: str | None = typer.Option(None, "--runtime", help="Filter by runtime"),
    status: str | None = typer.Option(None, "--status", help="Filter by verification status"),
    limit: int = typer.Option(20, "--limit", help="Max receipts to show"),
) -> None:
    """List work receipts, newest first."""
    from .execution import ExecutionStore

    receipts = ExecutionStore(_DB_PATH).list_receipts(
        runtime=runtime, verification_status=status, limit=limit
    )
    if not receipts:
        console.print("\n  [dim]No receipts recorded yet. Try: opencobalt run \"hello\" --runtime noop[/dim]\n")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Receipt", style="dim", max_width=14)
    table.add_column("Runtime")
    table.add_column("Risk")
    table.add_column("Verification")
    table.add_column("Task", style="dim", max_width=48)
    for receipt in receipts:
        table.add_row(
            receipt.receipt_id[:12],
            receipt.selected_runtime,
            _risk_str(receipt.risk_level),
            receipt.verification_status,
            receipt.task[:60],
        )
    console.print()
    console.print(table)
    console.print(f"  [dim]{len(receipts)} receipt(s). Inspect: opencobalt receipts inspect <id>[/dim]\n")


@receipts_app.command("inspect")
def receipts_inspect(
    receipt_id: str = typer.Argument(..., help="Receipt id (full or unique prefix)"),
) -> None:
    """Show the full evidence chain for one receipt."""
    from .execution import ExecutionStore

    store = ExecutionStore(_DB_PATH)
    receipt = store.get_receipt(receipt_id)
    if receipt is None:
        matches = [r for r in store.list_receipts(limit=500) if r.receipt_id.startswith(receipt_id)]
        if len(matches) == 1:
            receipt = matches[0]
        elif len(matches) > 1:
            err.print(f"  [red]Ambiguous receipt prefix: {receipt_id}[/red]")
            raise typer.Exit(1)
    if receipt is None:
        err.print(f"  [red]Receipt not found: {receipt_id}[/red]")
        raise typer.Exit(1)

    console.print(f"\n  [bold]Receipt[/bold] {receipt.receipt_id}")
    console.print(f"  [dim]Task:[/dim] {_redact_execution_text(receipt.task)}")
    console.print(f"  [dim]Runtime:[/dim] {receipt.selected_runtime}")
    if receipt.route_reason:
        console.print(f"  [dim]Route reason:[/dim] {receipt.route_reason}")
    console.print(
        f"  [dim]Risk:[/dim] {_risk_str(receipt.risk_level)}"
        f"  [dim]Approval required:[/dim] {'yes' if receipt.approval_required else 'no'}"
        f"  [dim]Verification:[/dim] {receipt.verification_status}"
    )
    if receipt.command_plan:
        console.print(f"  [dim]Command plan:[/dim] {' '.join(_redact_execution_argv(receipt.command_plan))}")

    plan = store.get_plan(receipt.plan_id)
    if plan is not None:
        console.print(f"  [dim]Plan:[/dim] {plan.plan_id}  [dim]dry-run:[/dim] {plan.dry_run}")
    if receipt.execution_id:
        result = store.get_result(receipt.execution_id)
        if result is not None:
            console.print(
                f"  [dim]Execution:[/dim] {result.execution_id}"
                f"  [dim]status:[/dim] {result.status}"
                f"  [dim]exit:[/dim] {result.return_code}"
                f"  [dim]duration:[/dim] {result.duration_ms}ms"
            )
    for artifact_id in receipt.artifact_ids:
        artifact = store.get_artifact(artifact_id)
        if artifact is not None:
            console.print(
                f"  [dim]Artifact:[/dim] {artifact.artifact_id[:12]}"
                f" [{artifact.artifact_type}] {artifact.path}"
                f"  [dim]sha256:[/dim] {artifact.sha256[:16]}..."
            )
    console.print()


@receipts_app.command("verify")
def receipts_verify(
    receipt_id: str = typer.Argument(..., help="Receipt id to re-verify"),
) -> None:
    """Recompute artifact hashes for a receipt and update its status."""
    engine = _execution_engine()
    try:
        status = engine.verify_receipt(receipt_id)
    except KeyError:
        err.print(f"  [red]Receipt not found: {receipt_id}[/red]")
        raise typer.Exit(1) from None
    color = _GREEN if status == "verified" else (_YELLOW if status in ("partial", "unverified") else _RED)
    console.print(f"\n  Verification: [{color}]{status}[/{color}]\n")
    if status in ("failed", "partial"):
        raise typer.Exit(1)


@artifacts_app.command("attach")
def artifacts_attach(
    path: str = typer.Argument(..., help="Path to a local file to hash and attach"),
    source: str = typer.Option("manual", "--source", help="Source runtime"),
    plan: str | None = typer.Option(None, "--plan", help="Plan id to link"),
    execution: str | None = typer.Option(None, "--execution", help="Execution id to link"),
    artifact_type: str = typer.Option("unknown", "--type", help="Artifact type (stdout, report, diff, ...)"),
    summary: str | None = typer.Option(None, "--summary", help="One-line description"),
) -> None:
    """Hash a local file (SHA-256) and record it as an execution artifact."""
    from .execution import ExecutionStore, attach_artifact

    try:
        artifact = attach_artifact(
            path,
            source_runtime=source,
            artifact_type=artifact_type,
            plan_id=plan,
            execution_id=execution,
            summary=summary,
        )
    except FileNotFoundError as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from None
    ExecutionStore(_DB_PATH).save_artifact(artifact)
    console.print(f"\n  [bold]Artifact attached:[/bold] {artifact.artifact_id}")
    console.print(f"  [dim]Type:[/dim] {artifact.artifact_type}  [dim]Size:[/dim] {artifact.size_bytes} bytes")
    console.print(f"  [dim]SHA-256:[/dim] {artifact.sha256}\n")


@artifacts_app.command("verify")
def artifacts_verify(
    artifact_id: str = typer.Argument(..., help="Artifact id to verify"),
) -> None:
    """Recompute an artifact's hash and compare to the attached hash."""
    from .execution import ExecutionStore, verify_artifact

    artifact = ExecutionStore(_DB_PATH).get_artifact(artifact_id)
    if artifact is None:
        err.print(f"  [red]Artifact not found: {artifact_id}[/red]")
        raise typer.Exit(1)
    verification = verify_artifact(artifact)
    if verification.verified:
        console.print(f"\n  [{_GREEN}]verified[/{_GREEN}]  {verification.reason}\n")
    else:
        console.print(f"\n  [{_RED}]failed[/{_RED}]  {verification.reason}")
        console.print(f"  [dim]Expected:[/dim] {verification.expected_sha256}")
        if verification.actual_sha256:
            console.print(f"  [dim]Actual:[/dim]   {verification.actual_sha256}")
        console.print()
        raise typer.Exit(1)


@artifacts_app.command("list")
def artifacts_list(
    artifact_type: str | None = typer.Option(None, "--type", help="Filter by artifact type"),
    plan: str | None = typer.Option(None, "--plan", help="Filter by plan id"),
    limit: int = typer.Option(20, "--limit", help="Max artifacts to show"),
) -> None:
    """List execution artifacts, newest first."""
    from .execution import ExecutionStore

    artifacts = ExecutionStore(_DB_PATH).list_artifacts(
        artifact_type=artifact_type, plan_id=plan, limit=limit
    )
    if not artifacts:
        console.print("\n  [dim]No artifacts recorded yet.[/dim]\n")
        return
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Artifact", style="dim", max_width=14)
    table.add_column("Type")
    table.add_column("Size", justify="right")
    table.add_column("SHA-256", style="dim", max_width=20)
    table.add_column("Path", style="dim", max_width=48)
    for artifact in artifacts:
        table.add_row(
            artifact.artifact_id[:12],
            artifact.artifact_type,
            str(artifact.size_bytes),
            artifact.sha256[:16] + "...",
            artifact.path,
        )
    console.print()
    console.print(table)
    console.print(f"  [dim]{len(artifacts)} artifact(s).[/dim]\n")


# --- Opportunity engine commands ---


def _opportunity_store():
    from .core.opportunity_store import OpportunityStore

    return OpportunityStore(_DB_PATH)


def _opportunity_engine():
    from .core.opportunity_engine import OpportunityEngine

    return OpportunityEngine(db_path=_DB_PATH)


def _resolve_opportunity_run(store, run_id: str | None):
    return store.latest_run() if run_id is None else store.get_run(run_id)


def _print_opportunity_table(run) -> None:
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Track", style="dim", max_width=18)
    table.add_column("Name")
    table.add_column("Type", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Evidence", justify="right")
    table.add_column("Status")
    table.add_column("Plan", style="dim", max_width=16)
    for entry in (run.report.ranked if run.report else []):
        table.add_row(
            entry["track_id"][:16],
            entry["name"],
            entry["track_type"],
            f"{entry['total']:.3f}",
            str(entry["evidence_count"]),
            entry["status"],
            entry["plan_id"][:14] if entry["plan_id"] else "-",
        )
    console.print()
    console.print(table)


@opportunities_app.command("brainstorm")
def opportunities_brainstorm(
    goal: str = typer.Argument(..., help="Broad goal text to decompose"),
    top: int = typer.Option(3, "--top", help="How many top tracks get delegation plans"),
    no_plans: bool = typer.Option(False, "--no-plans", help="Skip automatic plan creation"),
) -> None:
    """Run the full supervised pipeline for a goal: classify, decompose,
    gather local evidence, score, plan the top tracks, and report.

    Everything is automatic but nothing executes: plans are proposals
    gated behind the existing execution policy.
    """
    engine = _opportunity_engine()
    run = engine.brainstorm(goal, top_n=top, plan=not no_plans)

    console.print(f"\n  [bold]Run[/bold] {run.run_id}  [dim]class:[/dim] {run.goal.goal_class}")
    console.print(f"  [dim]Goal:[/dim] {run.goal.text[:100]}")
    _print_opportunity_table(run)
    if run.plans:
        console.print(f"  [dim]{len(run.plans)} non-executing plan(s) created:[/dim]")
        for plan in run.plans:
            nodes = len(plan.delegation.get("nodes", []))
            console.print(
                f"    {plan.plan_id[:14]}  risk {_risk_str(plan.risk_level)}"
                f"  approval {plan.approval_state}  [dim]{nodes} subagent node(s)[/dim]"
            )
    if run.report:
        console.print("  [dim]Next actions:[/dim]")
        for action in run.report.next_actions:
            console.print(f"    - {action}")
    console.print(
        f"  [dim]{len(engine.events)} event(s) emitted. Report: "
        f"opencobalt opportunities report[/dim]\n"
    )


@opportunities_app.command("score")
def opportunities_score(
    run_id: str | None = typer.Option(None, "--run", help="Run id (default: latest)"),
    explain: str | None = typer.Option(None, "--explain", help="Track id to explain in full"),
) -> None:
    """Rescore the run's tracks from current evidence and rank them."""
    store = _opportunity_store()
    run = _resolve_opportunity_run(store, run_id)
    if run is None:
        err.print("  [red]No opportunity runs found. Try: opencobalt opportunities brainstorm \"goal\"[/red]")
        raise typer.Exit(1)

    engine = _opportunity_engine()
    engine.rescore(run)
    console.print(f"\n  [bold]Rescored[/bold] {run.run_id}  [dim]class:[/dim] {run.goal.goal_class}")
    _print_opportunity_table(run)

    if explain:
        track = run.get_track(explain)
        score = run.score_for(track.track_id) if track else None
        if score is None:
            err.print(f"  [red]Track not found: {explain}[/red]")
            raise typer.Exit(1)
        console.print(f"  [bold]Explanation for {track.name}:[/bold]")
        for line in score.explanation:
            console.print(f"    [dim]{line}[/dim]")
    console.print()


@opportunities_app.command("report")
def opportunities_report(
    run_id: str | None = typer.Option(None, "--run", help="Run id (default: latest)"),
) -> None:
    """Print the ranked opportunity report for a run."""
    store = _opportunity_store()
    run = _resolve_opportunity_run(store, run_id)
    if run is None:
        err.print("  [red]No opportunity runs found. Try: opencobalt opportunities brainstorm \"goal\"[/red]")
        raise typer.Exit(1)

    console.print(f"\n  [bold]Opportunity report[/bold] {run.run_id}")
    console.print(f"  [dim]Goal:[/dim] {run.goal.text[:100]}  [dim]class:[/dim] {run.goal.goal_class}")
    _print_opportunity_table(run)
    if run.report:
        console.print("  [dim]Next actions:[/dim]")
        for action in run.report.next_actions:
            console.print(f"    - {action}")
    console.print()


@opportunities_app.command("plan")
def opportunities_plan(
    track_id: str = typer.Argument(..., help="Track id (full or unique prefix)"),
    run_id: str | None = typer.Option(None, "--run", help="Run id (default: resolve by track)"),
) -> None:
    """Create a policy-aware delegation plan for one track. Never executes:
    risky steps stay pending until approved through the execution gate."""
    store = _opportunity_store()
    run = store.get_run(run_id) if run_id else store.find_run_for_track(track_id)
    if run is None:
        err.print(f"  [red]No run found containing track: {track_id}[/red]")
        raise typer.Exit(1)
    track = run.get_track(track_id)
    if track is None:
        err.print(f"  [red]Track not found: {track_id}[/red]")
        raise typer.Exit(1)

    engine = _opportunity_engine()
    plan = engine.plan_track(run, track.track_id)

    console.print(f"\n  [bold]Plan[/bold] {plan.plan_id}  [dim]track:[/dim] {track.name}")
    console.print(
        f"  [dim]Risk:[/dim] {_risk_str(plan.risk_level)}"
        f"  [dim]Approval:[/dim] {plan.approval_state}"
        f"  [dim]Executed:[/dim] no (plans never auto-execute)"
    )
    console.print("  [dim]Steps:[/dim]")
    for step in plan.steps:
        marker = "needs approval" if step["approval_required"] else "local"
        console.print(
            f"    - {step['description']}  [{_risk_str(step['risk_level'])}]  [dim]{marker}[/dim]"
        )
    nodes = {n["node_id"]: n for n in plan.delegation.get("nodes", [])}
    console.print(f"  [dim]Delegation tree ({len(nodes)} node(s)):[/dim]")
    stack = [plan.delegation["root_id"]] if plan.delegation.get("root_id") else []
    while stack:
        node = nodes[stack.pop()]
        indent = "    " + "  " * node["depth"]
        console.print(
            f"{indent}{node['agent_id']}  [dim]depth {node['depth']}"
            f" risk {node['risk_level']} scope {node['permission_scope']}"
            f" -> {node['output_contract']}[/dim]"
        )
        stack.extend(reversed(node["child_ids"]))
    console.print(
        "  [dim]Execution stays behind the policy gate: opencobalt run / plans execute.[/dim]\n"
    )


@opportunities_app.command("list")
def opportunities_list(
    limit: int = typer.Option(10, "--limit", help="Max runs to show"),
) -> None:
    """List stored opportunity runs, newest first."""
    runs = _opportunity_store().list_runs(limit=limit)
    if not runs:
        console.print("\n  [dim]No opportunity runs yet. Try: opencobalt opportunities brainstorm \"goal\"[/dim]\n")
        return
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Run", style="dim", max_width=18)
    table.add_column("Class")
    table.add_column("Goal", style="dim", max_width=56)
    table.add_column("Created", style="dim")
    for row in runs:
        table.add_row(
            row["run_id"][:16], row["goal_class"], row["goal_text"][:64],
            row["created_at"][:19],
        )
    console.print()
    console.print(table)
    console.print(f"  [dim]{len(runs)} run(s).[/dim]\n")


@opportunities_app.command("outcome")
def opportunities_outcome(
    track_id: str = typer.Argument(..., help="Track id the outcome belongs to"),
    outcome: str = typer.Argument(..., help="useful / neutral / wasted / abandoned"),
    receipt: str | None = typer.Option(None, "--receipt", help="Receipt id evidencing the outcome"),
    notes: str | None = typer.Option(None, "--notes", help="Free-form outcome notes"),
) -> None:
    """Record what actually happened with a track. Outcome history is the
    training signal for future learned routing."""
    try:
        outcome_id = _opportunity_store().record_outcome(
            track_id, outcome=outcome, receipt_id=receipt, notes=notes
        )
    except ValueError as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from None
    console.print(f"\n  [bold]Outcome recorded:[/bold] {outcome_id} ({outcome})\n")
