"""Tests for the OpenCobalt FastAPI server.

Each test uses monkeypatch.chdir(tmp_path) so all SQLite stores land in a
throwaway directory and do not touch the real .opencobalt/ledger.db.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed; pip install 'opencobalt[server]'")

from fastapi.testclient import TestClient  # noqa: E402

from opencobalt.api_server import app  # noqa: E402

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
        assert entry["cost"].startswith("$")
        assert isinstance(entry["ok"], bool)


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
            assert isinstance(entry["on"], bool)


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

    def test_has_six_integrations(self, tmp_path, monkeypatch):
        data = _get("/api/integrations", tmp_path, monkeypatch)
        assert len(data) == 6

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
