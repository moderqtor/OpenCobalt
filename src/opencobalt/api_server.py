"""FastAPI backend for the OpenCobalt dashboard.

Reads directly from existing SQLite stores and registries.
Runs on port 8000; the React dev server runs on 5173.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agents.registry import list_agents
from .core.benchmark import BenchmarkStore
from .core.cost import CostTracker
from .core.ledger import Ledger
from .core.public_safety import scan_directory
from .core.router import route_task
from .integrations.registry import REGISTRY as _INTEGRATION_REGISTRY
from .personal_ai.api import router as personal_ai_router

_START_TIME = time.time()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield
    try:
        from opencobalt.personal_ai.api import _CONTEXT_LOCK, _CONTEXTS

        with _CONTEXT_LOCK:
            contexts = [item[1] for item in _CONTEXTS.values()]
        for context in contexts:
            cancel_all = getattr(context.service, "cancel_all", None)
            if callable(cancel_all):
                cancel_all()
    except Exception:
        pass


app = FastAPI(title="OpenCobalt API", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(personal_ai_router)


def _ledger() -> Ledger:
    return Ledger(Path(".opencobalt") / "ledger.db")


def _count_tests() -> int | None:
    """Count test functions in tests/ by scanning for 'def test_' lines."""
    tests_dir = Path("tests")
    if not tests_dir.is_dir():
        return None
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
        "test_count": (test_count := _count_tests()),
        "test_count_evidence": (
            "source_definition_scan" if test_count is not None else "tests_directory_unavailable"
        ),
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
            "cost": None,
            "ok": None,
            "evidence": "route_decision_only",
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
            "on": None,
            "availability": "unknown",
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


@app.get("/api/timeline")
def get_timeline() -> list[dict[str, Any]]:
    """Return last 50 events merged across route_decisions, events, and benchmark_records."""
    events: list[dict[str, Any]] = []

    try:
        ledger = _ledger()
        for d in ledger.list_route_decisions(limit=50):
            ts = d.timestamp
            ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            events.append({
                "id": d.id,
                "timestamp": ts_iso,
                "type": "route",
                "title": d.task[:60],
                "detail": d.reasoning,
                "model": d.recommended_tool,
                "tier": d.tier,
                "scores": d.scores or d.metadata.get("_scores", {}),
                "cost": None,
                "status": "recorded",
                "evidence": "route_decision_only",
            })
    except Exception:
        pass

    try:
        ledger = _ledger()
        for e in ledger.list_events(limit=50):
            ts = e.timestamp
            ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            events.append({
                "id": e.id,
                "timestamp": ts_iso,
                "type": "note" if e.event_type == "manual_log" else e.event_type,
                "title": e.summary[:60],
                "detail": e.summary,
                "model": e.source,
                "tier": "",
                "cost": None,
                "status": "recorded",
                "evidence": "ledger_event",
            })
    except Exception:
        pass

    try:
        from .core.benchmark import BenchmarkStore
        for rec in BenchmarkStore(Path(".opencobalt") / "ledger.db").list_recent(limit=50):
            events.append({
                "id": rec.get("id", ""),
                "timestamp": rec.get("timestamp", ""),
                "type": "benchmark",
                "title": f"{rec.get('agent_id', '')} benchmark",
                "detail": f"task_type={rec.get('task_type', '')} latency={rec.get('latency_ms', 0)}ms",
                "model": rec.get("agent_id", ""),
                "tier": rec.get("tier", ""),
                "cost": "$0.000",
                "status": "ok" if rec.get("success") else "fail",
            })
    except Exception:
        pass

    events.sort(key=lambda x: x["timestamp"], reverse=True)
    return events[:50]


@app.get("/api/telemetry")
def get_telemetry() -> dict[str, Any]:
    """Return Phase 15 scoring aggregates for the dashboard."""
    try:
        from .core.telemetry import TelemetryStore

        store = TelemetryStore(Path(".opencobalt") / "telemetry.db")
        runs = store.list_runs(limit=1000)
        scored_rows = []
        for run in runs:
            score = store.get_score(run["id"])
            if score is None:
                continue
            tool_calls = json.loads(run.get("tool_calls_json") or "[]")
            scored_rows.append({
                "id": run["id"][:8],
                "run_type": run["run_type"],
                "agent": run["agent_id"],
                "prompt": run["seed_prompt"],
                "overall": score["overall"],
                "judge": score["judge"],
                "summary": run.get("summary") or "",
                "tool_count": len(tool_calls),
                "latency_ms": run.get("latency_ms") or 0,
                "scores": {
                    "quality": score.get("output_quality"),
                    "adherence": score.get("prompt_adherence"),
                    "efficiency": score.get("token_efficiency"),
                    "tools": score.get("tool_appropriateness"),
                    "convergence": score.get("convergence_quality"),
                },
            })

        board = store.get_leaderboard()
        average = round(sum(row["overall"] for row in scored_rows) / len(scored_rows)) if scored_rows else 0
        return {
            "total_runs": len(runs),
            "scored_runs": len(scored_rows),
            "average_overall": average,
            "top_agent": board[0]["agent_id"] if board else None,
            "leaderboard": board,
            "recent": scored_rows[:12],
        }
    except Exception:
        return {
            "total_runs": 0,
            "scored_runs": 0,
            "average_overall": 0,
            "top_agent": None,
            "leaderboard": [],
            "recent": [],
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


@app.get("/api/receipts")
def get_receipts() -> list[dict[str, Any]]:
    try:
        results = _ledger().list_verification_results(limit=20)
    except Exception:
        return []

    out = []
    for r in results:
        ts = r.timestamp
        ts_str = ts.strftime("%H:%M") if hasattr(ts, "strftime") else str(ts)[11:16]
        out.append({
            "id": r.id[:6].upper(),
            "ok": r.passed,
            "desc": r.command,
            "ts": ts_str,
            "exit_code": r.exit_code,
            "detail": r.output_summary,
        })
    return out


class _RouteRequest(BaseModel):
    task: str


@app.post("/api/route")
def post_route(req: _RouteRequest) -> dict[str, Any]:
    decision = route_task(req.task)
    try:
        _ledger().insert_route_decision(decision)
    except Exception:
        pass
    return {
        "tool": decision.recommended_tool,
        "tier": decision.tier,
        "score": decision.score,
        "reasoning": decision.reasoning,
        "scores": decision.scores,
    }
