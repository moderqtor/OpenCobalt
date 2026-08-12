"""Tests for the OpenCobalt FastAPI server.

Each test uses monkeypatch.chdir(tmp_path) so all SQLite stores land in a
throwaway directory and do not touch the real .opencobalt/ledger.db.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed; pip install 'opencobalt[server]'")

from fastapi.testclient import TestClient  # noqa: E402

from opencobalt.api_server import app  # noqa: E402
from opencobalt.integrations import REGISTRY as INTEGRATION_REGISTRY  # noqa: E402

client = TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(path: str, tmp_path, monkeypatch) -> dict:
    monkeypatch.chdir(tmp_path)
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} returned {resp.status_code}: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# /api/status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/status").status_code == 200

    def test_has_required_keys(self, tmp_path, monkeypatch):
        data = _get("/api/status", tmp_path, monkeypatch)
        for key in ("version", "test_count", "event_count", "public_check", "uptime_seconds"):
            assert key in data, f"missing key: {key}"

    def test_version_is_string(self, tmp_path, monkeypatch):
        data = _get("/api/status", tmp_path, monkeypatch)
        assert isinstance(data["version"], str)

    def test_public_check_is_string(self, tmp_path, monkeypatch):
        data = _get("/api/status", tmp_path, monkeypatch)
        assert isinstance(data["public_check"], str)

    def test_uptime_is_int(self, tmp_path, monkeypatch):
        data = _get("/api/status", tmp_path, monkeypatch)
        assert isinstance(data["uptime_seconds"], int)

    def test_missing_test_tree_is_reported_as_unknown_not_a_fabricated_count(
        self, tmp_path, monkeypatch
    ):
        data = _get("/api/status", tmp_path, monkeypatch)
        assert data["test_count"] is None
        assert data["test_count_evidence"] == "tests_directory_unavailable"


# ---------------------------------------------------------------------------
# /api/sessions
# ---------------------------------------------------------------------------

class TestSessions:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/sessions").status_code == 200

    def test_empty_when_no_ledger(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = client.get("/api/sessions").json()
        assert data == []

    def test_returns_list(self, tmp_path, monkeypatch):
        data = _get("/api/sessions", tmp_path, monkeypatch)
        assert isinstance(data, list)

    def test_entry_shape_when_populated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.core.ledger import Ledger
        from opencobalt.core.router import route_task
        ledger = Ledger(tmp_path / ".opencobalt" / "ledger.db")
        ledger.insert_route_decision(route_task("design the auth module", record=False))

        data = client.get("/api/sessions").json()
        assert len(data) == 1
        entry = data[0]
        for key in ("ts", "task", "model", "tier", "cost", "ok"):
            assert key in entry, f"missing key: {key}"
        assert entry["cost"] is None
        assert entry["ok"] is None
        assert entry["evidence"] == "route_decision_only"


# ---------------------------------------------------------------------------
# /api/agents
# ---------------------------------------------------------------------------

class TestAgents:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/agents").status_code == 200

    def test_returns_list(self, tmp_path, monkeypatch):
        data = _get("/api/agents", tmp_path, monkeypatch)
        assert isinstance(data, list)

    def test_has_four_agents(self, tmp_path, monkeypatch):
        data = _get("/api/agents", tmp_path, monkeypatch)
        assert len(data) == 4

    def test_entry_shape(self, tmp_path, monkeypatch):
        data = _get("/api/agents", tmp_path, monkeypatch)
        for entry in data:
            for key in ("id", "tier", "caps", "on"):
                assert key in entry, f"missing key: {key}"
            assert isinstance(entry["caps"], list)
            assert entry["on"] is None
            assert entry["availability"] == "unknown"


# ---------------------------------------------------------------------------
# /api/benchmarks
# ---------------------------------------------------------------------------

class TestBenchmarks:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/benchmarks").status_code == 200

    def test_empty_when_no_records(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = client.get("/api/benchmarks").json()
        assert data == []

    def test_entry_shape_when_populated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.core.benchmark import BenchmarkRecord, BenchmarkStore
        store = BenchmarkStore(tmp_path / ".opencobalt" / "ledger.db")
        store.record(BenchmarkRecord(
            agent_id="summarizer", task_id="t1", task_type="summarize",
            latency_ms=500, success=True, model_used="ollama", tier="worker", score=0.9,
        ))

        data = client.get("/api/benchmarks").json()
        assert len(data) == 1
        entry = data[0]
        for key in ("rank", "name", "tier", "wins", "lat", "tasks"):
            assert key in entry, f"missing key: {key}"
        assert isinstance(entry["rank"], int)
        assert isinstance(entry["wins"], int)


# ---------------------------------------------------------------------------
# /api/integrations
# ---------------------------------------------------------------------------

class TestIntegrations:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/integrations").status_code == 200

    def test_returns_list(self, tmp_path, monkeypatch):
        data = _get("/api/integrations", tmp_path, monkeypatch)
        assert isinstance(data, list)

    def test_lists_canonical_integrations(self, tmp_path, monkeypatch):
        data = _get("/api/integrations", tmp_path, monkeypatch)
        assert len(data) == len(INTEGRATION_REGISTRY)
        names = {entry["name"] for entry in data}
        assert "google-antigravity" in names
        assert "gemini-cli" not in names
        assert "antigravity-cli" not in names

    def test_entry_shape(self, tmp_path, monkeypatch):
        data = _get("/api/integrations", tmp_path, monkeypatch)
        for entry in data:
            for key in ("name", "repo", "on", "caps"):
                assert key in entry, f"missing key: {key}"
            assert isinstance(entry["on"], bool)
            assert isinstance(entry["caps"], list)


# ---------------------------------------------------------------------------
# /api/memory
# ---------------------------------------------------------------------------

class TestMemory:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/memory").status_code == 200

    def test_empty_when_no_records(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = client.get("/api/memory").json()
        assert data["entries"] == []
        assert data["total_count"] == 0

    def test_has_required_keys(self, tmp_path, monkeypatch):
        data = _get("/api/memory", tmp_path, monkeypatch)
        for key in ("entries", "total_count", "store_size_kb"):
            assert key in data, f"missing key: {key}"


# ---------------------------------------------------------------------------
# /api/cost
# ---------------------------------------------------------------------------

class TestCost:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/cost").status_code == 200

    def test_has_required_keys(self, tmp_path, monkeypatch):
        data = _get("/api/cost", tmp_path, monkeypatch)
        for key in ("monthly_total", "monthly_cap", "per_run_cap", "routing_mode", "api_enabled"):
            assert key in data, f"missing key: {key}"

    def test_api_enabled_false(self, tmp_path, monkeypatch):
        data = _get("/api/cost", tmp_path, monkeypatch)
        assert data["api_enabled"] is False

    def test_routing_mode_is_string(self, tmp_path, monkeypatch):
        data = _get("/api/cost", tmp_path, monkeypatch)
        assert isinstance(data["routing_mode"], str)


# ---------------------------------------------------------------------------
# /api/context
# ---------------------------------------------------------------------------

class TestContext:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/context").status_code == 200

    def test_empty_when_no_context_pack(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = client.get("/api/context").json()
        assert data["files"] == []
        assert data["file_count"] == 0

    def test_parses_context_pack(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ctx_dir = tmp_path / ".opencobalt" / "context"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / "latest.md").write_text(
            "# OpenCobalt Context Pack\n\n"
            "## core/router.py\n\n```\nsome code here\n```\n\n"
            "## core/ledger.py\n\n```\nmore code\n```\n",
            encoding="utf-8",
        )
        data = client.get("/api/context").json()
        assert data["file_count"] == 2
        assert len(data["files"]) == 2
        assert data["files"][0]["n"] == "core/router.py"
        for f in data["files"]:
            for key in ("n", "tok", "pct"):
                assert key in f, f"missing key: {key}"


# ---------------------------------------------------------------------------
# /api/timeline
# ---------------------------------------------------------------------------

class TestTimeline:
    def test_timeline_endpoint_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/timeline").status_code == 200

    def test_timeline_returns_list(self, tmp_path, monkeypatch):
        data = _get("/api/timeline", tmp_path, monkeypatch)
        assert isinstance(data, list)

    def test_timeline_empty_when_no_data(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = client.get("/api/timeline").json()
        assert data == []

    def test_timeline_merges_event_types(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.core.ledger import Ledger
        from opencobalt.core.models import SessionEvent
        from opencobalt.core.router import route_task

        ledger = Ledger(tmp_path / ".opencobalt" / "ledger.db")
        # Insert a route decision
        ledger.insert_route_decision(route_task("design the auth module", record=False))
        # Insert a session event
        ledger.insert_event(SessionEvent(
            project="test",
            source="cli",
            event_type="manual_log",
            summary="reviewed the module",
        ))

        data = client.get("/api/timeline").json()
        assert len(data) >= 2
        types = {e["type"] for e in data}
        assert "route" in types
        assert "note" in types or "manual_log" in types

    def test_timeline_entry_has_required_keys(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.core.ledger import Ledger
        from opencobalt.core.router import route_task

        ledger = Ledger(tmp_path / ".opencobalt" / "ledger.db")
        ledger.insert_route_decision(route_task("design the auth module", record=False))

        data = client.get("/api/timeline").json()
        assert len(data) >= 1
        entry = data[0]
        for key in ("id", "timestamp", "type", "title", "model", "tier", "status"):
            assert key in entry, f"missing key: {key}"

    def test_timeline_route_entry_includes_scores(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.core.ledger import Ledger
        from opencobalt.core.router import route_task

        ledger = Ledger(tmp_path / ".opencobalt" / "ledger.db")
        decision = route_task("design the auth module", record=False)
        ledger.insert_route_decision(decision)

        data = client.get("/api/timeline").json()
        route_entries = [entry for entry in data if entry["type"] == "route"]
        assert route_entries
        scores = route_entries[0]["scores"]
        assert isinstance(scores, dict)
        assert scores
        assert decision.recommended_tool in scores
        assert route_entries[0]["cost"] is None
        assert route_entries[0]["status"] == "recorded"


# ---------------------------------------------------------------------------
# /api/telemetry
# ---------------------------------------------------------------------------

class TestTelemetry:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/telemetry").status_code == 200

    def test_empty_shape_when_no_runs(self, tmp_path, monkeypatch):
        data = _get("/api/telemetry", tmp_path, monkeypatch)
        assert data["total_runs"] == 0
        assert data["scored_runs"] == 0
        assert data["average_overall"] == 0
        assert data["top_agent"] is None
        assert data["recent"] == []

    def test_returns_scored_run_summary(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.core.telemetry import TelemetryStore

        store = TelemetryStore(tmp_path / ".opencobalt" / "telemetry.db")
        session = store.start_run(run_type="route", seed_prompt="write tests", agent_id="codex-cli")
        session.record_tool_use("pytest")
        session.record_output("Implemented tests.")
        session.finish("complete")
        store.save_score({
            "run_id": session.run_id,
            "scored_at": "2026-06-07T00:00:00Z",
            "judge": "heuristic",
            "overall": 78,
            "output_quality": 80,
            "prompt_adherence": 82,
            "novel_ideation": 55,
            "context_handling": 60,
            "token_efficiency": 70,
            "latency_score": 88,
            "tool_appropriateness": 85,
            "task_decomposition": 65,
            "agent_selection": 75,
            "convergence_quality": 95,
            "judge_reasoning": "Solid run.",
            "heuristics": {"retry_count": 0},
        })

        data = client.get("/api/telemetry").json()
        assert data["total_runs"] == 1
        assert data["scored_runs"] == 1
        assert data["average_overall"] == 78
        assert data["top_agent"] == "codex-cli"
        assert data["recent"][0]["overall"] == 78
        assert data["recent"][0]["tool_count"] == 1


# ---------------------------------------------------------------------------
# /api/receipts
# ---------------------------------------------------------------------------

class TestReceipts:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert client.get("/api/receipts").status_code == 200

    def test_empty_when_no_records(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = client.get("/api/receipts").json()
        assert data == []

    def test_entry_shape_when_populated(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.core.ledger import Ledger
        from opencobalt.core.models import VerificationResult

        ledger = Ledger(tmp_path / ".opencobalt" / "ledger.db")
        ledger.insert_verification_result(VerificationResult(
            command="pytest", exit_code=0, passed=True,
            output_summary="214 passed",
        ))

        data = client.get("/api/receipts").json()
        assert len(data) == 1
        entry = data[0]
        for key in ("id", "ok", "desc", "ts", "exit_code", "detail"):
            assert key in entry, f"missing key: {key}"
        assert entry["ok"] is True
        assert entry["exit_code"] == 0

    def test_failed_receipt_ok_false(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from opencobalt.core.ledger import Ledger
        from opencobalt.core.models import VerificationResult

        ledger = Ledger(tmp_path / ".opencobalt" / "ledger.db")
        ledger.insert_verification_result(VerificationResult(
            command="pytest", exit_code=1, passed=False,
            output_summary="3 failed",
        ))

        data = client.get("/api/receipts").json()
        assert len(data) == 1
        assert data[0]["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/route
# ---------------------------------------------------------------------------

class TestRoutePost:
    def test_returns_200(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        resp = client.post("/api/route", json={"task": "design the auth module"})
        assert resp.status_code == 200

    def test_returns_tool_and_tier(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = client.post("/api/route", json={"task": "review code quality"}).json()
        for key in ("tool", "tier", "score", "reasoning", "scores"):
            assert key in data, f"missing key: {key}"

    def test_tool_is_string(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        data = client.post("/api/route", json={"task": "summarize the readme"}).json()
        assert isinstance(data["tool"], str)
        assert len(data["tool"]) > 0

    def test_decision_persisted_to_ledger(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        client.post("/api/route", json={"task": "write unit tests"})
        sessions = client.get("/api/sessions").json()
        assert len(sessions) == 1
        assert "unit tests" in sessions[0]["task"]

    def test_empty_task_returns_422(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        resp = client.post("/api/route", json={})
        assert resp.status_code == 422
