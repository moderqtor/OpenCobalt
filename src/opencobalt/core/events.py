"""Append-only local event spine.

Adapted from Cobalt Forge automation/lib/events.py.
Outputs JSONL event records. No external dependencies.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any


_EVENT_VERSION = 1


def make_event(
    *,
    event_type: str,
    subject_type: str,
    subject_id: str,
    message: str,
    project: str = "opencobalt",
    source: str = "cli",
    tool: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured event dict. Does not write to disk."""
    stamp = dt.datetime.now(tz=dt.timezone.utc)
    uid = f"evt-{stamp.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:12]}"
    return {
        "version": _EVENT_VERSION,
        "id": uid,
        "timestamp": stamp.isoformat(),
        "project": project,
        "source": source,
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "message": message,
        "tool": tool,
        "metadata": metadata or {},
    }


def append_event(event: dict[str, Any], *, path: Path) -> None:
    """Append a single event to a JSONL file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def read_events(*, path: Path, limit: int = 100) -> list[dict[str, Any]]:
    """Read up to `limit` events from a JSONL file (most recent last)."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    parsed = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return parsed[-limit:]
