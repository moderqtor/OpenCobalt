"""OpenCobalt CLI.

Usage:
  opencobalt status
  opencobalt models
  opencobalt route TASK
  opencobalt auto GOAL
  opencobalt history [--limit N]
  opencobalt stats
  opencobalt benchmark
  opencobalt log [--summary TEXT]
  opencobalt memory status
  opencobalt memory add TEXT
  opencobalt memory export
  opencobalt context
  opencobalt run TASK [--runtime R] [--execute] [--yes]
  opencobalt continue MISSION_ID
  opencobalt handoff MISSION_ID --to TARGET
  opencobalt demo cold-resume [--target TARGET]
  opencobalt receipts list|inspect|verify
  opencobalt artifacts attach|verify|list
  opencobalt adapters list|inspect
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
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .agents.registry import get_agent
from .agents.registry import list_agents as _list_agents
from .cli_console import make_console, print_document
from .core.cold_resume_demo import NORTH_STAR, run_cold_resume_demo
from .core.cost import CostTracker
from .core.ledger import Ledger
from .core.memory import MemoryStore
from .core.mission_handoff import (
    MissionHandoffTargetError,
    normalize_handoff_target,
    render_mission_handoff,
)
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

adapters_app = typer.Typer(help="Runtime adapter contract commands.")
app.add_typer(adapters_app, name="adapters")

opportunities_app = typer.Typer(
    help="Autonomous opportunity engine (brainstorm, score, report, plan)."
)
app.add_typer(opportunities_app, name="opportunities")

approvals_app = typer.Typer(
    help="Approval bridge: authorize opportunity plans for policy-gated execution."
)
app.add_typer(approvals_app, name="approvals")

missions_app = typer.Typer(
    help="Mission State Machine v1: durable supervised missions that link "
    "discovery, approval, execution, receipts, provenance, and outcomes."
)
app.add_typer(missions_app, name="missions")

demo_app = typer.Typer(help="Deterministic local demos.")
app.add_typer(demo_app, name="demo")


class _EvolveGroup(typer.core.TyperGroup):
    """Let `opencobalt evolve "goal text"` behave like `evolve start`."""

    def resolve_command(self, ctx, args):
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["start", " ".join(args)]
        return super().resolve_command(ctx, args)


# invoke_without_command lets `opencobalt evolve "goal"` start a mission directly
evolve_app = typer.Typer(
    help="Evolve Mode: supervised self-improvement missions (propose, score, "
    "approve, execute, verify, learn).",
    cls=_EvolveGroup,
    invoke_without_command=True,
)
app.add_typer(evolve_app, name="evolve")

from opencobalt.core.daily_cli import (  # noqa: E402
    capture_cmd,
    clarify_cmd,
    daily_app,
    defer_cmd,
    done_cmd,
    focus_cmd,
    inbox_cmd,
    next_cmd,
    review_cmd,
    search_cmd,
    today_cmd,
    waiting_cmd,
)

app.add_typer(daily_app, name="daily")

# Top-level daily operator command aliases
app.command("capture")(capture_cmd)
app.command("inbox")(inbox_cmd)
app.command("clarify")(clarify_cmd)
app.command("today")(today_cmd)
app.command("next")(next_cmd)
app.command("focus")(focus_cmd)
app.command("done")(done_cmd)
app.command("defer")(defer_cmd)
app.command("waiting")(waiting_cmd)
app.command("review")(review_cmd)
app.command("search")(search_cmd)

console = make_console()
err = make_console(stderr=True)

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

    # ── Autonomy ──────────────────────────────────────────
    from .core.approval_bridge import ApprovalStore
    from .execution import ExecutionStore

    approval_store = ApprovalStore(_DB_PATH)
    pending_approvals = approval_store.count_pending()
    latest_receipts = ExecutionStore(_DB_PATH).list_receipts(limit=1)

    console.print("  [bold]Autonomy[/bold]")
    console.print(f"  [dim]{'─' * 42}[/dim]")
    if pending_approvals:
        console.print(
            f"  {_dot(False, warn=True)}  [dim]approvals [/dim]  "
            f"[{_YELLOW}]{pending_approvals} pending[/{_YELLOW}]"
            "  [dim]-- opencobalt approvals list[/dim]"
        )
    else:
        console.print(f"  {_dot(True)}  [dim]approvals [/dim]  none pending")
        checks_ok += 1
    checks_total += 1
    if latest_receipts:
        verification = latest_receipts[0].verification_status
        receipt_ok = verification != "failed"
        console.print(
            f"  {_dot(receipt_ok)}  [dim]receipt   [/dim]  "
            f"latest {verification}  [dim]·  {latest_receipts[0].receipt_id[:12]}[/dim]"
        )
        checks_ok += 1 if receipt_ok else 0
    else:
        console.print(
            f"  {_dot(True)}  [dim]receipt   [/dim]  [dim]none yet -- opencobalt run \"hello\" --runtime noop[/dim]"
        )
        checks_ok += 1
    checks_total += 1
    blocking = None
    for request in approval_store.list_requests(state="pending", limit=1):
        blocking = _next_blocking_action(request)
    if blocking:
        console.print(f"     [dim]next      [/dim]  {blocking}")
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
    goal: str = typer.Argument(..., help="Natural-language goal to plan automatically"),
    envelope: str | None = typer.Option(
        None,
        "--envelope",
        help="Autonomy envelope id, such as observe, plan, dry_run, or autonomous_lab",
    ),
    budget: str | None = typer.Option(
        None,
        "--budget",
        help="Cognitive budget id: low, medium, high, xhigh, or research",
    ),
    execute: bool = typer.Option(
        False,
        "--execute",
        help="Request execution in the plan. V1 still stops at authority boundaries.",
    ),
    iterations: int | None = typer.Option(
        None,
        "--iterations",
        "-n",
        help="Compatibility hint only. V1 auto plans instead of running long loops.",
    ),
    hours: float | None = typer.Option(
        None,
        "--hours",
        "-t",
        help="Compatibility hint only. V1 auto plans instead of running long loops.",
    ),
    use_limits: str | None = typer.Option(
        None,
        "--use-limits",
        help="Compatibility hint. Use --budget for cognitive budgets.",
    ),
    converge: bool = typer.Option(
        False,
        "--converge",
        help="Compatibility hint only. Convergence is planned as an internal primitive.",
    ),
    create_mission: bool = typer.Option(
        False,
        "--create-mission",
        "--mission",
        help="Persist the AutoPlan as a durable mission without executing it.",
    ),
    promote: bool = typer.Option(
        False,
        "--promote",
        help="After --create-mission, promote selected route steps into pending approvals.",
    ),
) -> None:
    """Plan the automatic internal route for a natural-language goal.

    V1 is conservative: it classifies, selects an envelope and cognitive
    budget, then prints the internal primitive sequence. It does not start a
    legacy long-running runner or external runtime.
    """
    from .core.auto_orchestrator import (
        AutoOrchestrator,
        render_auto_mission_record,
        render_auto_plan,
    )
    from .core.autonomy_envelopes import COGNITIVE_BUDGETS
    from .core.mission_engine import MissionEngine, render_auto_route_promotion_report

    selected_budget = budget
    if selected_budget is None and use_limits in COGNITIVE_BUDGETS:
        selected_budget = use_limits
    if promote and not create_mission:
        err.print("  [red]--promote requires --create-mission[/red]")
        raise typer.Exit(1)

    orchestrator = AutoOrchestrator()
    try:
        if create_mission:
            record = orchestrator.create_mission(
                goal,
                envelope_id=envelope,
                cognitive_budget_id=selected_budget,
                execute=execute,
                db_path=_DB_PATH,
                root=Path("."),
            )
            plan = record.plan
            promotion_report = (
                MissionEngine(db_path=_DB_PATH).promote_auto_route(record.mission_id)
                if promote
                else None
            )
        else:
            record = None
            promotion_report = None
            plan = orchestrator.plan(
                goal,
                envelope_id=envelope,
                cognitive_budget_id=selected_budget,
                execute=execute,
            )
    except ValueError as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print()
    console.print(render_auto_plan(plan))
    if record is not None:
        console.print()
        console.print(render_auto_mission_record(record))
    if promotion_report is not None:
        console.print()
        console.print(render_auto_route_promotion_report(promotion_report))
    if iterations is not None or hours is not None or use_limits or converge:
        console.print(
            "\n  [dim]Compatibility options were treated as planning hints; "
            "no long-running runner was started.[/dim]"
        )
    console.print()


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
        False, "--push-on-converge", help="Deprecated; no remote push is performed"
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
        False, "--push-on-converge", help="Deprecated; no remote push is performed"
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


# ── TUI helpers (pure-ish, tested in test_cli.py) ────────────────────────────

_EVENT_STREAMS = (
    ("execution", "execution.jsonl", _GREEN),
    ("approval", "approval.jsonl", _YELLOW),
    ("mission", "mission.jsonl", "#38bdf8"),
    ("evolve", "evolve.jsonl", _COBALT),
    ("opportunity", "opportunity.jsonl", "#c084fc"),
)


def _tool_chips() -> list[tuple[str, str, bool]]:
    """(label, detail, available) for the runtimes the header shows."""
    import shutil

    chips: list[tuple[str, str, bool]] = []
    for label, binary in (
        ("antigravity", "agy"),
        ("claude", "claude"),
        ("codex", "codex"),
    ):
        chips.append((label, "ready" if shutil.which(binary) else "not found",
                      shutil.which(binary) is not None))
    ollama_ok = shutil.which("ollama") is not None
    detail = "not found"
    if ollama_ok:
        try:
            models = discover_models()
            detail = models[0].name if models else "no models"
        except Exception:
            detail = "ready"
    chips.append(("ollama", detail, ollama_ok))
    return chips


def _merged_event_stream(limit: int = 18) -> list[tuple[str, str, str, str]]:
    """Recent (time, source, message, color) rows merged across the JSONL
    event spines, newest last. Local files only; missing spines are fine."""
    from .core.events import read_events

    rows: list[tuple[str, str, str, str]] = []
    base = Path(".opencobalt") / "events"
    for source, filename, color in _EVENT_STREAMS:
        for event in read_events(path=base / filename, limit=limit):
            stamp = str(event.get("timestamp", ""))[11:19]
            message = str(event.get("message", ""))[:72]
            rows.append((stamp, source, message, color))
    rows.sort(key=lambda r: r[0])
    return rows[-limit:]


def _git_branch() -> str:
    try:
        head = (Path(".git") / "HEAD").read_text(encoding="utf-8").strip()
        return head.rsplit("/", 1)[-1] if "/" in head else head[:12]
    except OSError:
        return "-"


@app.command()
def tui() -> None:
    """Launch the live control-plane dashboard. Press Ctrl+C to exit."""
    _REFRESH = 2
    from importlib.metadata import version as _pkg_version

    try:
        _version = _pkg_version("opencobalt")
    except Exception:
        _version = "0.1.0"

    def _make_header() -> Panel:
        chips = Text()
        chips.append("  ⬡ ", style=f"bold {_COBALT}")
        chips.append("OpenCobalt CLI ", style=f"bold {_COBALT}")
        chips.append(f"v{_version}", style="dim")
        for label, detail, available in _tool_chips():
            chips.append("   ")
            chips.append("● " if available else "○ ", style=_GREEN if available else "dim")
            chips.append(f"{label} ", style="bold" if available else "dim")
            chips.append(detail, style=_GREEN if available else "dim")
        return Panel(chips, box=box.ROUNDED, border_style="dim", expand=True)

    def _make_infobar() -> Panel:
        from .core.approval_bridge import ApprovalStore
        from .execution import ExecutionStore

        line = Text()
        line.append("  cwd: ", style="dim")
        line.append(str(Path(".").resolve()), style=_COBALT)
        try:
            pending = ApprovalStore(_DB_PATH).count_pending()
        except Exception:
            pending = 0
        line.append("   approvals: ", style="dim")
        line.append(
            f"{pending} pending" if pending else "none pending",
            style=_YELLOW if pending else _GREEN,
        )
        try:
            receipts = ExecutionStore(_DB_PATH).list_receipts(limit=1)
            latest = receipts[0].verification_status if receipts else "none yet"
        except Exception:
            latest = "none yet"
        line.append("   receipt: ", style="dim")
        line.append(latest, style=_GREEN if latest == "verified" else "dim")
        line.append("   git: ", style="dim")
        line.append(_git_branch(), style=_COBALT)
        return Panel(line, box=box.SIMPLE, expand=True)

    def _make_stream_panel() -> Panel:
        rows = _merged_event_stream(limit=16)
        if not rows:
            body: str | Text = (
                "[dim]No activity yet. Try: opencobalt opportunities "
                "brainstorm \"goal\" or opencobalt evolve start \"goal\"[/dim]"
            )
        else:
            text = Text()
            for stamp, source, message, color in rows:
                text.append(f" {stamp}  ", style="dim")
                text.append(f"[{source}]", style=f"bold {color}")
                text.append(f"{' ' * max(1, 13 - len(source))}{message}\n")
            body = text
        return Panel(
            body, title="[dim]Activity[/dim]", border_style="dim", expand=True
        )

    def _make_autonomy_panel() -> Panel:
        from .core.approval_bridge import ApprovalStore
        from .execution import ExecutionStore

        lines: list[str] = []
        try:
            store = ApprovalStore(_DB_PATH)
            pending = store.list_requests(state="pending", limit=3)
            if pending:
                for request in pending:
                    lines.append(
                        f"[{_YELLOW}]●[/{_YELLOW}] {request.request_id[:13]}  "
                        f"{request.track_name[:18]}  [{_risk_str(request.risk_level)}]"
                    )
                    action = _next_blocking_action(request)
                    if action:
                        lines.append(f"   [dim]{action.removeprefix('opencobalt ')}[/dim]")
            else:
                lines.append(f"[{_GREEN}]●[/{_GREEN}] no approvals pending")
        except Exception:
            lines.append("[dim]approvals unavailable[/dim]")
        lines.append("")
        try:
            receipts = ExecutionStore(_DB_PATH).list_receipts(limit=4)
            if receipts:
                for receipt in receipts:
                    color = _GREEN if receipt.verification_status == "verified" else "dim"
                    lines.append(
                        f"[{color}]●[/{color}] {receipt.receipt_id[:10]}  "
                        f"{receipt.verification_status:<10}  [dim]{receipt.task[:16]}[/dim]"
                    )
            else:
                lines.append("[dim]no receipts yet[/dim]")
        except Exception:
            lines.append("[dim]receipts unavailable[/dim]")
        return Panel(
            "\n".join(lines),
            title="[dim]Approvals + Receipts[/dim]",
            border_style="dim",
            expand=True,
        )

    def _make_routes_panel() -> Panel:
        try:
            decisions = _ledger().list_route_decisions(limit=5)
        except Exception:
            decisions = []
        if not decisions:
            body = "[dim]No route decisions yet.[/dim]"
        else:
            rows = []
            for d in decisions:
                ts = d.timestamp.strftime("%H:%M") if hasattr(d.timestamp, "strftime") else str(d.timestamp)[:5]
                tc = _tier_color(d.tier)
                tool = f"[{tc}]{d.recommended_tool:<13}[/{tc}]" if tc != "dim" else f"[dim]{d.recommended_tool:<13}[/dim]"
                rows.append(f"[dim]{ts}[/dim]  {tool}  {d.task[:22]}")
            body = "\n".join(rows)
        return Panel(body, title="[dim]Routes[/dim]", border_style="dim", expand=True)

    def _make_footer() -> Panel:
        from .execution import ExecutionStore

        line = Text()
        line.append("  ● ", style=_GREEN)
        line.append("DB ", style="dim")
        line.append("synced", style=_GREEN)
        line.append("   router: ", style="dim")
        line.append("deterministic", style=_GREEN)
        try:
            verified = len(
                ExecutionStore(_DB_PATH).list_receipts(
                    verification_status="verified", limit=500
                )
            )
            line.append("   receipts verified: ", style="dim")
            line.append(str(verified), style=_GREEN if verified else "dim")
        except Exception:
            pass
        line.append(f"   v{_version}", style="dim")
        line.append("   git: ", style="dim")
        line.append(_git_branch(), style=_COBALT)
        return Panel(line, box=box.SIMPLE, expand=True)

    def _make_layout() -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="infobar", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )
        layout["body"].split_row(
            Layout(name="stream", ratio=2),
            Layout(name="side", ratio=1),
        )
        layout["body"]["side"].split_column(
            Layout(name="autonomy"),
            Layout(name="routes"),
        )
        return layout

    layout = _make_layout()
    console.print("  [dim]OpenCobalt control plane -- Ctrl+C to exit[/dim]\n")

    try:
        with Live(layout, refresh_per_second=1, screen=True):
            while True:
                layout["header"].update(_make_header())
                layout["infobar"].update(_make_infobar())
                layout["body"]["stream"].update(_make_stream_panel())
                layout["body"]["side"]["autonomy"].update(_make_autonomy_panel())
                layout["body"]["side"]["routes"].update(_make_routes_panel())
                layout["footer"].update(_make_footer())
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
        if name == "claude-code":
            console.print(
                f"  {_dot(True)}  {name}"
                " [dim](installed; runtime evidence: "
                "opencobalt adapters inspect claude-code)[/dim]"
            )
        elif name == "codex-cli":
            console.print(
                f"  {_dot(True)}  {name}"
                " [dim](installed; runtime evidence: "
                "opencobalt adapters inspect codex-cli)[/dim]"
            )
        elif name == "cursor":
            console.print(
                f"  {_dot(True)}  {name}"
                " [dim](editor installed; runtime evidence: "
                "opencobalt adapters inspect cursor)[/dim]"
            )
        else:
            console.print(f"  {_dot(True)}  {name}")
    for name in sorted(inactive):
        console.print(f"  {_dot(False, warn=True)}  [dim]{name} (not installed)[/dim]")

    console.print()
    console.print(f"  [dim]{len(active)} active  {len(inactive)} not installed[/dim]\n")


@adapters_app.command("list")
def adapters_list() -> None:
    """List execution runtime adapters and their normalized contract status."""
    from .execution import available_runtimes, get_adapter

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Adapter", style=f"{_COBALT}")
    table.add_column("Available")
    table.add_column("Verifiability")
    table.add_column("Max risk")
    table.add_column("Capabilities", style="dim")
    for runtime_id in available_runtimes():
        adapter = get_adapter(runtime_id)
        snapshot = adapter.discover_capabilities()
        available = _dot(snapshot.available, warn=not snapshot.available)
        table.add_row(
            snapshot.adapter_id,
            available,
            snapshot.verifiability_level,
            _risk_str(snapshot.max_safe_risk),
            ", ".join(snapshot.capabilities[:5]) or "--",
        )
    console.print()
    console.print(table)
    console.print(f"  [dim]Adapter ids:[/dim] {', '.join(available_runtimes())}")
    console.print("  [dim]Inspect: opencobalt adapters inspect <adapter_id>[/dim]\n")


@adapters_app.command("inspect")
def adapters_inspect(
    adapter_id: str = typer.Argument(..., help="Adapter id or supported alias"),
) -> None:
    """Show one runtime adapter capability snapshot."""
    from .execution import get_adapter

    try:
        adapter = get_adapter(adapter_id)
    except KeyError as exc:
        err.print(f"  [red]{exc.args[0]}[/red]")
        raise typer.Exit(1) from None
    snapshot = adapter.discover_capabilities()
    console.print(f"\n  [bold]Adapter[/bold] {snapshot.adapter_id}")
    console.print(f"  [dim]Name:[/dim] {snapshot.adapter_name}")
    console.print(f"  [dim]Executable:[/dim] {snapshot.executable_path or adapter.executable}")
    console.print(f"  [dim]Available:[/dim] {'yes' if snapshot.available else 'no'}")
    console.print(f"  [dim]snapshot hash:[/dim] {snapshot.snapshot_hash}")
    console.print(f"  [dim]Capability level:[/dim] {snapshot.verifiability_level}")
    console.print(f"  [dim]Verifiability:[/dim] {snapshot.verifiability_level}")
    console.print(f"  [dim]Requires network:[/dim] {'yes' if snapshot.requires_network else 'no'}")
    console.print(
        f"  [dim]Requires credentials:[/dim] "
        f"{'yes' if snapshot.requires_credentials else 'no'}"
    )
    console.print(
        f"  [dim]Artifact support:[/dim] "
        f"{', '.join(snapshot.supported_artifact_types) or '--'}"
    )
    console.print(f"  [dim]Max safe risk:[/dim] {_risk_str(snapshot.max_safe_risk)}")
    if snapshot.capabilities:
        console.print("  [dim]Capabilities:[/dim]")
        for capability in snapshot.capabilities:
            detail = snapshot.capability_details.get(capability, {})
            source = detail.get("source") if isinstance(detail, dict) else "static"
            console.print(f"    {capability}  [dim]{source}[/dim]")
    if snapshot.limitations:
        console.print("  [dim]Limitations:[/dim]")
        for limitation in snapshot.limitations:
            console.print(f"    {limitation}")
    console.print("")


# ── UI command ────────────────────────────────────────────────────────────────


def _can_bind_ui_port(port: int) -> bool:
    """Match development-server bind semantics without accepting an active listener."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _ui_port_has_listener(port: int) -> bool:
    """Return whether a loopback listener is currently accepting connections."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.05)
            return probe.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _require_available_ui_port(
    label: str,
    port: int,
    *,
    release_timeout_seconds: float = 2.0,
) -> None:
    """Fail on a listener, but tolerate a bounded just-released macOS socket."""
    import time

    if not 1 <= port <= 65535:
        err.print(f"\n[{_RED}]{label} port must be between 1 and 65535.[/{_RED}]\n")
        raise typer.Exit(1)
    deadline = time.monotonic() + release_timeout_seconds
    while not _can_bind_ui_port(port):
        if _ui_port_has_listener(port) or time.monotonic() >= deadline:
            err.print(
                f"\n[{_RED}]{label} port {port} is already in use.[/{_RED}]  "
                "Choose another port and try again.\n"
            )
            raise typer.Exit(1) from None
        time.sleep(0.1)


def _stop_ui_processes(processes: list, *, timeout_seconds: float = 5.0) -> None:
    """Terminate launcher-owned process groups and wait for their ports to release."""
    import os
    import signal
    import subprocess
    import time

    def send(process, signal_number: int) -> None:
        if process.poll() is not None:
            return
        pid = getattr(process, "pid", None)
        if os.name == "posix" and isinstance(pid, int):
            try:
                process_group = os.getpgid(pid)
                if process_group != os.getpgrp():
                    os.killpg(process_group, signal_number)
                    return
            except (OSError, ProcessLookupError):
                pass
        if signal_number == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()

    for process in processes:
        send(process, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    for process in processes:
        remaining = max(0.01, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            send(process, signal.SIGKILL)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass


@app.command("ui")
def ui_shell(
    port: int = typer.Option(5173, "--port", help="Vite dev server port"),
    api_port: int = typer.Option(8000, "--api-port", help="API server port"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Skip opening browser"),
) -> None:
    """Start the API server and React dashboard. Opens http://localhost:5173."""
    import os
    import shutil
    import subprocess
    import time as _time
    import webbrowser

    if not shutil.which("npm"):
        err.print(f"\n[{_RED}]npm not found.[/{_RED}]  Install Node.js from https://nodejs.org\n")
        raise typer.Exit(1)

    if port == api_port:
        err.print(f"\n[{_RED}]UI and API ports must be different.[/{_RED}]\n")
        raise typer.Exit(1)
    _require_available_ui_port("UI", port)
    _require_available_ui_port("API", api_port)

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
            start_new_session=os.name == "posix",
        )
        procs.append(api_proc)

        vite_environment = dict(os.environ)
        vite_environment["OPENCOBALT_API_ORIGIN"] = f"http://127.0.0.1:{api_port}"
        vite_proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(port)],
            cwd=ui_dir,
            env=vite_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name == "posix",
        )
        procs.append(vite_proc)

        console.print(f"  [dim]API server :[/dim]  http://localhost:{api_port}")
        console.print(f"  [{_GREEN}]Dashboard running at[/{_GREEN}]  http://localhost:{port}")
        console.print("  [dim]Ctrl+C to stop.[/dim]\n")

        # Open the browser only after the API is actually ready. Child failures and
        # transient loopback resets remain bounded and produce a useful CLI error.
        import urllib.error
        import urllib.request
        readiness_deadline = _time.monotonic() + 10
        while True:
            if api_proc.poll() is not None:
                err.print(
                    f"\n[{_RED}]API server failed to start.[/{_RED}]  "
                    f"Run: pip install -e '.[server]'\n"
                )
                vite_proc.terminate()
                raise typer.Exit(1)
            if vite_proc.poll() is not None:
                err.print(
                    f"\n[{_RED}]UI server failed to start.[/{_RED}]  "
                    "Run: npm install --prefix ui\n"
                )
                api_proc.terminate()
                raise typer.Exit(1)
            try:
                response = urllib.request.urlopen(
                    f"http://127.0.0.1:{api_port}/api/status", timeout=1
                )
                response.close()
                break
            except (urllib.error.URLError, OSError):
                if _time.monotonic() >= readiness_deadline:
                    err.print(
                        f"\n[{_RED}]API server did not become ready within 10 seconds.[/{_RED}]\n"
                    )
                    raise typer.Exit(1) from None
                _time.sleep(0.1)

        if not no_browser:
            webbrowser.open(f"http://localhost:{port}")

        while True:
            api_status = api_proc.poll()
            vite_status = vite_proc.poll()
            if api_status is not None:
                err.print(
                    f"\n[{_RED}]API server stopped unexpectedly (exit {api_status}).[/{_RED}]\n"
                )
                raise typer.Exit(1)
            if vite_status is not None:
                err.print(
                    f"\n[{_RED}]UI server stopped unexpectedly (exit {vite_status}).[/{_RED}]\n"
                )
                raise typer.Exit(1)
            _time.sleep(0.2)

    except KeyboardInterrupt:
        pass
    finally:
        _stop_ui_processes(procs)
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
    console.print("  Status: [dim]planned, not implemented[/dim]\n")
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

def _route_exec(tool: str, task: str, dry_run: bool = False) -> None:
    from .core.runtime_boundary import legacy_runtime_block_message_for_runtime

    _ = task

    # Copy brief to clipboard
    _clipboard_brief(dry_run, tool=tool)

    if dry_run:
        console.print("\n  [dim]--dry-run: legacy launcher blocked[/dim]")
    else:
        console.print(f"\n  [{_YELLOW}]Legacy launcher blocked.[/{_YELLOW}]")
    console.print(f"  {legacy_runtime_block_message_for_runtime(tool)}", markup=False)


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


def _receipt_adapter_id(receipt) -> str:
    return receipt.adapter_id or receipt.selected_runtime


def _capability_names_for_receipt(receipt) -> list[str]:
    from .execution.normalization import legacy_capability_names

    normalized = receipt.capabilities_snapshot.get("normalized")
    if isinstance(normalized, dict):
        caps = normalized.get("capabilities")
        return list(caps) if isinstance(caps, list) else []
    return legacy_capability_names(receipt.capabilities_snapshot)


def _print_receipt_adapter_section(receipt) -> None:
    adapter_id = _receipt_adapter_id(receipt)
    console.print(f"  [dim]Adapter id:[/dim] {adapter_id}")
    caps = _capability_names_for_receipt(receipt)
    if receipt.capability_snapshot_hash:
        console.print(
            f"  [dim]Capability snapshot:[/dim] {receipt.capability_snapshot_hash[:16]}..."
        )
    else:
        console.print(
            "  [dim]Capability snapshot:[/dim] legacy-compatible "
            f"({', '.join(caps) if caps else 'no normalized hash'})"
        )
    if caps:
        console.print(f"  [dim]Capabilities:[/dim] {', '.join(caps[:8])}")
    if receipt.normalized_invocation is not None:
        invocation = receipt.normalized_invocation
        console.print(f"  [dim]Invocation hash:[/dim] {invocation.invocation_hash[:16]}...")
        console.print(f"  [dim]Environment:[/dim] {invocation.environment_policy}")
    if receipt.normalized_receipt is not None:
        normalized = receipt.normalized_receipt
        console.print(f"  [dim]Verifiability:[/dim] {normalized.verifiability_level}")
        console.print(f"  [dim]Events:[/dim] {normalized.event_count}")
        console.print(f"  [dim]Artifact hashes:[/dim] {len(normalized.artifact_hashes)}")
        if normalized.limitations:
            console.print(
                f"  [dim]Limitations:[/dim] {'; '.join(normalized.limitations[:4])}"
            )


@app.command("run")
def run_task(
    task: str = typer.Argument(..., help="Task to plan and optionally execute"),
    runtime: str | None = typer.Option(
        None,
        "--runtime",
        help=(
            "Runtime id (claude-code, codex-cli, cursor, google-antigravity, ollama, noop). "
            "Routed if omitted."
        ),
    ),
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
            _redact_execution_text(plan.task)[:60],
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
            _receipt_adapter_id(receipt),
            _risk_str(receipt.risk_level),
            receipt.verification_status,
            _redact_execution_text(receipt.task)[:60],
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
    _print_receipt_adapter_section(receipt)
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
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2), collapse_padding=True)
    table.add_column("Track", style="dim", no_wrap=True, overflow="ignore")
    table.add_column("Name", overflow="fold")
    table.add_column("Type", style="dim", no_wrap=True)
    table.add_column("Score", justify="right", no_wrap=True)
    table.add_column("Evidence", justify="right", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Plan", style="dim", no_wrap=True, overflow="ignore")
    for entry in (run.report.ranked if run.report else []):
        table.add_row(
            entry["track_id"],
            entry["name"],
            entry["track_type"],
            f"{entry['total']:.3f}",
            str(entry["evidence_count"]),
            entry["status"],
            entry["plan_id"] if entry["plan_id"] else "-",
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
    new: bool = typer.Option(False, "--new", help="Build a fresh plan even if one exists"),
) -> None:
    """Create a policy-aware delegation plan for one track. Never executes:
    risky steps stay pending until approved through the execution gate.
    Idempotent: an existing plan is reused unless --new is passed."""
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
    plan = engine.plan_track(run, track.track_id, new=new)

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


# --- Approval bridge commands ---


def _approval_bridge():
    from .core.approval_bridge import ApprovalBridge

    return ApprovalBridge(db_path=_DB_PATH)


_APPROVAL_STATE_COLORS = {
    "pending": _YELLOW,
    "approved": _GREEN,
    "rejected": _RED,
    "executed": _GREEN,
    "failed": _RED,
    "superseded": "dim",
}


def _approval_state_str(state: str) -> str:
    color = _APPROVAL_STATE_COLORS.get(state, "dim")
    return f"[{color}]{state}[/{color}]"


def _print_request_steps(request) -> None:
    console.print("  [dim]Steps:[/dim]")
    for step in request.steps:
        line = (
            f"    {step.step_id[:13]}  [{_risk_str(step.risk_level)}]"
            f"  {_approval_state_str(step.approval_state)}  {step.task[:56]}"
        )
        if step.blocked:
            line += f"  [{_RED}]blocked[/{_RED}]"
        console.print(line)
        if step.execution_plan_id:
            console.print(f"        [dim]exec plan:[/dim] {step.execution_plan_id[:14]}")
        if step.receipt_id:
            console.print(f"        [dim]receipt:[/dim]   {step.receipt_id[:14]}")


def _next_blocking_action(request) -> str | None:
    """One-line hint for the next command that unblocks this request."""
    rid = request.request_id[:13]
    for step in request.steps:
        if step.approval_state == "pending" and not step.blocked:
            return f"opencobalt approvals approve {rid} --step {step.step_id[:13]}"
    for step in request.steps:
        if step.approval_state == "approved":
            return f"opencobalt approvals run {rid} --execute"
    if any(s.approval_state == "executed" for s in request.steps):
        return f"opencobalt approvals outcome {rid} useful"
    return None


@approvals_app.command("list")
def approvals_list(
    state: str | None = typer.Option(None, "--state", help="Filter by request state"),
    limit: int = typer.Option(20, "--limit", help="Max requests to show"),
) -> None:
    """List approval requests, newest first."""
    requests = _approval_bridge().store.list_requests(state=state, limit=limit)
    if not requests:
        console.print(
            "\n  [dim]No approval requests yet. "
            "Try: opencobalt opportunities approve <TRACK_ID>[/dim]\n"
        )
        return
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2), collapse_padding=True)
    table.add_column("Request", style="dim", no_wrap=True, overflow="ignore")
    table.add_column("Track", overflow="fold")
    table.add_column("Risk", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Steps", justify="right", no_wrap=True)
    table.add_column("Goal", style="dim", overflow="fold")
    for request in requests:
        done = sum(1 for s in request.steps if s.approval_state == "executed")
        approved = sum(1 for s in request.steps if s.approval_state == "approved")
        table.add_row(
            request.request_id,
            request.track_name,
            _risk_str(request.risk_level),
            _approval_state_str(request.state),
            f"{done} run / {approved} ok / {len(request.steps)}",
            request.goal_text[:48],
        )
    console.print()
    console.print(table)
    console.print(f"  [dim]{len(requests)} request(s). Inspect: opencobalt approvals show <id>[/dim]\n")


@approvals_app.command("show")
def approvals_show(
    request_id: str = typer.Argument(..., help="Approval request id (full or prefix)"),
) -> None:
    """Show one approval request: steps, states, and linked execution."""
    bridge = _approval_bridge()
    request = bridge.store.get_request(request_id)
    if request is None:
        err.print(f"  [red]Approval request not found: {request_id}[/red]")
        raise typer.Exit(1)

    console.print(f"\n  [bold]Approval request[/bold] {request.request_id}")
    console.print(f"  [dim]Goal:[/dim] {request.goal_text[:90]}")
    console.print(
        f"  [dim]Track:[/dim] {request.track_name} ({request.track_id[:14]})"
        f"  [dim]Plan:[/dim] {request.opportunity_plan_id[:14]}"
    )
    score = f"{request.score_total:.3f}" if request.score_total is not None else "-"
    console.print(
        f"  [dim]Risk:[/dim] {_risk_str(request.risk_level)}"
        f"  [dim]State:[/dim] {_approval_state_str(request.state)}"
        f"  [dim]Score:[/dim] {score}"
        f"  [dim]Evidence:[/dim] {len(request.evidence_ids)}"
    )
    _print_request_steps(request)
    decisions = bridge.store.list_decisions(request.request_id)
    if decisions:
        console.print("  [dim]Decisions:[/dim]")
        for decision in decisions:
            reason = f" ({decision.reason})" if decision.reason else ""
            console.print(
                f"    {decision.decision} by {decision.decided_by}"
                f" on {decision.step_id[:13] if decision.step_id else 'request'}{reason}"
            )
    action = _next_blocking_action(request)
    if action:
        console.print(f"  [dim]Next:[/dim] {action}")
    console.print(f"  [dim]Lineage:[/dim] opencobalt why {request.request_id[:13]}\n")


@approvals_app.command("approve")
def approvals_approve(
    request_id: str = typer.Argument(..., help="Approval request id"),
    step: str | None = typer.Option(None, "--step", help="Approve only this step id"),
    reason: str = typer.Option("", "--reason", help="Why this was approved"),
) -> None:
    """Approve a request's steps (or one step). Black risk cannot be approved."""
    from .core.approval_bridge import ApprovalError

    bridge = _approval_bridge()
    try:
        approved = bridge.approve(request_id, step_id=step, reason=reason)
    except KeyError as exc:
        err.print(f"  [red]{exc.args[0]}[/red]")
        raise typer.Exit(1) from None
    except ApprovalError as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from None

    request = bridge.store.get_request(request_id)
    if not approved:
        console.print("\n  [dim]Nothing newly approved (already decided or blocked).[/dim]")
    else:
        console.print(f"\n  [bold]Approved {len(approved)} step(s):[/bold]")
        for s in approved:
            console.print(f"    {s.step_id[:13]}  [{_risk_str(s.risk_level)}]  {s.task[:60]}")
    if request is not None:
        console.print(f"  [dim]Request state:[/dim] {_approval_state_str(request.state)}")
        action = _next_blocking_action(request)
        if action:
            console.print(f"  [dim]Next:[/dim] {action}")
    console.print()


@approvals_app.command("reject")
def approvals_reject(
    request_id: str = typer.Argument(..., help="Approval request id"),
    step: str | None = typer.Option(None, "--step", help="Reject only this step id"),
    reason: str = typer.Option("", "--reason", help="Why this was rejected"),
) -> None:
    """Reject a request's steps (or one step)."""
    bridge = _approval_bridge()
    try:
        rejected = bridge.reject(request_id, step_id=step, reason=reason)
    except KeyError as exc:
        err.print(f"  [red]{exc.args[0]}[/red]")
        raise typer.Exit(1) from None
    console.print(f"\n  [bold]Rejected {len(rejected)} step(s).[/bold]")
    request = bridge.store.get_request(request_id)
    if request is not None:
        console.print(f"  [dim]Request state:[/dim] {_approval_state_str(request.state)}")
    console.print()


@approvals_app.command("run")
def approvals_run(
    request_id: str = typer.Argument(..., help="Approval request id"),
    step: str | None = typer.Option(None, "--step", help="Run only this step id"),
    runtime: str | None = typer.Option(
        None, "--runtime", help="Runtime id (google-antigravity, ollama, noop). Routed if omitted."
    ),
    execute: bool = typer.Option(False, "--execute", help="Actually run (default is dry-run)"),
    yes: bool = typer.Option(False, "--yes", help="Approve red-risk execution explicitly"),
    rerun: bool = typer.Option(False, "--rerun", help="Run a step again even if already executed"),
) -> None:
    """Hand approved steps to the execution engine, one receipt per step.

    The existing policy gate stays in charge: dry-run by default, --execute
    for green/yellow, --execute --yes for red, black blocked. Unapproved
    steps are refused with the command that would approve them.
    """
    bridge = _approval_bridge()
    engine = _execution_engine()
    try:
        reports = bridge.run_steps(
            request_id,
            engine=engine,
            step_id=step,
            runtime=runtime,
            execute=execute,
            approved=yes,
            rerun=rerun,
        )
    except KeyError as exc:
        err.print(f"  [red]{exc.args[0]}[/red]")
        raise typer.Exit(1) from None

    request = bridge.store.get_request(request_id)
    console.print(f"\n  [bold]Approval run[/bold] {request.request_id if request else request_id}")
    refused = 0
    for report in reports:
        s = report.step
        if report.action == "executed":
            result = report.outcome.result
            status_color = _GREEN if result and result.status == "succeeded" else _RED
            console.print(
                f"    {s.step_id[:13]}  [{status_color}]{report.action}[/{status_color}]"
                f"  {s.task[:48]}"
            )
            console.print(
                f"        [dim]receipt:[/dim] {s.receipt_id}"
                f"  [dim]verification:[/dim] {report.outcome.receipt.verification_status}"
            )
        elif report.action == "dry_run":
            console.print(f"    {s.step_id[:13]}  [dim]dry-run[/dim]  {s.task[:48]}")
            console.print(
                f"        [dim]plan:[/dim] {s.execution_plan_id[:14]}"
                f"  [dim]receipt:[/dim] {s.receipt_id[:14]}"
                "  [dim](no subprocess started)[/dim]"
            )
        elif report.action in ("refused", "blocked"):
            refused += 1
            console.print(
                f"    {s.step_id[:13]}  [{_RED}]{report.action}[/{_RED}]  {s.task[:48]}"
            )
            console.print(f"        [dim]{report.reason}[/dim]")
        else:  # skipped
            console.print(f"    {s.step_id[:13]}  [dim]skipped[/dim]  {report.reason}")
    if not execute and any(r.action == "dry_run" for r in reports):
        console.print("  [dim]Dry-run only. Add --execute to run for real.[/dim]")
    if request is not None:
        console.print(f"  [dim]Request state:[/dim] {_approval_state_str(request.state)}")
        action = _next_blocking_action(request)
        if action:
            console.print(f"  [dim]Next:[/dim] {action}")
    console.print()
    if refused and execute:
        raise typer.Exit(2)


@approvals_app.command("outcome")
def approvals_outcome(
    request_id: str = typer.Argument(..., help="Approval request id"),
    outcome: str = typer.Argument(..., help="useful / neutral / wasted / abandoned"),
    notes: str | None = typer.Option(None, "--notes", help="Free-form outcome notes"),
) -> None:
    """Record an outcome for the opportunity track behind an approval request.

    Links the latest executed step's receipt as evidence, closing the loop
    from approval back into opportunity outcome history.
    """
    bridge = _approval_bridge()
    request = bridge.store.get_request(request_id)
    if request is None:
        err.print(f"  [red]Approval request not found: {request_id}[/red]")
        raise typer.Exit(1)
    receipt_id = None
    for s in request.steps:
        if s.receipt_id and s.approval_state in ("executed", "failed"):
            receipt_id = s.receipt_id
    try:
        outcome_id = _opportunity_store().record_outcome(
            request.track_id,
            outcome=outcome,
            plan_id=request.opportunity_plan_id,
            receipt_id=receipt_id,
            notes=notes,
        )
    except ValueError as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from None
    console.print(f"\n  [bold]Outcome recorded:[/bold] {outcome_id} ({outcome})")
    console.print(f"  [dim]Track:[/dim] {request.track_id[:14]}")
    if receipt_id:
        console.print(f"  [dim]Receipt evidence:[/dim] {receipt_id[:14]}")
    console.print()


@opportunities_app.command("approve")
def opportunities_approve(
    source_id: str = typer.Argument(..., help="Track or opportunity plan id (full or prefix)"),
    run_id: str | None = typer.Option(None, "--run", help="Run id (default: resolve by source)"),
    new: bool = typer.Option(False, "--new", help="Supersede any existing request for this source"),
) -> None:
    """Promote an opportunity track or plan into an approval request.

    Builds the plan first if the track has none (planning only). Green
    steps are auto-approved by policy; yellow/red wait for explicit
    approval; black stays blocked. Nothing executes here.
    """
    store = _opportunity_store()
    if run_id:
        run = store.get_run(run_id)
    else:
        run = store.find_run_for_track(source_id) or store.find_run_for_plan(source_id)
    if run is None:
        err.print(f"  [red]No run found containing track or plan: {source_id}[/red]")
        raise typer.Exit(1)

    bridge = _approval_bridge()
    try:
        request, created = bridge.promote(
            run, source_id, new=new, opportunity_store=store
        )
    except KeyError as exc:
        err.print(f"  [red]{exc.args[0]}[/red]")
        raise typer.Exit(1) from None

    verb = "created" if created else "reused (pass --new to supersede)"
    console.print(f"\n  [bold]Approval request {verb}:[/bold] {request.request_id}")
    console.print(
        f"  [dim]Track:[/dim] {request.track_name} ({request.track_id[:14]})"
        f"  [dim]Risk:[/dim] {_risk_str(request.risk_level)}"
        f"  [dim]State:[/dim] {_approval_state_str(request.state)}"
    )
    _print_request_steps(request)
    rid = request.request_id[:13]
    console.print("  [dim]Next commands:[/dim]")
    console.print(f"    opencobalt approvals show {rid}")
    action = _next_blocking_action(request)
    if action:
        console.print(f"    {action}")
    console.print(f"    opencobalt why {rid}\n")


# --- Evolve Mode ---


def _evolve_engine(**kwargs):
    from .core.evolve import EvolveEngine

    return EvolveEngine(db_path=_DB_PATH, **kwargs)


def _resolve_evolve_mission(engine, mission_id: str | None):
    if mission_id:
        return engine.store.get_mission(mission_id)
    return engine.store.latest_mission()


def _print_evolve_report(report) -> None:
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Candidate", style="dim", max_width=18)
    table.add_column("Title", max_width=44)
    table.add_column("Type", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Escape", justify="right")
    table.add_column("Risk")
    table.add_column("Status")
    for entry in report.ranked:
        escape = entry.get("wrapperware_escape")
        table.add_row(
            entry["candidate_id"][:16],
            entry["title"][:44],
            entry["candidate_type"],
            f"{entry['total']:.3f}",
            f"{escape:.2f}" if escape is not None else "-",
            _risk_str(entry["risk_level"]),
            entry["status"],
        )
    console.print()
    console.print(table)
    if report.next_commands:
        console.print("  [dim]Next commands:[/dim]")
        for command in report.next_commands:
            console.print(f"    {command}")
    console.print()


@evolve_app.callback(invoke_without_command=True)
def evolve_cmd(ctx: typer.Context) -> None:
    """Evolve Mode: supervised self-improvement missions."""
    if ctx.invoked_subcommand is None:
        if ctx.args:
            goal = " ".join(ctx.args).strip()
            if goal:
                evolve_start(goal=goal)
                return
        console.print(
            "  [dim]Usage: opencobalt evolve start \"goal text\" "
            "| evolve report | evolve candidates | evolve approve <id> "
            "| evolve run <id> | evolve roadmap [--write][/dim]"
        )


@evolve_app.command("start")
def evolve_start(
    goal: str = typer.Argument(
        ..., help="Mission goal, e.g. \"make OpenCobalt more useful this week\""
    ),
    candidates: int = typer.Option(6, "--candidates", help="Max candidates to propose"),
) -> None:
    """Start a supervised self-improvement mission: read the roadmap and
    repo, propose and score candidates, plan the subagent analysis tree,
    and report. Nothing executes; approval and execution stay behind the
    existing gates."""
    from .core.evolve import EvolvePolicy

    engine = _evolve_engine(policy=EvolvePolicy(max_candidates=candidates))
    result = engine.start_mission(goal)
    mission = result.mission
    console.print(
        f"\n  [bold {_COBALT}]Evolve mission[/bold {_COBALT}] {mission.mission_id}"
        f"  [dim]status:[/dim] {mission.status}"
    )
    console.print(f"  [dim]Goal:[/dim] {mission.goal[:100]}")
    console.print(
        f"  [dim]Roadmap proposals:[/dim] {len(mission.roadmap_proposals)}"
        f"  [dim]Subagent nodes:[/dim] {len(mission.delegation.get('nodes', []))}"
        f"  [dim]Backing run:[/dim] {mission.run_id[:16] if mission.run_id else '-'}"
    )
    _print_evolve_report(result.report)
    console.print(
        "  [dim]Supervised mode: nothing executed, no docs written, no push. "
        f"{len(engine.events)} event(s) emitted.[/dim]\n"
    )


@evolve_app.command("list")
def evolve_list(
    limit: int = typer.Option(10, "--limit", help="Max missions to show"),
) -> None:
    """List evolve missions, newest first."""
    missions = _evolve_engine().store.list_missions(limit=limit)
    if not missions:
        console.print("\n  [dim]No evolve missions yet. Try: opencobalt evolve \"goal\"[/dim]\n")
        return
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("Mission", style="dim", max_width=18)
    table.add_column("Status")
    table.add_column("Goal", style="dim", max_width=56)
    table.add_column("Created", style="dim")
    for row in missions:
        table.add_row(
            row["mission_id"][:16], row["status"], row["goal"][:56],
            row["created_at"][:19],
        )
    console.print()
    console.print(table)
    console.print(f"  [dim]{len(missions)} mission(s).[/dim]\n")


@evolve_app.command("report")
def evolve_report(
    mission_id: str = typer.Argument(None, help="Mission id (default: latest)"),
) -> None:
    """Print the ranked candidate report for a mission."""
    engine = _evolve_engine()
    mission = _resolve_evolve_mission(engine, mission_id)
    if mission is None or mission.report is None:
        err.print("  [red]No evolve mission found. Try: opencobalt evolve \"goal\"[/red]")
        raise typer.Exit(1)
    console.print(
        f"\n  [bold]Evolve report[/bold] {mission.mission_id}"
        f"  [dim]status:[/dim] {mission.status}"
    )
    console.print(f"  [dim]Goal:[/dim] {mission.goal[:100]}")
    _print_evolve_report(mission.report)


@evolve_app.command("candidates")
def evolve_candidates(
    mission_id: str = typer.Argument(None, help="Mission id (default: latest)"),
    explain: str | None = typer.Option(None, "--explain", help="Candidate id to explain in full"),
) -> None:
    """Show candidate details: score breakdown, steps, and linked ids."""
    engine = _evolve_engine()
    mission = _resolve_evolve_mission(engine, mission_id)
    if mission is None:
        err.print("  [red]No evolve mission found. Try: opencobalt evolve \"goal\"[/red]")
        raise typer.Exit(1)
    items = engine.store.list_candidates(mission.mission_id)
    console.print(f"\n  [bold]Candidates[/bold] for {mission.mission_id}")
    for candidate in items:
        total = f"{candidate.score.total:.3f}" if candidate.score else "-"
        console.print(
            f"\n  {candidate.candidate_id[:16]}  [{candidate.candidate_type}]"
            f"  score {total}  risk {_risk_str(candidate.risk_level)}"
            f"  status {candidate.status}"
        )
        console.print(f"    [dim]{candidate.title}[/dim]")
        for step in candidate.steps:
            console.print(f"      - {step}")
        if candidate.track_id:
            console.print(f"    [dim]track:[/dim] {candidate.track_id[:16]}")
        if candidate.approval_request_id:
            console.print(f"    [dim]approval:[/dim] {candidate.approval_request_id[:16]}")
        if candidate.receipt_ids:
            console.print(f"    [dim]receipts:[/dim] {len(candidate.receipt_ids)}")
        if explain and candidate.candidate_id.startswith(explain) and candidate.score:
            console.print("    [dim]Score explanation:[/dim]")
            for line in candidate.score.explanation:
                console.print(f"      [dim]{line}[/dim]")
    console.print()


@evolve_app.command("approve")
def evolve_approve(
    candidate_id: str = typer.Argument(..., help="Candidate id (full or prefix)"),
) -> None:
    """Promote a candidate through the Approval Bridge and approve its
    approvable steps. Black-risk steps stay blocked as always."""
    engine = _evolve_engine()
    try:
        candidate, request = engine.approve_candidate(candidate_id)
    except KeyError as exc:
        err.print(f"  [red]{exc.args[0]}[/red]")
        raise typer.Exit(1) from None
    console.print(
        f"\n  [bold]Candidate approved:[/bold] {candidate.candidate_id[:16]}"
        f"  [dim]status:[/dim] {candidate.status}"
    )
    console.print(
        f"  [dim]Approval request:[/dim] {request.request_id}"
        f"  [dim]state:[/dim] {_approval_state_str(request.state)}"
    )
    _print_request_steps(request)
    console.print(
        f"  [dim]Next:[/dim] opencobalt evolve run {candidate.candidate_id[:14]}"
        " --runtime noop [--execute]\n"
    )


@evolve_app.command("run")
def evolve_run(
    candidate_id: str = typer.Argument(..., help="Candidate id (full or prefix)"),
    runtime: str | None = typer.Option(
        None, "--runtime", help="Runtime id (google-antigravity, ollama, noop). Routed if omitted."
    ),
    execute: bool = typer.Option(False, "--execute", help="Actually run (default is dry-run)"),
    yes: bool = typer.Option(False, "--yes", help="Approve red-risk execution explicitly"),
    rerun: bool = typer.Option(False, "--rerun", help="Run again even if already executed"),
) -> None:
    """Run a candidate's approved steps through the policy-gated execution
    engine. Dry-run by default; every step writes a receipt."""
    engine = _evolve_engine()
    exec_engine = _execution_engine()
    try:
        candidate, reports = engine.run_candidate(
            candidate_id,
            engine=exec_engine,
            runtime=runtime,
            execute=execute,
            approved=yes,
            rerun=rerun,
        )
    except KeyError as exc:
        err.print(f"  [red]{exc.args[0]}[/red]")
        raise typer.Exit(1) from None
    console.print(
        f"\n  [bold]Evolve run[/bold] {candidate.candidate_id[:16]}"
        f"  [dim]status:[/dim] {candidate.status}"
    )
    refused = 0
    for report in reports:
        s = report.step
        if report.action == "executed":
            console.print(f"    {s.step_id[:13]}  [{_GREEN}]executed[/{_GREEN}]  {s.task[:48]}")
            console.print(
                f"        [dim]receipt:[/dim] {s.receipt_id}"
                f"  [dim]verification:[/dim] {report.outcome.receipt.verification_status}"
            )
        elif report.action == "dry_run":
            console.print(f"    {s.step_id[:13]}  [dim]dry-run[/dim]  {s.task[:48]}")
        elif report.action in ("refused", "blocked"):
            refused += 1
            console.print(f"    {s.step_id[:13]}  [{_RED}]{report.action}[/{_RED}]  {s.task[:48]}")
            console.print(f"        [dim]{report.reason}[/dim]")
        else:
            console.print(f"    {s.step_id[:13]}  [dim]skipped[/dim]  {report.reason}")
    if not execute and any(r.action == "dry_run" for r in reports):
        console.print("  [dim]Dry-run only. Add --execute to run for real.[/dim]")
    if candidate.status == "verified":
        console.print(
            f"  [dim]Record outcome:[/dim] opencobalt approvals outcome "
            f"{candidate.approval_request_id[:13]} useful"
        )
    console.print(f"  [dim]Lineage:[/dim] opencobalt why {candidate.candidate_id[:14]}\n")
    if refused and execute:
        raise typer.Exit(2)


@evolve_app.command("roadmap")
def evolve_roadmap(
    mission_id: str = typer.Argument(None, help="Mission id (default: latest)"),
    write: bool = typer.Option(
        False, "--write", help="Append proposals to docs/ROADMAP.md (explicitly gated)"
    ),
) -> None:
    """Show a mission's roadmap proposals. Writing to docs/ROADMAP.md
    requires the explicit --write flag and only appends a marked section."""
    from .core.evolve import EvolvePolicy

    engine = _evolve_engine(policy=EvolvePolicy(allow_roadmap_write=write))
    mission = _resolve_evolve_mission(engine, mission_id)
    if mission is None:
        err.print("  [red]No evolve mission found. Try: opencobalt evolve \"goal\"[/red]")
        raise typer.Exit(1)
    console.print(f"\n  [bold]Roadmap proposals[/bold] for {mission.mission_id}")
    if not mission.roadmap_proposals:
        console.print("  [dim]No proposals recorded for this mission.[/dim]\n")
        return
    for proposal in mission.roadmap_proposals:
        console.print(
            f"    [{proposal.proposal_type}] {proposal.title}"
            f"  [dim]escape {proposal.wrapperware_escape_value:.2f}"
            f"  status {proposal.status}[/dim]"
        )
    if write:
        path = engine.write_roadmap_proposals(mission)
        console.print(f"\n  [bold]Proposals appended to[/bold] {path}")
        console.print("  [dim]Review the diff before committing; nothing was pushed.[/dim]\n")
    else:
        console.print(
            "\n  [dim]Proposals are read-only. Append to docs/ROADMAP.md with: "
            f"opencobalt evolve roadmap {mission.mission_id[:13]} --write[/dim]\n"
        )


# --- Mission State Machine v1 ---


def _mission_engine():
    from .core.mission_engine import MissionEngine

    return MissionEngine(db_path=_DB_PATH)


_MISSION_STATUS_COLORS = {
    "completed": _GREEN,
    "failed": _RED,
    "abandoned": "dim",
    "awaiting_approval": _YELLOW,
    "awaiting_feedback": _YELLOW,
}


def _mission_status_str(status: str) -> str:
    color = _MISSION_STATUS_COLORS.get(status, _COBALT)
    return f"[{color}]{status}[/{color}]"


def _print_mission_steps(steps) -> None:
    if not steps:
        return
    console.print("  [dim]Steps:[/dim]")
    for step in steps:
        line = (
            f"    {step.step_id[:14]}  [{_risk_str(step.risk_level)}]"
            f"  {_approval_state_str(step.approval_state)}"
            f"  [dim]{step.execution_state}[/dim]  {step.title[:48]}"
        )
        if step.risk_level == "black":
            line += f"  [{_RED}]blocked[/{_RED}]"
        console.print(line)
        if step.auto_step_why:
            markers = []
            if step.auto_promotion_classification:
                markers.append(step.auto_promotion_classification)
            if step.uses_execution_engine:
                markers.append("uses ExecutionEngine")
            if step.expected_receipt:
                markers.append("expected receipt")
            if step.requires_approval:
                markers.append("approval expected")
            suffix = "  [dim]" + ", ".join(markers) + "[/dim]" if markers else ""
            console.print(f"        [dim]why:[/dim] {step.auto_step_why}{suffix}")
        if step.auto_promotion_reason:
            console.print(
                f"        [dim]promotion:[/dim] {step.auto_promotion_reason}",
                highlight=False,
            )
        if step.approval_request_id:
            console.print(
                f"        [dim]approval:[/dim] {step.approval_request_id[:13]}"
                f" / {step.approval_step_id[:13] if step.approval_step_id else ''}"
            )
        if step.blocked_authority and step.auto_promotion_classification == "blocked_authority":
            console.print(
                "        [dim]blocked authority:[/dim] "
                + ", ".join(step.blocked_authority),
                highlight=False,
            )
        if step.execution_plan_id:
            console.print(f"        [dim]exec plan:[/dim] {step.execution_plan_id[:14]}")
        if step.receipt_id:
            console.print(f"        [dim]receipt:[/dim] {step.receipt_id[:14]}")


def _print_auto_route_promotion_summary(mission, steps) -> None:
    if mission.mission_type != "auto":
        return
    promoted = [step for step in steps if step.approval_request_id]
    blocked = [
        step
        for step in promoted
        if step.auto_promotion_classification == "blocked_authority"
    ]
    unpromoted = [step for step in steps if not step.approval_request_id]
    console.print("  [dim]Auto route promotion:[/dim]")
    if mission.approval_request_id:
        console.print(f"    approval request: {mission.approval_request_id[:13]}")
    else:
        console.print("    approval request: not promoted")
    console.print(f"    promoted: {len(promoted)}")
    console.print(f"    blocked authority placeholders: {len(blocked)}")
    console.print(f"    unpromoted: {len(unpromoted)}")


def _print_mission_extraction_summary(record) -> None:
    if record is None:
        return
    extraction = record.extraction
    console.print("  [dim]Mission extraction:[/dim]")
    console.print(
        f"    {record.extraction_id[:14]}  v{record.version}  "
        f"source: {record.source_type}  extractor: {record.extractor}",
        markup=False,
        highlight=False,
    )
    console.print(
        "    confidence "
        f"overall: {extraction.confidence.overall}  "
        f"goal: {extraction.confidence.goal}  "
        f"status: {extraction.confidence.status}",
        markup=False,
        highlight=False,
    )
    console.print(
        f"    extracted status: {extraction.status}  "
        f"next actions: {len(extraction.next_actions)}  "
        f"open questions: {len(extraction.open_questions)}",
        markup=False,
        highlight=False,
    )
    if extraction.risks:
        console.print(
            "    risks: " + "; ".join(extraction.risks[:3]),
            markup=False,
            highlight=False,
        )


def _print_mission_verification_summary(record) -> None:
    if record is None:
        return
    verification = record.verification
    console.print("  [dim]Mission extraction verification:[/dim]")
    console.print(
        f"    {record.verification_id[:14]}  v{record.version}  "
        f"extraction: {record.extraction_id[:14]}  "
        f"status: {verification.status}  verifier: {record.verifier}",
        markup=False,
        highlight=False,
    )
    console.print(
        "    confidence after verification "
        f"overall: {verification.overall_confidence_after_verification}  "
        f"warnings: {len(verification.warnings)}  "
        f"redactions: {len(verification.redactions_detected)}  "
        "prompt-injection lines: "
        f"{verification.prompt_injection_lines_detected}",
        markup=False,
        highlight=False,
    )
    for warning in verification.warnings[:3]:
        console.print(f"    warning: {warning}", markup=False, highlight=False)


def _render_close_session_output(
    *,
    mission,
    extraction_record,
    verification_record=None,
    handoff_target: str,
    handoff_output: str | None = None,
) -> str:
    lines = [
        "Mission session closed.",
        "",
        f"Mission: {mission.mission_id}",
        f"Extraction: {extraction_record.extraction_id}",
    ]

    if verification_record is not None:
        verification = verification_record.verification
        lines.extend(
            [
                (
                    f"Verification: {verification_record.verification_id} "
                    f"{verification.status}"
                ),
                f"Verification status: {verification.status}",
                f"Verification warnings: {len(verification.warnings)}",
            ]
        )
        for warning in verification.warnings[:5]:
            lines.append(f"- {warning}")

    lines.extend(
        [
            "",
            "Cold resume:",
            f"opencobalt continue {mission.mission_id}",
            "",
            "Handoff:",
            f"opencobalt handoff {mission.mission_id} --to {handoff_target}",
        ]
    )

    if handoff_output is not None:
        lines.extend(
            [
                "",
                f"Handoff packet ({handoff_target}):",
                handoff_output,
            ]
        )

    return "\n".join(lines)


def _mission_next_action(mission, steps) -> str | None:
    mid = mission.mission_id[:13]
    if mission.mission_type == "auto":
        if mission.approval_request_id:
            return f"opencobalt approvals show {mission.approval_request_id[:13]}"
        return f"opencobalt missions promote-auto {mid}"
    if mission.status in ("opportunities_generated", "candidates_generated",
                          "plan_proposed", "verifying"):
        return f"opencobalt missions advance {mid}"
    for step in steps:
        if step.approval_state == "pending" and step.risk_level != "black":
            return f"opencobalt missions approve-step {step.step_id[:14]}"
    for step in steps:
        if step.approval_state == "approved":
            return f"opencobalt missions run-step {step.step_id[:14]} --execute"
    if mission.status == "awaiting_feedback":
        return f"opencobalt missions outcome {mid} useful"
    return None


def _format_context_items(values: list[str]) -> list[str]:
    if not values:
        return ["- none recorded"]
    return [f"- {value}" for value in values]


def _verification_context_lines(verification) -> list[str]:
    if verification is None:
        return [
            "Verification: unverified",
            "Verifier warnings:",
            "- Latest extraction has not been verified against a source report.",
        ]
    result = verification.verification
    lines = [
        (
            "Verification: "
            f"{result.status} ({verification.verification_id}; "
            f"overall after verification: "
            f"{result.overall_confidence_after_verification})"
        ),
        "Verifier warnings:",
    ]
    if result.warnings:
        lines.extend(_format_context_items(result.warnings))
    else:
        lines.append("- none recorded")
    return lines


def _render_continue_context(mission, record, verification=None) -> str:
    if record is None:
        return "\n".join(
            [
                "OPENCOBALT MISSION CONTEXT",
                "",
                f"Mission: {mission.mission_id}",
                f"Goal: {mission.goal}",
                f"Status: {mission.status}",
                "Last known state: no mission extraction is attached yet.",
                "",
                "Findings:",
                "- none recorded",
                "Decisions:",
                "- none recorded",
                "Assumptions:",
                "- none recorded",
                "Open questions:",
                "- Attach a mission extraction before relying on cold resume.",
                "Risks:",
                "- No extracted mission intelligence is available.",
                "Files touched:",
                "- none recorded",
                "Artifacts:",
                "- none recorded",
                "Source-mentioned references:",
                "- none recorded",
                "Next actions:",
                f"- opencobalt missions ingest-session {mission.mission_id[:13]} --file PATH",
                "",
                "Verification: unverified",
                "Verifier warnings:",
                "- No extraction is attached, so no extraction verification exists.",
                "",
                "Confidence:",
                "- overall: low",
                "Continuation instruction:",
                "You are resuming this mission from OpenCobalt durable mission state. "
                "Treat this context as the source of continuity, but verify claims "
                "against the repository before making changes.",
            ]
        )

    extraction = record.extraction
    confidence = extraction.confidence
    lines = [
        "OPENCOBALT MISSION CONTEXT",
        "",
        f"Mission: {mission.mission_id}",
        f"Goal: {extraction.goal or mission.goal}",
        f"Status: {extraction.status}",
        (
            "Last known state: "
            f"mission status {mission.status}; extraction {record.extraction_id} "
            f"version {record.version}; source {record.source_type}; "
            f"recorded {record.created_at}"
        ),
        "",
        *_verification_context_lines(verification),
        "",
        "Findings:",
        *_format_context_items(extraction.findings),
        "Decisions:",
        *_format_context_items(extraction.decisions),
        "Assumptions:",
        *_format_context_items(extraction.assumptions),
        "Open questions:",
        *_format_context_items(extraction.open_questions),
        "Risks:",
        *_format_context_items(extraction.risks),
        "Files touched:",
        *_format_context_items(extraction.files_touched),
        "Artifacts:",
        *_format_context_items(extraction.artifacts),
        "Source-mentioned references:",
        *_format_context_items(extraction.source_references),
        "Next actions:",
        *_format_context_items(extraction.next_actions),
        "",
        "Confidence:",
        f"- goal: {confidence.goal}",
        f"- status: {confidence.status}",
        f"- findings: {confidence.findings}",
        f"- decisions: {confidence.decisions}",
        f"- assumptions: {confidence.assumptions}",
        f"- open_questions: {confidence.open_questions}",
        f"- next_actions: {confidence.next_actions}",
        f"- files_touched: {confidence.files_touched}",
        f"- source_references: {confidence.source_references}",
        f"- artifacts: {confidence.artifacts}",
        f"- risks: {confidence.risks}",
        f"- overall: {confidence.overall}",
        (
            "- verified_overall: "
            + (
                verification.verification.overall_confidence_after_verification
                if verification is not None
                else "low"
            )
        ),
        "Continuation instruction:",
        "You are resuming this mission from OpenCobalt durable mission state. "
        "Treat this context as the source of continuity, but verify claims "
        "against the repository before making changes.",
    ]
    return "\n".join(lines)


@app.command("continue")
def continue_mission(
    mission_id: str = typer.Argument(..., help="Mission id (full or prefix)"),
) -> None:
    """Print a compact cold-resume context package for another agent."""
    engine = _mission_engine()
    mission = engine.store.get_mission(mission_id)
    if mission is None:
        err.print(f"  [red]Unknown mission: {mission_id}[/red]")
        raise typer.Exit(1)
    record = engine.store.latest_mission_extraction(mission.mission_id)
    verification = (
        engine.store.latest_mission_extraction_verification(
            mission.mission_id,
            extraction_id=record.extraction_id,
        )
        if record is not None
        else None
    )
    print_document(
        console,
        _render_continue_context(mission, record, verification),
    )


@app.command("handoff")
def handoff_mission(
    mission_id: str = typer.Argument(..., help="Mission id (full or prefix)"),
    to: str = typer.Option(
        "generic",
        "--to",
        help="Handoff target: generic, codex-cli, claude-code, cursor",
    ),
) -> None:
    """Print a runtime-specific copy-paste handoff packet.

    This renders durable mission memory only. It does not start or contact the
    requested runtime.
    """
    engine = _mission_engine()
    mission = engine.store.get_mission(mission_id)
    if mission is None:
        err.print(f"  [red]Unknown mission: {mission_id}[/red]")
        raise typer.Exit(1)
    try:
        target = normalize_handoff_target(to)
    except MissionHandoffTargetError as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc
    record = engine.store.latest_mission_extraction(mission.mission_id)
    verification = (
        engine.store.latest_mission_extraction_verification(
            mission.mission_id,
            extraction_id=record.extraction_id,
        )
        if record is not None
        else None
    )
    print_document(
        console,
        render_mission_handoff(
            mission=mission,
            target=target,
            extraction_record=record,
            verification_record=verification,
        ),
    )


@demo_app.command("cold-resume")
def demo_cold_resume(
    target_value: str = typer.Option(
        "generic",
        "--target",
        help="Handoff target: generic, codex-cli, claude-code, cursor",
    ),
) -> None:
    """Run a deterministic local cold-resume demo.

    The demo creates a mission, ingests a built-in sanitized old-agent report,
    verifies the extraction, and renders continue/handoff previews. It does not
    execute agents, runtimes, subprocesses, networks, or model APIs.
    """
    try:
        target = normalize_handoff_target(target_value)
    except MissionHandoffTargetError as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc

    engine = _mission_engine()
    result = run_cold_resume_demo(engine)
    mission = result.mission
    extraction_record = result.extraction_record
    verification_record = result.verification_record
    continue_output = _render_continue_context(
        mission,
        extraction_record,
        verification_record,
    )
    handoff_output = render_mission_handoff(
        mission=mission,
        target=target,
        extraction_record=extraction_record,
        verification_record=verification_record,
    )

    console.print(
        _render_cold_resume_demo_output(
            mission_id=mission.mission_id,
            extraction_id=extraction_record.extraction_id,
            verification_id=verification_record.verification_id,
            verification_status=verification_record.verification.status,
            verification_warning_count=len(verification_record.verification.warnings),
            target=target,
            continue_output=continue_output,
            handoff_output=handoff_output,
            safety=result.safety,
        ),
        markup=False,
        highlight=False,
    )


def _render_cold_resume_demo_output(
    *,
    mission_id: str,
    extraction_id: str,
    verification_id: str,
    verification_status: str,
    verification_warning_count: int,
    target: str,
    continue_output: str,
    handoff_output: str,
    safety,
) -> str:
    safety_lines = [
        _safety_line(
            "injected instruction treated as data",
            safety.injected_instruction_absent_from_store,
        ),
        _safety_line(
            "fake token absent from stored extraction and verifier record",
            safety.sensitive_content_absent_from_store,
        ),
        _safety_line(
            "raw report not persisted in mission store",
            safety.raw_report_absent_from_store,
        ),
        _safety_line(
            "verification warnings visible",
            safety.verification_warnings_visible,
        ),
        _safety_line(
            "temporary source report removed",
            safety.temp_report_removed,
        ),
        "- No runtime execution performed",
        "- No network or model API calls performed",
        "- No authority granted by this demo output",
    ]
    return "\n".join(
        [
            "OpenCobalt cold-resume demo",
            "",
            "North star:",
            NORTH_STAR,
            "",
            f"Created mission: {mission_id}",
            f"Attached extraction: {extraction_id}",
            (
                f"Verified extraction: {verification_id} "
                f"({verification_status}; warnings: {verification_warning_count})"
            ),
            "",
            "Safety checks:",
            *safety_lines,
            "",
            "Cold resume:",
            f"opencobalt continue {mission_id}",
            "",
            "Cold resume preview:",
            _preview_block(continue_output, max_lines=16),
            "",
            "Handoff:",
            f"opencobalt handoff {mission_id} --to {target}",
            "",
            f"Handoff packet preview ({target}):",
            _handoff_preview_block(handoff_output),
            "",
            "Rerun commands:",
            f".venv/bin/opencobalt demo cold-resume --target {target}",
            f".venv/bin/opencobalt continue {mission_id}",
            f".venv/bin/opencobalt handoff {mission_id} --to {target}",
        ]
    )


def _safety_line(label: str, passed: bool) -> str:
    status = "ok" if passed else "failed"
    return f"- {label}: {status}"


def _preview_block(text: str, *, max_lines: int) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join([*lines[:max_lines], "..."])


def _handoff_preview_block(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= 18:
        return "\n".join(lines)
    preview = [*lines[:18], "..."]
    try:
        target_start = lines.index("Target-specific instructions:")
    except ValueError:
        return "\n".join(preview)
    preview.extend(lines[target_start : target_start + 6])
    return "\n".join(preview)


@missions_app.command("start")
def missions_start(
    goal: str = typer.Argument(..., help="The mission goal"),
    mission_type: str = typer.Option(
        "auto", "--type", help="auto / opportunity / evolve"
    ),
    max_risk: str = typer.Option(
        "red", "--max-risk", help="Risk budget: green / yellow / red. "
        "Only tightens the normal gates; black is always blocked."
    ),
    top_n: int = typer.Option(3, "--top", help="Tracks to plan during discovery"),
) -> None:
    """Create a durable mission and run opportunity discovery.

    Discovery proposes, scores, and plans. Nothing executes; execution
    only ever happens later via approved steps and --execute.
    """
    from .core.mission_engine import MissionError

    engine = _mission_engine()
    try:
        mission = engine.start_mission(
            goal, mission_type=mission_type, max_risk=max_risk, top_n=top_n
        )
    except MissionError as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(
        f"\n  [bold]Mission started:[/bold] {mission.mission_id}"
        f"\n  [dim]Goal:[/dim]   {mission.goal}"
        f"\n  [dim]Type:[/dim]   {mission.mission_type}"
        f"\n  [dim]Status:[/dim] {_mission_status_str(mission.status)}"
        f"\n  [dim]Budget:[/dim] {_risk_str(mission.max_risk)}"
    )
    if mission.run_id:
        console.print(f"  [dim]Run:[/dim]    {mission.run_id}")
    if mission.evolve_mission_id:
        console.print(f"  [dim]Evolve:[/dim] {mission.evolve_mission_id}")
    console.print(
        f"\n  [dim]Next:[/dim] opencobalt missions advance {mission.mission_id[:13]}\n"
    )


@missions_app.command("list")
def missions_list(
    limit: int = typer.Option(10, "--limit", help="Missions to show"),
) -> None:
    """List missions with status, selection, approvals, and outcomes."""
    engine = _mission_engine()
    rows = engine.store.list_missions(limit=limit)
    if not rows:
        console.print(
            "\n  [dim]No missions yet. Start one:[/dim] "
            'opencobalt missions start "your goal"\n'
        )
        return
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2), collapse_padding=True)
    table.add_column("mission_id", style=_COBALT, no_wrap=True, overflow="ignore")
    table.add_column("status", no_wrap=True)
    table.add_column("track", no_wrap=True, overflow="ignore")
    table.add_column("approval", no_wrap=True, overflow="ignore")
    table.add_column("receipt", no_wrap=True, overflow="ignore")
    table.add_column("outcome", no_wrap=True)
    table.add_column("goal", overflow="fold")
    for row in rows:
        table.add_row(
            row["mission_id"],
            _mission_status_str(row["status"]),
            row["selected_track_id"] or "",
            row["approval_request_id"] or "",
            row["last_receipt_id"] or "",
            row["outcome"] or "",
            row["goal"][:38],
        )
    console.print(table)


@missions_app.command("show")
def missions_show(
    mission_id: str = typer.Argument(..., help="Mission id (full or prefix)"),
) -> None:
    """Show one mission's full state: selection, plan, steps, receipts."""
    engine = _mission_engine()
    mission = engine.store.get_mission(mission_id)
    if mission is None:
        err.print(f"  [red]Unknown mission: {mission_id}[/red]")
        raise typer.Exit(1)
    steps = engine.sync_steps(mission)
    console.print(
        f"\n  [bold]Mission[/bold] {mission.mission_id}"
        f"\n  [dim]Goal:[/dim]      {mission.goal}"
        f"\n  [dim]Type:[/dim]      {mission.mission_type}"
        f"\n  [dim]Status:[/dim]    {_mission_status_str(mission.status)}"
        f"\n  [dim]Budget:[/dim]    {_risk_str(mission.max_risk)}"
    )
    for label, value in (
        ("Run", mission.run_id),
        ("Evolve", mission.evolve_mission_id),
        ("Track", mission.selected_track_id),
        ("Candidate", mission.selected_candidate_id),
        ("Plan", mission.active_plan_id),
        ("Approval", mission.approval_request_id),
        ("Receipt", mission.last_receipt_id),
        ("Outcome", mission.outcome),
    ):
        if value:
            console.print(f"  [dim]{label}:[/dim]{' ' * max(1, 10 - len(label))}{value}")
    if mission.auto_plan_id:
        console.print(
            f"  [dim]Auto plan:[/dim] {mission.auto_plan_id}"
            f"\n  [dim]Intent:[/dim]    {mission.auto_intent}"
            f"\n  [dim]Envelope:[/dim]  {mission.autonomy_envelope}"
            f"\n  [dim]Budget:[/dim]    {mission.cognitive_budget}"
        )
        if mission.auto_plan_hash:
            console.print(f"  [dim]Plan hash:[/dim] {mission.auto_plan_hash[:16]}")
    extraction = engine.store.latest_mission_extraction(mission.mission_id)
    _print_mission_extraction_summary(extraction)
    verification = (
        engine.store.latest_mission_extraction_verification(
            mission.mission_id,
            extraction_id=extraction.extraction_id,
        )
        if extraction is not None
        else None
    )
    _print_mission_verification_summary(verification)
    _print_mission_steps(steps)
    _print_auto_route_promotion_summary(mission, steps)
    action = _mission_next_action(mission, steps)
    if action:
        console.print(f"\n  [dim]Next:[/dim] {action}")
    console.print("")


@missions_app.command("ingest-session")
def missions_ingest_session(
    mission_id: str = typer.Argument(..., help="Mission id (full or prefix)"),
    file: Path = typer.Option(
        ...,
        "--file",
        help="Local session transcript or agent output file to extract",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Extract mission intelligence from a completed local session file.

    v0 uses the deterministic local extractor and performs no network/model
    calls. The raw transcript is not persisted.
    """
    from pydantic import ValidationError

    from .core.mission_engine import MissionError

    engine = _mission_engine()
    try:
        record = engine.ingest_session_file(mission_id, file)
    except (KeyError, MissionError, OSError, ValidationError, ValueError) as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(
        f"\n  [bold]Extraction attached:[/bold] {record.extraction_id}"
        f"\n  [dim]Mission:[/dim]   {record.mission_id}"
        f"\n  [dim]Version:[/dim]   {record.version}"
        f"\n  [dim]Source:[/dim]    {record.source_type}"
        f"\n  [dim]Status:[/dim]    {record.extraction.status}"
        f"\n  [dim]Confidence:[/dim] overall: {record.extraction.confidence.overall}"
        f"\n\n  [dim]Continue:[/dim]  opencobalt continue {record.mission_id[:13]}\n",
        highlight=False,
    )


@missions_app.command("attach-extraction")
def missions_attach_extraction(
    mission_id: str = typer.Argument(..., help="Mission id (full or prefix)"),
    json_file: Path = typer.Option(
        ...,
        "--json",
        help="Externally generated extraction JSON matching the v0 schema",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Attach externally generated extraction JSON after schema validation."""
    from pydantic import ValidationError

    from .core.mission_engine import MissionError

    engine = _mission_engine()
    try:
        record = engine.attach_extraction_json(mission_id, json_file)
    except (KeyError, MissionError, OSError, ValidationError, ValueError) as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(
        f"\n  [bold]Extraction attached:[/bold] {record.extraction_id}"
        f"\n  [dim]Mission:[/dim]   {record.mission_id}"
        f"\n  [dim]Version:[/dim]   {record.version}"
        f"\n  [dim]Source:[/dim]    {record.source_type}"
        f"\n  [dim]Status:[/dim]    {record.extraction.status}"
        f"\n  [dim]Confidence:[/dim] overall: {record.extraction.confidence.overall}"
        f"\n\n  [dim]Continue:[/dim]  opencobalt continue {record.mission_id[:13]}\n",
        highlight=False,
    )


@missions_app.command("verify-extraction")
def missions_verify_extraction(
    mission_id: str = typer.Argument(..., help="Mission id (full or prefix)"),
    source_file: Path = typer.Option(
        ...,
        "--source-file",
        help="Local source report used to verify the attached extraction",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    extraction_id: str | None = typer.Option(
        None,
        "--extraction-id",
        help="Specific extraction id to verify. Defaults to the latest extraction.",
    ),
) -> None:
    """Verify a mission extraction against a source report.

    v0 is deterministic and local. The source report is read for this command
    only; raw source text is not persisted.
    """
    from .core.mission_engine import MissionError

    engine = _mission_engine()
    try:
        record = engine.verify_extraction(
            mission_id,
            extraction_id=extraction_id,
            source_file=source_file,
        )
    except (KeyError, MissionError, OSError, ValueError) as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc
    verification = record.verification
    console.print(
        f"\n  [bold]Extraction verified:[/bold] {record.verification_id}"
        f"\n  [dim]Mission:[/dim]     {record.mission_id}"
        f"\n  [dim]Extraction:[/dim]  {record.extraction_id}"
        f"\n  [dim]Version:[/dim]     {record.version}"
        f"\n  [dim]Status:[/dim]      {verification.status}"
        "\n  [dim]Confidence:[/dim]  overall after verification: "
        f"{verification.overall_confidence_after_verification}"
        f"\n  [dim]Warnings:[/dim]    {len(verification.warnings)}"
        f"\n  [dim]Redactions:[/dim]  {len(verification.redactions_detected)}"
        "\n  [dim]Prompt injection lines:[/dim] "
        f"{verification.prompt_injection_lines_detected}",
        highlight=False,
    )
    for warning in verification.warnings[:5]:
        console.print(f"    warning: {warning}", markup=False, highlight=False)
    console.print(
        f"\n  [dim]Continue:[/dim]  opencobalt continue {record.mission_id[:13]}\n",
        highlight=False,
    )


@missions_app.command("close-session")
def missions_close_session(
    mission_id: str = typer.Argument(..., help="Mission id (full or prefix)"),
    file: Path = typer.Option(
        ...,
        "--file",
        help="Finished local agent report to close into mission memory",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    verify: bool = typer.Option(
        False,
        "--verify",
        help="Verify the new extraction against the same local report",
    ),
    handoff_to: str | None = typer.Option(
        None,
        "--handoff-to",
        help="Print a handoff packet for: generic, codex-cli, claude-code, cursor",
    ),
) -> None:
    """Close a finished local agent report into durable mission memory.

    This is a deterministic local composition of session ingest, optional
    extraction verification, and optional handoff rendering. It does not call
    live models, execute agents, launch runtime adapters, or persist raw report
    text.
    """
    from pydantic import ValidationError

    from .core.mission_engine import MissionError

    try:
        target = normalize_handoff_target(handoff_to or "generic")
    except MissionHandoffTargetError as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc

    engine = _mission_engine()
    try:
        extraction_record = engine.ingest_session_file(mission_id, file)
        mission = engine.store.get_mission(extraction_record.mission_id)
        if mission is None:
            raise MissionError(f"unknown mission: {extraction_record.mission_id}")
        verification_record = (
            engine.verify_extraction(
                extraction_record.mission_id,
                source_file=file,
                extraction_id=extraction_record.extraction_id,
            )
            if verify
            else None
        )
    except (KeyError, MissionError, OSError, ValidationError, ValueError) as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc

    handoff_output = (
        render_mission_handoff(
            mission=mission,
            target=target,
            extraction_record=extraction_record,
            verification_record=verification_record,
        )
        if handoff_to is not None
        else None
    )
    console.print(
        _render_close_session_output(
            mission=mission,
            extraction_record=extraction_record,
            verification_record=verification_record,
            handoff_target=target,
            handoff_output=handoff_output,
        ),
        markup=False,
        highlight=False,
    )


@missions_app.command("advance")
def missions_advance(
    mission_id: str = typer.Argument(..., help="Mission id (full or prefix)"),
) -> None:
    """Advance the mission one safe stage. Stops at approval boundaries;
    never executes anything."""
    from .core.mission_engine import MissionError

    engine = _mission_engine()
    try:
        report = engine.advance(mission_id)
    except (KeyError, MissionError) as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc
    mission = report.mission
    console.print(
        f"\n  [bold]Mission[/bold] {mission.mission_id[:14]}"
        f"  [dim]status:[/dim] {_mission_status_str(mission.status)}"
        f"\n  [dim]Action:[/dim] {report.action}"
        f"\n  {report.detail}"
    )
    _print_mission_steps(report.steps)
    action = _mission_next_action(mission, report.steps or engine.store.list_steps(mission.mission_id))
    if action:
        console.print(f"\n  [dim]Next:[/dim] {action}")
    console.print("")


@missions_app.command("promote-auto")
def missions_promote_auto(
    mission_id: str = typer.Argument(..., help="Auto mission id (full or prefix)"),
) -> None:
    """Promote selected auto route steps into pending approval requests.

    This records approval state only. It does not approve, execute, or create
    receipts.
    """
    from .core.mission_engine import MissionError, render_auto_route_promotion_report

    engine = _mission_engine()
    try:
        report = engine.promote_auto_route(mission_id)
    except (KeyError, MissionError) as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print()
    console.print(render_auto_route_promotion_report(report))
    console.print("")


@missions_app.command("approve-step")
def missions_approve_step(
    step_id: str = typer.Argument(..., help="Mission step id (full or prefix)"),
    reason: str = typer.Option("", "--reason", help="Why this step is approved"),
) -> None:
    """Approve one pending mission step. Black risk cannot be approved;
    approval never executes anything."""
    from .core.approval_bridge import ApprovalError
    from .core.mission_engine import MissionError

    engine = _mission_engine()
    try:
        step = engine.approve_step(step_id, reason=reason)
    except (KeyError, MissionError, ApprovalError) as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(
        f"\n  [bold]Step approved:[/bold] {step.step_id[:14]}"
        f"  [{_risk_str(step.risk_level)}]"
        f"  {_approval_state_str(step.approval_state)}"
        f"\n  {step.title[:80]}"
        f"\n\n  [dim]Run it (explicitly):[/dim] opencobalt missions run-step "
        f"{step.step_id[:14]} --execute\n"
    )


@missions_app.command("run-step")
def missions_run_step(
    step_id: str = typer.Argument(..., help="Mission step id (full or prefix)"),
    runtime: str | None = typer.Option(None, "--runtime", help="Runtime adapter id"),
    execute: bool = typer.Option(
        False, "--execute", help="Actually run (default is dry-run)"
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Explicit approval for red-risk execution"
    ),
    rerun: bool = typer.Option(False, "--rerun", help="Run again if already executed"),
) -> None:
    """Run one approved mission step through the policy-gated, receipt-backed
    execution engine. Dry-run by default; red needs --execute --yes; black
    never runs."""
    from .core.approval_bridge import ApprovalError
    from .core.mission_engine import MissionError

    engine = _mission_engine()
    try:
        step, report = engine.run_step(
            step_id, runtime=runtime, execute=execute, approved=yes, rerun=rerun
        )
    except (KeyError, MissionError, ApprovalError) as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(
        f"\n  [bold]Step:[/bold] {step.step_id[:14]}"
        f"  [{_risk_str(step.risk_level)}]"
        f"  [dim]action:[/dim] {report.action}"
        f"\n  {report.reason}"
    )
    if step.receipt_id:
        console.print(f"  [dim]Receipt:[/dim] {step.receipt_id}")
    if step.execution_plan_id:
        console.print(f"  [dim]Exec plan:[/dim] {step.execution_plan_id[:14]}")
    if not execute:
        console.print(
            "\n  [dim]Dry-run only. To execute:[/dim] opencobalt missions run-step "
            f"{step.step_id[:14]} --execute"
        )
    if report.action in ("refused", "blocked") and execute:
        console.print("")
        raise typer.Exit(2)
    console.print("")


@missions_app.command("outcome")
def missions_outcome(
    mission_id: str = typer.Argument(..., help="Mission id (full or prefix)"),
    outcome: str = typer.Argument(..., help="useful / neutral / wasted / abandoned"),
    notes: str | None = typer.Option(None, "--notes", help="Optional notes"),
) -> None:
    """Record a receipt-evidenced outcome. Feeds bounded, explainable
    outcome-weighted scoring for future missions."""
    from .core.mission_engine import MissionError

    engine = _mission_engine()
    try:
        outcome_id = engine.record_outcome(mission_id, outcome, notes=notes)
    except (KeyError, MissionError, ValueError) as exc:
        err.print(f"  [red]{exc}[/red]")
        raise typer.Exit(1) from exc
    mission = engine.store.get_mission(mission_id)
    status = mission.status if mission else "?"
    console.print(
        f"\n  [bold]Outcome recorded:[/bold] {outcome_id} ({outcome})"
        f"\n  [dim]Mission status:[/dim] {_mission_status_str(status)}\n"
    )


@missions_app.command("why")
def missions_why(
    mission_id: str = typer.Argument(..., help="Mission id (full or prefix)"),
) -> None:
    """Readable provenance for one mission: goal, evidence, score, plan,
    approvals, receipts, artifacts, and outcome."""
    from .core.provenance import ProvenanceBuilder, render_trace_lines

    engine = _mission_engine()
    mission = engine.store.get_mission(mission_id)
    if mission is None:
        err.print(f"  [red]Unknown mission: {mission_id}[/red]")
        raise typer.Exit(1)

    console.print(
        f"\n  [bold]Why mission[/bold] {mission.mission_id}"
        f"\n  [dim]Goal:[/dim]    {mission.goal}"
        f"\n  [dim]Type:[/dim]    {mission.mission_type}"
        f"\n  [dim]Status:[/dim]  {_mission_status_str(mission.status)}"
        f"\n  [dim]Outcome:[/dim] {mission.outcome or 'not recorded'}"
    )
    if mission.auto_plan_id:
        console.print(
            f"\n  [dim]Auto plan:[/dim] {mission.auto_plan_id}"
            f"\n  [dim]Intent:[/dim]    {mission.auto_intent}"
            f"\n  [dim]Envelope:[/dim]  {mission.autonomy_envelope}"
            f"\n  [dim]Budget:[/dim]    {mission.cognitive_budget}"
            f"\n  [dim]Next:[/dim]      {mission.auto_next_action}"
        )
        steps = engine.store.list_steps(mission.mission_id)
        if steps:
            console.print("\n  [dim]Auto route steps:[/dim]")
            for step in steps:
                marker = step.auto_promotion_classification or "unpromoted"
                link = (
                    f" -> {step.approval_request_id[:13]}"
                    if step.approval_request_id
                    else ""
                )
                console.print(
                    f"    {step.step_id[:14]}  {step.auto_primitive}"
                    f"  {marker}{link}",
                    markup=False,
                    highlight=False,
                )

    # Score explanation for the selected track, if any.
    if mission.run_id and mission.selected_track_id:
        from .core.opportunity_store import OpportunityStore

        run = OpportunityStore(_DB_PATH).get_run(mission.run_id)
        score = run.score_for(mission.selected_track_id) if run else None
        if score:
            console.print(f"\n  [dim]Score explanation ({score.total:.3f}):[/dim]")
            for line in score.explanation[:12]:
                console.print(f"    {line}", markup=False, highlight=False)

    trace = ProvenanceBuilder(_DB_PATH).trace(mission.mission_id)
    if trace is not None:
        console.print(f"\n  [dim]Lineage ({len(trace.nodes)} node(s)):[/dim]")
        for line in render_trace_lines(trace):
            console.print(f"  {line}", markup=False, highlight=False)

    events = engine.store.list_mission_events(mission.mission_id)
    if events:
        console.print(f"\n  [dim]Mission events ({len(events)}):[/dim]")
        for event in events[-15:]:
            message = event["payload"].get("message", event["event_type"])
            console.print(
                f"    {event['created_at'][:19]}  {event['event_type']}  {message}",
                markup=False, highlight=False,
            )
    console.print("")


# --- Provenance ---


@app.command("why")
def why(
    any_id: str = typer.Argument(
        ..., help="Any known id: mission, mission step, run, goal, track, "
        "evidence, opportunity plan, approval request, step, execution plan, "
        "receipt, artifact, mission extraction, extraction verification, or outcome"
    ),
) -> None:
    """Trace the lineage of any object: what caused it, what evidence and
    score supported it, what approval applied, what execution and receipt
    came out of it, and what outcome was recorded."""
    from .core.config import get_db_path
    from .core.provenance import ProvenanceBuilder, render_trace_lines

    trace = ProvenanceBuilder(get_db_path()).trace(any_id)
    if trace is None:
        err.print(
            f"  [red]No lineage found for: {any_id}[/red]\n"
            "  [dim]Accepted: mis-/mstp-/mex-/mver-/emis-/ecand-/orun-/goal-/"
            "otrk-/ev-/oplan-/areq-/astp-/oout- ids, "
            "or execution plan / receipt / artifact ids.[/dim]"
        )
        raise typer.Exit(1)

    console.print(f"\n  [bold]Why[/bold] {trace.focus_id}  [dim]kind:[/dim] {trace.focus_kind}")
    console.print(f"  [dim]{'─' * 60}[/dim]")
    for line in render_trace_lines(trace):
        # markup=False: trace lines carry [key=value] blocks rich would
        # otherwise try to parse as style tags.
        style = "bold" if "<-- you asked about this" in line else None
        console.print(f"  {line}", markup=False, highlight=False, style=style)
    console.print(
        f"\n  [dim]{len(trace.nodes)} node(s), {len(trace.edges)} edge(s). "
        "Inspect details: opencobalt approvals show / receipts inspect.[/dim]\n"
    )
