"""Provenance tests for Evolve Mode: why mission / candidate / receipt."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.core.evolve import EvolveEngine
from opencobalt.core.provenance import ProvenanceBuilder
from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.store import ExecutionStore

runner = CliRunner()

ROADMAP = """# Roadmap

## In Progress / Next

- Outcome-weighted scoring: feed outcomes back into track priors
"""


def _invoke(*args: str, **kwargs):
    env = {**kwargs.pop("env", {}), "NO_COLOR": "1", "COLUMNS": "200"}
    kwargs.setdefault("color", False)
    return runner.invoke(app, list(args), env=env, **kwargs)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Mission run through approval and noop execution."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ROADMAP.md").write_text(ROADMAP)
    # Same path the CLI resolves so why-command tests share the state.
    db = tmp_path / ".opencobalt" / "ledger.db"
    engine = EvolveEngine(
        root=tmp_path, db_path=db, events_path=tmp_path / "events" / "evolve.jsonl"
    )
    result = engine.start_mission("make OpenCobalt more useful this week")
    planned = next(c for c in result.candidates if c.opportunity_plan_id)
    engine.approve_candidate(planned.candidate_id)
    exec_engine = ExecutionEngine(store=ExecutionStore(db))
    candidate, _ = engine.run_candidate(
        planned.candidate_id, engine=exec_engine, runtime="noop", execute=True
    )
    return {
        "db": db,
        "mission": result.mission,
        "candidate": candidate,
        "builder": ProvenanceBuilder(db),
    }


def _kinds(trace) -> set[str]:
    return {n.kind for n in trace.nodes}


class TestEvolveProvenance:
    def test_trace_mission(self, env):
        trace = env["builder"].trace(env["mission"].mission_id)
        assert trace is not None
        assert trace.focus_kind == "mission"
        assert {"mission", "candidate", "goal", "track"} <= _kinds(trace)

    def test_trace_candidate_full_chain(self, env):
        trace = env["builder"].trace(env["candidate"].candidate_id)
        assert trace is not None
        assert trace.focus_kind == "candidate"
        assert {"mission", "candidate", "goal", "track", "approval",
                "step", "receipt"} <= _kinds(trace)

    def test_trace_candidate_by_prefix(self, env):
        trace = env["builder"].trace(env["candidate"].candidate_id[:12])
        assert trace is not None
        assert trace.focus_id == env["candidate"].candidate_id

    def test_receipt_traces_back_to_mission(self, env):
        receipt_id = env["candidate"].receipt_ids[0]
        trace = env["builder"].trace(receipt_id)
        assert trace is not None
        assert "mission" in _kinds(trace)
        assert "candidate" in _kinds(trace)

    def test_why_cli_mission_and_candidate(self, env):
        result = _invoke("why", env["mission"].mission_id)
        assert result.exit_code == 0
        assert "kind: mission" in result.output
        result = _invoke("why", env["candidate"].candidate_id)
        assert result.exit_code == 0
        assert "kind: candidate" in result.output
        assert "proposed" in result.output
        assert "mission emis-" in result.output
        # The realized_as edge is in the graph; the renderer may skip the
        # label when the track was already printed under the goal root.
        trace = env["builder"].trace(env["candidate"].candidate_id)
        assert any(e.relation == "realized_as" for e in trace.edges)
