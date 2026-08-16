"""Command-line surface for durable agent-broker sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from .broker import AgentBroker, BrokerExecution
from .models import AgentBrokerSession

app = typer.Typer(
    name="opencobalt-broker",
    help="Durable, receipt-backed external-agent session broker.",
    add_completion=False,
)


def _payload(session: AgentBrokerSession, execution: BrokerExecution | None = None) -> dict[str, Any]:
    data = session.model_dump(mode="json")
    if execution is not None:
        data["execution"] = {
            "status": execution.status,
            "executed": execution.executed,
            "receipt_id": execution.receipt_id,
            "provider_session_id": execution.provider_session_id,
            "response": execution.response,
            "error": execution.error,
            "metadata": execution.metadata,
        }
    return data


def _emit(data: Any, *, json_output: bool) -> None:
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(data, indent=2, sort_keys=True, default=str))
        return
    if isinstance(data, dict):
        for key, value in data.items():
            if value not in (None, "", [], {}):
                typer.echo(f"{key}: {value}")
    else:
        typer.echo(str(data))


@app.command("start")
def start_cmd(
    goal: str = typer.Argument(..., help="Objective for the durable Codex session."),
    repository: Path = typer.Option(Path("."), "--repo", help="Authoritative repository."),
    model: str | None = typer.Option(None, "--model"),
    execute: bool = typer.Option(False, "--execute", help="Actually run the first turn."),
    yes: bool = typer.Option(False, "--yes", help="Approve red-risk execution when policy permits."),
    timeout: int = typer.Option(1800, "--timeout", min=1, max=7200),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create a staged workspace and start a durable Codex thread."""
    broker = AgentBroker()
    try:
        session, execution = broker.start(
            repository=str(repository),
            objective=goal,
            model=model,
            execute=execute,
            approved=yes,
            timeout_seconds=timeout,
        )
    except Exception as exc:
        raise typer.Exit(code=_error(exc, json_output=json_output)) from exc
    _emit(_payload(session, execution), json_output=json_output)
    if not execute:
        typer.echo("Dry-run only. Re-run with --execute to invoke Codex.", err=True)


@app.command("continue")
def continue_cmd(
    session_id: str = typer.Argument(...),
    prompt: str = typer.Argument(...),
    execute: bool = typer.Option(False, "--execute"),
    yes: bool = typer.Option(False, "--yes"),
    timeout: int = typer.Option(1800, "--timeout", min=1, max=7200),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Resume the same provider thread and run another bounded turn."""
    broker = AgentBroker()
    try:
        session, execution = broker.continue_session(
            session_id,
            prompt,
            execute=execute,
            approved=yes,
            timeout_seconds=timeout,
        )
    except Exception as exc:
        raise typer.Exit(code=_error(exc, json_output=json_output)) from exc
    _emit(_payload(session, execution), json_output=json_output)
    if not execute:
        typer.echo("Dry-run only. Re-run with --execute to invoke Codex.", err=True)


@app.command("status")
def status_cmd(
    session_id: str | None = typer.Argument(None),
    limit: int = typer.Option(20, "--limit", min=1, max=500),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show one broker session or the most recently updated sessions."""
    broker = AgentBroker()
    try:
        if session_id:
            session = broker.require_session(session_id)
            data = _payload(session)
            data["turns"] = [turn.model_dump(mode="json") for turn in broker.turns(session_id)]
        else:
            data = [session.model_dump(mode="json") for session in broker.list_sessions(limit=limit)]
    except Exception as exc:
        raise typer.Exit(code=_error(exc, json_output=json_output)) from exc
    _emit(data, json_output=json_output)


@app.command("stop")
def stop_cmd(
    session_id: str = typer.Argument(...),
    archive_provider: bool = typer.Option(
        False,
        "--archive-provider",
        help="Also archive the persisted Codex thread through ExecutionEngine.",
    ),
    execute: bool = typer.Option(False, "--execute"),
    yes: bool = typer.Option(False, "--yes"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Stop local continuation; optionally archive the provider thread."""
    broker = AgentBroker()
    try:
        session, execution = broker.stop(
            session_id,
            archive_provider=archive_provider,
            execute=execute,
            approved=yes,
        )
    except Exception as exc:
        raise typer.Exit(code=_error(exc, json_output=json_output)) from exc
    _emit(_payload(session, execution), json_output=json_output)


def _error(exc: Exception, *, json_output: bool) -> int:
    payload = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True), err=True)
    else:
        typer.echo(f"error: {exc}", err=True)
    return 1
