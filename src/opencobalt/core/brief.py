"""Temporal context injection -- generates a session brief from ledger + memory."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .ledger import Ledger

_ARCH_DOC = Path("docs/ARCHITECTURE.md")
_MEMORIES_DB = Path(".opencobalt") / "memories.db"
_MARKER = "# OpenCobalt brief"


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_ts(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(ts))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


class BriefGenerator:
    """Generate a markdown context brief optimised for pasting into any AI tool."""

    def __init__(self, ledger: Ledger, bridge_path: Path | None = None) -> None:
        self._ledger = ledger
        self._bridge_path = bridge_path or _MEMORIES_DB

    def generate(self, days: int = 7) -> str:
        cutoff = _now_utc() - timedelta(days=days)
        sections: list[str] = [f"{_MARKER}\n"]

        # ── Recent work ───────────────────────────────────────────────────────
        decisions = self._ledger.list_route_decisions(limit=200)
        recent = [
            d for d in decisions
            if (ts := _parse_ts(d.timestamp)) and ts >= cutoff
        ]
        sections.append("## Recent Work")
        if recent:
            tool_counts: dict[str, int] = {}
            for d in recent:
                tool_counts[d.recommended_tool] = tool_counts.get(d.recommended_tool, 0) + 1
            summary = ", ".join(f"{n} tasks to {t}" for t, n in sorted(tool_counts.items(), key=lambda x: -x[1]))
            sections.append(f"_{summary}_\n")
            for d in recent[:8]:
                _ts = _parse_ts(d.timestamp)
                ts_str = _ts.strftime("%Y-%m-%d") if _ts else "?"
                sections.append(f"- {ts_str} [{d.recommended_tool}] {d.task[:70]}")
        else:
            sections.append("_No routing activity in this period._")
        sections.append("")

        # ── Notes ──────────────────────────────────────────────────────────────
        notes = self._get_recent_notes(cutoff, tag=None)
        decisions_tagged = self._get_recent_notes(cutoff, tag="decision")
        risks = self._get_recent_notes(cutoff, tag="risk")

        sections.append("## Notes")
        if notes:
            for n in notes[:6]:
                ts_str = n.get("timestamp", "")[:10]
                sections.append(f"- {ts_str}: {n.get('content', '')[:100]}")
        else:
            sections.append("_No notes in this period._")
        sections.append("")

        # ── Open decisions ────────────────────────────────────────────────────
        sections.append("## Open Decisions")
        if decisions_tagged:
            for n in decisions_tagged[:4]:
                ts_str = n.get("timestamp", "")[:10]
                sections.append(f"- {ts_str}: {n.get('content', '')[:100]}")
        else:
            sections.append("_None recorded. Tag decisions with: opencobalt note \"...\" --tags decision_")
        sections.append("")

        # ── Current risks ─────────────────────────────────────────────────────
        if risks:
            sections.append("## Current Risks")
            for n in risks[:4]:
                ts_str = n.get("timestamp", "")[:10]
                sections.append(f"- {ts_str}: {n.get('content', '')[:100]}")
            sections.append("")

        # ── Architecture snapshot ──────────────────────────────────────────────
        sections.append("## Architecture Snapshot")
        if _ARCH_DOC.exists():
            lines = _ARCH_DOC.read_text(encoding="utf-8").splitlines()[:20]
            sections.append("\n".join(lines))
        else:
            sections.append("_docs/ARCHITECTURE.md not found_")
        sections.append("")

        # ── Last session ──────────────────────────────────────────────────────
        sections.append("## Last Session")
        if decisions:
            last = decisions[0]
            _last_ts = _parse_ts(last.timestamp)
            ts_str = _last_ts.strftime("%Y-%m-%d") if _last_ts else "?"
            sections.append(f"Last session: {ts_str}, routed to {last.recommended_tool}: {last.task[:80]}")
        else:
            sections.append("_No sessions recorded yet._")
        sections.append("")

        return "\n".join(sections)

    def _get_recent_notes(self, cutoff: datetime, tag: str | None) -> list[dict]:
        try:
            import sqlite3
            if not self._bridge_path.exists():
                return []
            conn = sqlite3.connect(self._bridge_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY timestamp DESC LIMIT 500"
            ).fetchall()
            conn.close()
            result = []
            for row in rows:
                d = dict(row)
                ts = _parse_ts(d.get("timestamp"))
                if ts and ts < cutoff:
                    continue
                meta = json.loads(d.get("metadata", "{}"))
                if tag is None:
                    if meta.get("type") == "note":
                        result.append(d)
                else:
                    tags = meta.get("tags", [])
                    if isinstance(tags, list) and tag in tags:
                        result.append(d)
            return result
        except Exception:
            return []
