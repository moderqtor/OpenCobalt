"""Small Codex SDK worker invoked only through ExecutionEngine.

This module intentionally owns no OpenCobalt session state. It receives one
bounded turn/archive request, uses the official high-level Codex Python SDK, and
emits one JSON result for the broker to persist.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from typing import Any

_BOUNDARY = """You are a coding worker operating inside an OpenCobalt staged workspace.
The staged workspace is not authoritative state. Work only inside the supplied
workspace. Do not push, merge, deploy, publish, spend money, send external
messages, access secrets or credentials, change authentication state, or expand
scope beyond the user's coding objective. Do not request sandbox escalation.
Make useful in-scope local changes and run non-destructive local verification
when appropriate. OpenCobalt, not this worker, owns promotion and authority.
"""


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


def _load_sdk():
    try:
        from openai_codex import ApprovalMode, Codex, Sandbox
    except ImportError as exc:  # pragma: no cover - exercised by adapter discovery
        raise RuntimeError(
            "openai-codex is not installed; install OpenCobalt's codex optional dependency"
        ) from exc
    return Codex, ApprovalMode, Sandbox


def _install_decline_handler(codex: Any) -> None:
    """Fail closed on any SDK server request for additional authority.

    ``ApprovalMode.deny_all`` maps turns to an approval policy of ``never``.
    This explicit handler is defense in depth for current SDK versions whose
    low-level default request handler may otherwise accept command/file approval
    requests. We deliberately fail if the high-level client no longer exposes
    the expected handler slot rather than silently losing this boundary.
    """
    client = getattr(codex, "_client", None)
    if client is None or not hasattr(client, "_approval_handler"):
        raise RuntimeError("Codex SDK approval boundary could not be installed")

    def decline(_method: str, _params: Any) -> dict[str, str]:
        return {"decision": "decline"}

    client._approval_handler = decline


def _turn(*, prompt: str, thread_id: str | None, model: str | None) -> dict[str, Any]:
    Codex, ApprovalMode, Sandbox = _load_sdk()
    cwd = os.getcwd()
    with Codex() as codex:
        _install_decline_handler(codex)
        if thread_id:
            thread = codex.thread_resume(
                thread_id,
                approval_mode=ApprovalMode.deny_all,
                cwd=cwd,
                developer_instructions=_BOUNDARY,
                model=model,
                sandbox=Sandbox.workspace_write,
            )
        else:
            thread = codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                cwd=cwd,
                developer_instructions=_BOUNDARY,
                model=model,
                sandbox=Sandbox.workspace_write,
            )
        result = thread.run(
            prompt,
            approval_mode=ApprovalMode.deny_all,
            cwd=cwd,
            model=model,
            sandbox=Sandbox.workspace_write,
        )
        return {
            "ok": True,
            "action": "turn",
            "thread_id": thread.id,
            "final_response": str(getattr(result, "final_response", "") or ""),
            "usage": _jsonable(getattr(result, "usage", None)),
            "item_count": len(getattr(result, "items", []) or []),
            "cwd": cwd,
        }


def _archive(*, thread_id: str) -> dict[str, Any]:
    Codex, _ApprovalMode, _Sandbox = _load_sdk()
    with Codex() as codex:
        _install_decline_handler(codex)
        response = codex.thread_archive(thread_id)
    return {
        "ok": True,
        "action": "archive",
        "thread_id": thread_id,
        "archive": _jsonable(response),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opencobalt.agent_broker.worker")
    subparsers = parser.add_subparsers(dest="action", required=True)

    turn = subparsers.add_parser("turn")
    turn.add_argument("--prompt", required=True)
    turn.add_argument("--thread-id")
    turn.add_argument("--model")

    archive = subparsers.add_parser("archive")
    archive.add_argument("--thread-id", required=True)
    archive.add_argument("--model")

    args = parser.parse_args(argv)
    try:
        if args.action == "turn":
            payload = _turn(prompt=args.prompt, thread_id=args.thread_id, model=args.model)
        else:
            payload = _archive(thread_id=args.thread_id)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "action": args.action,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
