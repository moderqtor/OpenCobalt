"""CLI commands for OpenCobalt Daily Operator.

Provides ergonomic commands for daily execution, capture, triage, dashboard, next action,
focus sessions, completion receipts, review protocols, search, and provenance explanations.
"""

import json
import sys
from dataclasses import asdict
from typing import Optional

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

import opencobalt.core.config as config
from opencobalt.core.daily_operator import DailyOperatorService

console = Console()
err = Console(stderr=True)

daily_app = typer.Typer(help="Daily Operator: personal execution and efficiency control plane.")


def _get_service() -> DailyOperatorService:
    return DailyOperatorService(config.get_db_path())


def _emit_json(data: dict, status: str = "success", error: Optional[dict] = None) -> None:
    payload = {
        "schema_version": "1.0",
        "status": status,
        "timestamp": _get_service().clock.now_iso(),
        "data": data if status == "success" else None,
        "error": error if status == "error" else None,
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")


# -------------------------------------------------------------------------
# Capture Command
# -------------------------------------------------------------------------
@daily_app.command("capture")
def capture_cmd(
    text: Optional[str] = typer.Argument(None, help="Raw thought or action to capture."),
    from_stdin: bool = typer.Option(False, "--stdin", help="Read capture text from stdin."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """Capture an obligation, idea, question, or action item into inbox."""
    service = _get_service()
    content = ""

    if from_stdin or text == "-":
        content = sys.stdin.read().strip()
    elif text:
        content = text.strip()

    if not content:
        err.print("[red]error:[/red] Capture text cannot be empty. Pass text as argument or use --stdin.")
        raise typer.Exit(code=2)

    cpt = service.capture(content, source="cli")
    if json_output:
        _emit_json({"capture_id": cpt.id, "raw_text": cpt.raw_text, "status": cpt.status})
    else:
        console.print(f"[green]✓ Captured[/green] [bold]{cpt.id}[/bold]: \"{cpt.raw_text}\"")


# -------------------------------------------------------------------------
# Inbox Command
# -------------------------------------------------------------------------
@daily_app.command("inbox")
def inbox_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """List pending unclarified inbox items."""
    service = _get_service()
    captures = service.get_inbox()

    if json_output:
        _emit_json({"count": len(captures), "items": [{"id": c.id, "raw_text": c.raw_text, "created_at": c.created_at} for c in captures]})
        return

    if not captures:
        console.print("[dim]No pending inbox items. Capture thoughts with: opencobalt capture \"text\"[/dim]")
        return

    table = Table(title=f"INBOX ({len(captures)} items)", box=box.SIMPLE, show_header=True)
    table.add_column("ID", style="bold cyan")
    table.add_column("Created", style="dim")
    table.add_column("Content")

    for c in captures:
        table.add_row(c.id, c.created_at[:16], c.raw_text)

    console.print(table)


# -------------------------------------------------------------------------
# Clarify Command
# -------------------------------------------------------------------------
@daily_app.command("clarify")
def clarify_cmd(
    capture_id: str = typer.Argument(..., help="ID of capture item to clarify (cpt-...)."),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Refined action title."),
    impact: int = typer.Option(3, "--impact", "-i", help="Impact rating (1-5)."),
    minutes: int = typer.Option(30, "--minutes", "-m", help="Estimated duration in minutes."),
    due: Optional[str] = typer.Option(None, "--due", "-d", help="Due date (ISO format YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)."),
    discard: bool = typer.Option(False, "--discard", help="Discard item without converting to commitment."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """Clarify an inbox capture item into an action-ready commitment."""
    service = _get_service()
    try:
        cmt = service.clarify_capture(
            capture_id=capture_id,
            title=title,
            actionable=not discard,
            impact_level=impact,
            estimated_minutes=minutes,
            due_at=due,
        )
    except ValueError as e:
        err.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=1)

    if discard:
        if json_output:
            _emit_json({"capture_id": capture_id, "status": "discarded"})
        else:
            console.print(f"[yellow]Discarded capture[/yellow] {capture_id}")
        return

    if json_output:
        _emit_json({"commitment_id": cmt.id, "title": cmt.title, "status": cmt.status, "impact": cmt.impact_level, "due_at": cmt.due_at})
    else:
        console.print(f"[green]✓ Clarified[/green] {capture_id} -> Commitment [bold]{cmt.id}[/bold]: \"{cmt.title}\" (impact: {cmt.impact_level}, est: {cmt.estimated_minutes}m)")


# -------------------------------------------------------------------------
# Today Command
# -------------------------------------------------------------------------
@daily_app.command("today")
def today_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """Show operational daily view (active focus, next action, agenda, blockers, inbox)."""
    service = _get_service()
    data = service.get_today_dashboard()

    if json_output:
        _emit_json(data)
        return

    console.print(f"[bold #3B7CF4]OPENCOBALT DAILY OPERATOR[/bold #3B7CF4] · {data['date_stamp']}\n")

    # NOW Section
    if data["now_focus"]:
        nf = data["now_focus"]
        title_str = nf["commitment_title"] or nf["notes"] or "Focus Session"
        console.print(Panel(f"[bold green]● NOW ACTIVE FOCUS[/bold green]\nSession ID : {nf['session_id']}\nTarget     : [bold]{title_str}[/bold]\nStarted At : {nf['start_time'][:16]}", box=box.ROUNDED))
    else:
        console.print("[dim]NOW FOCUS: No active focus session running. Use `opencobalt focus <id>` to start.[/dim]\n")

    # NEXT Section
    if data["next_action"]:
        na = data["next_action"]["commitment"]
        score = data["next_action"]["priority_score"]
        console.print(f"[bold yellow]▶ RECOMMENDATION NEXT ACTION[/bold yellow] (Score: {score})")
        console.print(f"  ID        : [bold cyan]{na['id']}[/bold cyan]")
        console.print(f"  Action    : [bold]{na['title']}[/bold]")
        console.print(f"  Est Time  : {na['estimated_minutes']} mins | Impact: Level {na['impact_level']}")
        if na.get("due_at"):
            console.print(f"  Due At    : [red]{na['due_at'][:16]}[/red]")
        console.print(f"  Start with: [dim]opencobalt focus {na['id']}[/dim]\n")

    # LATER TODAY Section
    if data["later_today"]:
        table = Table(title="LATER TODAY", box=box.SIMPLE, show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Score", justify="right")
        table.add_column("Title")
        table.add_column("Est Mins", justify="right")
        for item in data["later_today"]:
            c = item["commitment"]
            table.add_row(c["id"], str(item["priority_score"]), c["title"], f"{c['estimated_minutes']}m")
        console.print(table)

    # WAITING / OVERDUE Summary
    summary_parts = []
    if data["overdue_count"] > 0:
        summary_parts.append(f"[bold red]{data['overdue_count']} OVERDUE[/bold red]")
    if data["waiting_count"] > 0:
        summary_parts.append(f"[yellow]{data['waiting_count']} waiting[/yellow]")
    if data["inbox_count"] > 0:
        summary_parts.append(f"[cyan]{data['inbox_count']} in inbox[/cyan]")

    if summary_parts:
        console.print("\n[dim]Queue status:[/dim] " + " · ".join(summary_parts))


# -------------------------------------------------------------------------
# Next Command
# -------------------------------------------------------------------------
@daily_app.command("next")
def next_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """Recommend single concrete next action with priority explanation."""
    service = _get_service()
    rec = service.get_next_recommendation()

    if json_output:
        _emit_json(rec or {})
        return

    if not rec:
        console.print("[dim]No ready actions found. Capture a thought or check `opencobalt inbox`.[/dim]")
        return

    cmt = rec["commitment"]
    exp = rec["explanation"]
    console.print(f"[bold yellow]RECOMMENDED NEXT ACTION[/bold yellow] (Priority Score: [bold]{rec['score']}[/bold])")
    console.print(f"  ID        : [bold cyan]{cmt['id']}[/bold cyan]")
    console.print(f"  Action    : [bold]{cmt['title']}[/bold]")
    console.print(f"  Est Time  : {cmt['estimated_minutes']} minutes | Impact Level: {cmt['impact_level']}")
    if cmt.get("due_at"):
        console.print(f"  Due At    : [red]{cmt['due_at'][:16]}[/red]")

    console.print("\n  [bold]Priority Rationale:[/bold]")
    for r in exp.get("rationale", []):
        console.print(f"    • {r}")

    if rec.get("why_outranked"):
        console.print("\n  [dim]Why it outranks alternatives:[/dim]")
        for w in rec["why_outranked"]:
            console.print(f"    - {w}")

    console.print(f"\n  To begin focus: [bold green]opencobalt focus {cmt['id']}[/bold green]")


# -------------------------------------------------------------------------
# Focus Command
# -------------------------------------------------------------------------
@daily_app.command("focus")
def focus_cmd(
    target_id: Optional[str] = typer.Argument(None, help="Commitment ID to focus on (cmt-...)."),
    stop: bool = typer.Option(False, "--stop", help="Stop current focus session."),
    interrupt: bool = typer.Option(False, "--interrupt", help="Interrupt current focus session."),
    notes: str = typer.Option("", "--notes", "-n", help="Notes or rationale for session."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """Start, inspect, or stop a focus session on an active commitment."""
    service = _get_service()

    if stop or interrupt:
        outcome = "interrupted" if interrupt else "completed"
        sess = service.focus_stop(outcome=outcome, notes=notes)
        if json_output:
            _emit_json({"status": "stopped", "session": asdict(sess) if sess else None})
        else:
            if sess:
                console.print(f"[yellow]Stopped focus session[/yellow] {sess.id} (outcome: {outcome}, duration: {sess.duration_minutes}m)")
            else:
                console.print("[dim]No active focus session to stop.[/dim]")
        return

    if target_id:
        sess = service.focus_start(commitment_id=target_id, notes=notes)
        if json_output:
            _emit_json({"status": "started", "session": asdict(sess)})
        else:
            console.print(f"[bold green]● Focus Started[/bold green] [bold cyan]{sess.id}[/bold cyan] on commitment [bold]{target_id}[/bold]")
        return

    # Inspect current status
    status = service.focus_status()
    if json_output:
        _emit_json(status or {})
        return

    if not status:
        console.print("[dim]No active focus session. Start one with: opencobalt focus <cmt-id>[/dim]")
        return

    sess = status["session"]
    cmt = status["commitment"]
    title_str = cmt["title"] if cmt else "General focus"
    console.print("[bold green]● ACTIVE FOCUS SESSION[/bold green]")
    console.print(f"  Session ID : [cyan]{sess['id']}[/cyan]")
    console.print(f"  Target     : [bold]{title_str}[/bold]")
    console.print(f"  Elapsed    : [bold]{status['elapsed_minutes']}[/bold] minutes")
    if sess.get("notes"):
        console.print(f"  Notes      : {sess['notes']}")


# -------------------------------------------------------------------------
# Done Command
# -------------------------------------------------------------------------
@daily_app.command("done")
def done_cmd(
    commitment_id: str = typer.Argument(..., help="ID of commitment to complete (cmt-...)."),
    summary: str = typer.Option("", "--summary", "-s", help="Outcome summary statement."),
    evidence: Optional[str] = typer.Option(None, "--evidence", "-e", help="File path to outcome evidence."),
    follow_up: Optional[str] = typer.Option(None, "--follow-up", "-f", help="Create follow-up commitment title."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """Mark a commitment complete and record a receipt/outcome in SQLite ledger."""
    service = _get_service()
    try:
        res = service.done(
            commitment_id=commitment_id,
            outcome_summary=summary,
            evidence_path=evidence,
            follow_up_title=follow_up,
        )
    except ValueError as e:
        err.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=1)

    if json_output:
        _emit_json(res)
    else:
        console.print(f"[bold green]✓ Completed[/bold green] [cyan]{commitment_id}[/cyan]: \"{res['commitment']['title']}\"")
        if res.get("follow_up"):
            console.print(f"  [dim]Follow-up created:[/dim] {res['follow_up']['id']} \"{res['follow_up']['title']}\"")


# -------------------------------------------------------------------------
# Defer & Waiting Commands
# -------------------------------------------------------------------------
@daily_app.command("defer")
def defer_cmd(
    commitment_id: str = typer.Argument(..., help="Commitment ID to postpone."),
    until: str = typer.Option(..., "--until", "-u", help="Postpone until date/time (ISO format)."),
    reason: str = typer.Option("", "--reason", "-r", help="Reason for deferral."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """Postpone a commitment until a specified time."""
    service = _get_service()
    try:
        cmt = service.defer(commitment_id=commitment_id, until_iso=until, reason=reason)
    except ValueError as e:
        err.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=1)

    if json_output:
        _emit_json({"commitment_id": cmt.id, "status": cmt.status, "deferred_until": cmt.deferred_until})
    else:
        console.print(f"[yellow][-] Deferred[/yellow] {cmt.id} until {until}")


@daily_app.command("waiting")
def waiting_cmd(
    commitment_id: str = typer.Argument(..., help="Commitment ID waiting on external dependency."),
    for_ref: str = typer.Option(..., "--for", "-f", help="Person, agent, or dependency waiting on."),
    reason: str = typer.Option("", "--reason", "-r", help="Context or rationale."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """Mark a commitment as waiting on external input or approval."""
    service = _get_service()
    try:
        cmt = service.waiting(commitment_id=commitment_id, for_ref=for_ref, reason=reason)
    except ValueError as e:
        err.print(f"[red]error:[/red] {e}")
        raise typer.Exit(code=1)

    if json_output:
        _emit_json({"commitment_id": cmt.id, "status": cmt.status, "waiting_on": cmt.waiting_on_ref})
    else:
        console.print(f"[yellow][!] Waiting[/yellow] {cmt.id} on \"{for_ref}\"")


# -------------------------------------------------------------------------
# Review Command
# -------------------------------------------------------------------------
@daily_app.command("review")
def review_cmd(
    date_stamp: Optional[str] = typer.Option(None, "--date", "-d", help="Review date YYYY-MM-DD."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """Run daily review protocol and generate durable scorecard record."""
    service = _get_service()
    data = service.review_day(date_stamp=date_stamp)

    if json_output:
        _emit_json(data)
        return

    sc = data["scorecard"]
    console.print(f"[bold #3B7CF4]DAILY REVIEW PROTOCOL[/bold #3B7CF4] · {sc['date']}\n")
    console.print(f"  Completed Items : [green]{sc['completed_count']}[/green]")
    console.print(f"  Deferred Items  : [yellow]{sc['deferred_count']}[/yellow]")
    console.print(f"  Waiting Items   : [yellow]{sc['waiting_count']}[/yellow]")
    console.print(f"  Inbox Count     : [cyan]{sc['inbox_count']}[/cyan]")

    if data["completed_items"]:
        console.print("\n  [bold green]Completed Today:[/bold green]")
        for c in data["completed_items"]:
            console.print(f"    ✓ {c['id']} {c['title']}")

    console.print("\n[dim]Daily review recorded to ledger.[/dim]")


# -------------------------------------------------------------------------
# Search & Why Commands
# -------------------------------------------------------------------------
@daily_app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Search term across captures, commitments, and ledger."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output machine-readable JSON."),
):
    """Unified search across daily captures, commitments, and records."""
    service = _get_service()
    res = service.search(query)

    if json_output:
        _emit_json(res)
        return

    console.print(f"[bold]Search results for:[/bold] \"{query}\"\n")
    if res["captures"]:
        console.print(f"  [bold cyan]Captures ({len(res['captures'])}):[/bold cyan]")
        for c in res["captures"]:
            console.print(f"    • {c['id']}: {c['raw_text']}")

    if res["commitments"]:
        console.print(f"\n  [bold cyan]Commitments ({len(res['commitments'])}):[/bold cyan]")
        for c in res["commitments"]:
            console.print(f"    • {c['id']} [{c['status']}]: {c['title']}")

    if not res["captures"] and not res["commitments"]:
        console.print("[dim]No matching daily records found.[/dim]")
