"""Temporal context injection -- session brief from ledger, memory, and project cwd."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .ledger import Ledger

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
            summary = ", ".join(
                f"{n} tasks to {t}"
                for t, n in sorted(tool_counts.items(), key=lambda x: -x[1])
            )
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

        sections.append("## Open Decisions")
        if decisions_tagged:
            for n in decisions_tagged[:4]:
                ts_str = n.get("timestamp", "")[:10]
                sections.append(f"- {ts_str}: {n.get('content', '')[:100]}")
        else:
            sections.append('_None recorded._')
        sections.append("")

        if risks:
            sections.append("## Current Risks")
            for n in risks[:4]:
                ts_str = n.get("timestamp", "")[:10]
                sections.append(f"- {ts_str}: {n.get('content', '')[:100]}")
            sections.append("")

        # ── Project context (replaces OpenCobalt architecture snapshot) ────────
        sections.append("## Project Context")
        sections.append(self._project_context())
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

    def generate_startup(self) -> str:
        """Return a compact brief for shell startup."""
        cwd = Path.cwd()
        cutoff = _now_utc() - timedelta(days=1)
        decisions = self._ledger.list_route_decisions(limit=100)
        recent = [
            d for d in decisions
            if (_parse_ts(d.timestamp) or _now_utc()) >= cutoff
        ]

        project_name = cwd.name
        lines = [f"BRIEF  {project_name}"]

        if recent:
            tool_counts: dict[str, int] = {}
            for d in recent:
                tool_counts[d.recommended_tool] = tool_counts.get(d.recommended_tool, 0) + 1
            summary = " · ".join(
                f"{tool} ×{count}"
                for tool, count in sorted(tool_counts.items(), key=lambda item: -item[1])
            )
            lines.append(f"→ {len(recent)} routes · {summary}")
            last = recent[0]
            lines.append(f"→ last: {last.task[:60]}")
        else:
            lines.append("→ no activity yet in this project")

        risks = self._get_recent_notes(cutoff=_now_utc() - timedelta(days=7), tag="risk")
        decisions_tagged = self._get_recent_notes(
            cutoff=_now_utc() - timedelta(days=7), tag="decision",
        )
        if risks:
            lines.append(f"! risk: {risks[0].get('content', '')[:60]}")
        if decisions_tagged:
            lines.append(f"! open: {decisions_tagged[0].get('content', '')[:60]}")
        if not risks and not decisions_tagged:
            lines.append("✓ no open risks or decisions")

        # Show stack if detectable
        stack = _detect_stack(cwd)
        if stack:
            lines.append(f"  stack: {stack}")

        return "\n".join(lines)

    def _project_context(self) -> str:
        """Build project context from cwd — stack, git, readme."""
        cwd = Path.cwd()
        parts: list[str] = [f"**{cwd.name}**"]

        stack = _detect_stack(cwd)
        if stack:
            parts.append(f"Stack: {stack}")

        branch = _git_branch(cwd)
        if branch:
            parts.append(f"Branch: {branch}")

        log = _git_log(cwd, n=6)
        if log:
            parts.append(f"\nRecent commits:\n{log}")
        else:
            parts.append("No git history yet")

        readme_excerpt = _readme_excerpt(cwd)
        if readme_excerpt:
            parts.append(f"\n{readme_excerpt}")

        return "\n".join(parts)

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


# ── Project detection helpers ──────────────────────────────────────────────────

def _detect_stack(cwd: Path) -> str:
    parts: list[str] = []

    if (cwd / "package.json").exists():
        try:
            pkg = json.loads((cwd / "package.json").read_text(encoding="utf-8"))
            deps = list(pkg.get("dependencies", {}).keys())
            fw = next(
                (d for d in deps if d in ("react", "vue", "svelte", "next", "nuxt", "astro")),
                None,
            )
            parts.append(f"Node.js{f'/{fw}' if fw else ''}")
        except Exception:
            parts.append("Node.js")

    if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
        parts.append("Python")

    if (cwd / "Cargo.toml").exists():
        parts.append("Rust")

    if (cwd / "go.mod").exists():
        parts.append("Go")

    if (cwd / "pubspec.yaml").exists():
        parts.append("Dart/Flutter")

    if (cwd / "src-tauri").exists():
        parts.append("Tauri")

    return " · ".join(parts)


def _git_branch(cwd: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _git_log(cwd: Path, n: int = 5) -> str:
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", f"-{n}"],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _readme_excerpt(cwd: Path) -> str:
    for name in ("README.md", "readme.md", "README.rst", "README"):
        p = cwd / name
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8")
                para = content.split("\n\n")[0].strip()
                return para[:200]
            except Exception:
                pass
    return ""
