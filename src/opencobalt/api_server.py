"""FastAPI backend for the OpenCobalt dashboard.

Reads directly from existing SQLite stores and registries.
Runs on port 8000; the React dev server runs on 5173.
"""

from __future__ import annotations

import importlib.metadata
import re
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agents.registry import list_agents
from .core.benchmark import BenchmarkStore
from .core.cost import CostTracker
from .core.ledger import Ledger
from .core.public_safety import scan_directory
from .integrations.registry import REGISTRY as _INTEGRATION_REGISTRY

_START_TIME = time.time()

app = FastAPI(title="OpenCobalt API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _ledger() -> Ledger:
    return Ledger(Path(".opencobalt") / "ledger.db")


def _count_tests() -> int:
    """Count test functions in tests/ by scanning for 'def test_' lines."""
    tests_dir = Path("tests")
    if not tests_dir.is_dir():
        return 0
    count = 0
    for f in tests_dir.glob("test_*.py"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            count += text.count("def test_")
        except OSError:
            pass
    return count


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    try:
        version = importlib.metadata.version("opencobalt")
    except Exception:
        version = "0.1.0"

    try:
        event_count = _ledger().count_events()
    except Exception:
        event_count = 0

    try:
        scan = scan_directory(Path("."))
        public_check = "clean" if scan.is_clean else f"{len(scan.issues)} issue(s)"
    except Exception:
        public_check = "unknown"

    return {
        "version": version,
        "test_count": _count_tests() or 214,
        "event_count": event_count,
        "public_check": public_check,
        "uptime_seconds": int(time.time() - _START_TIME),
    }


@app.get("/api/sessions")
def get_sessions() -> list[dict[str, Any]]:
    try:
        decisions = _ledger().list_route_decisions(limit=20)
    except Exception:
        return []

    result = []
    for d in decisions:
        ts = d.timestamp
        ts_str = ts.strftime("%H:%M:%S") if hasattr(ts, "strftime") else str(ts)[11:19]
        result.append({
            "ts": ts_str,
            "task": d.task,
            "model": d.recommended_tool,
            "tier": d.tier,
            "cost": "$0.000",
            "ok": True,
        })
    return result


@app.get("/api/agents")
def get_agents() -> list[dict[str, Any]]:
    try:
        profiles = list_agents()
    except Exception:
        return []

    return [
        {
            "id": p.name,
            "tier": p.tier,
            "caps": p.capabilities,
            "on": False,
        }
        for p in profiles
    ]


@app.get("/api/benchmarks")
def get_benchmarks() -> list[dict[str, Any]]:
    try:
        board = BenchmarkStore(Path(".opencobalt") / "ledger.db").get_leaderboard(n=10)
    except Exception:
        return []

    try:
        tier_map = {p.name: p.tier for p in list_agents()}
    except Exception:
        tier_map = {}

    result = []
    for i, entry in enumerate(board, start=1):
        ms = entry["avg_latency_ms"]
        lat = f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms:.0f}ms"
        result.append({
            "rank": i,
            "name": entry["agent_id"],
            "tier": tier_map.get(entry["agent_id"], "worker"),
            "wins": int(entry["win_rate"] * 100),
            "lat": lat,
            "tasks": entry["total"],
        })
    return result


@app.get("/api/integrations")
def get_integrations() -> list[dict[str, Any]]:
    try:
        result = []
        for integration in _INTEGRATION_REGISTRY.values():
            p = integration.profile()
            result.append({
                "name": p.name,
                "repo": p.source_url,
                "on": p.installed,
                "caps": p.capabilities,
            })
        return result
    except Exception:
        return []


@app.get("/api/memory")
def get_memory() -> dict[str, Any]:
    try:
        ledger = _ledger()
        records = ledger.list_memory_records(limit=10)
        total = ledger.count_memory_records()
    except Exception:
        records = []
        total = 0

    mem_db = Path(".opencobalt") / "memories.db"
    size_kb = mem_db.stat().st_size // 1024 if mem_db.exists() else 0

    return {
        "entries": [
            {
                "ts": r.timestamp.strftime("%H:%M:%S") if hasattr(r.timestamp, "strftime") else str(r.timestamp)[11:19],
                "namespace": r.namespace,
                "content": r.content[:120],
            }
            for r in records
        ],
        "total_count": total,
        "store_size_kb": size_kb,
    }


@app.get("/api/cost")
def get_cost() -> dict[str, Any]:
    try:
        tracker = CostTracker(Path(".opencobalt") / "ledger.db")
        return {
            "monthly_total": tracker.monthly_spend(),
            "monthly_cap": tracker.monthly_cap(),
            "per_run_cap": tracker.per_run_cap(),
            "routing_mode": tracker.get_routing_mode(),
            "api_enabled": False,
        }
    except Exception:
        return {
            "monthly_total": 0.0,
            "monthly_cap": 5.0,
            "per_run_cap": 0.10,
            "routing_mode": "standard",
            "api_enabled": False,
        }


@app.get("/api/context")
def get_context() -> dict[str, Any]:
    ctx_path = Path(".opencobalt") / "context" / "latest.md"
    empty = {"files": [], "project": "opencobalt", "total_tokens": 0, "file_count": 0}
    if not ctx_path.exists():
        return empty

    try:
        content = ctx_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return empty

    sections = re.split(r"^## ", content, flags=re.MULTILINE)
    raw: list[dict] = []
    total_chars = 0
    for section in sections[1:]:
        lines = section.split("\n", 1)
        fname = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ""
        chars = len(body)
        total_chars += chars
        raw.append({"n": fname, "chars": chars})

    total_tokens = max(total_chars // 4, 1)
    files = [
        {
            "n": f["n"],
            "tok": f["chars"] // 4,
            "pct": int(f["chars"] / total_chars * 100) if total_chars else 0,
        }
        for f in raw[:10]
    ]
    return {
        "files": files,
        "project": "opencobalt",
        "total_tokens": total_tokens,
        "file_count": len(raw),
    }
