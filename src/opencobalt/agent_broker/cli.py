"""Command-line surface for durable agent-broker sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from .broker import AgentBroker, BrokerExecution
from .models import AgentBrokerSession
from .relay import GitHubAgentRelay, command_comment

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


@app.command("relay")
def relay_cmd(
    github_repo: str = typer.Option(..., "--github-repo", help="GitHub owner/name relay repository."),
    issue: int = typer.Option(..., "--issue", min=1, help="Issue or PR number used as the relay channel."),
    author: str = typer.Option(..., "--author", help="Only this GitHub login may issue commands."),
    local_repo: Path = typer.Option(Path("."), "--local-repo", help="Authoritative local repository bound to start commands."),
    execute_agent: bool = typer.Option(False, "--execute-agent", help="Allow accepted start/continue commands to invoke Codex."),
    allow_github_comments: bool = typer.Option(
        False,
        "--allow-github-comments",
        help="Explicitly allow relay result comments through existing gh authentication.",
    ),
    model: str | None = typer.Option(None, "--model"),
    interval: float = typer.Option(5.0, "--interval", min=1.0, max=300.0),
    once: bool = typer.Option(False, "--once", help="Process one poll cycle and exit."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Bridge allowlisted GitHub comments to local durable Codex sessions."""
    if not allow_github_comments:
        raise typer.BadParameter(
            "relay requires --allow-github-comments because command results are written to GitHub"
        )
    try:
        relay = GitHubAgentRelay(
            repository=github_repo,
            issue_number=issue,
            allowed_author=author,
            local_repository=str(local_repo),
            execute_agent=execute_agent,
            allow_comment_writes=allow_github_comments,
            model=model,
        )
        relay.github.check_auth()
        if once:
            _emit(relay.run_once(), json_output=json_output)
            return
        typer.echo(
            f"Relay active: {github_repo}#{issue} · author {author} · "
            f"agent execution {'enabled' if execute_agent else 'dry-run'}"
        )
        typer.echo(
            "Accepted commands can modify only staged workspaces. Results are posted to the configured GitHub thread. Ctrl+C stops the relay."
        )
        relay.run_forever(interval_seconds=interval)
    except KeyboardInterrupt:
        typer.echo("Relay stopped.")
    except Exception as exc:
        raise typer.Exit(code=_error(exc, json_output=json_output)) from exc


@app.command("command")
def command_cmd(
    action: str = typer.Argument(..., help="start, continue, status, or stop"),
    prompt: str | None = typer.Option(None, "--prompt"),
    session_id: str | None = typer.Option(None, "--session"),
) -> None:
    """Render a relay command comment for inspection or manual use."""
    if action not in {"start", "continue", "status", "stop"}:
        raise typer.BadParameter("action must be start, continue, status, or stop")
    try:
        body = command_comment(
            action=action,  # type: ignore[arg-type]
            prompt=prompt,
            session_id=session_id,
        )
    except Exception as exc:
        raise typer.Exit(code=_error(exc, json_output=False)) from exc
    typer.echo(body)


def _error(exc: Exception, *, json_output: bool) -> int:
    payload = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True), err=True)
    else:
        typer.echo(f"error: {exc}", err=True)
    return 1
