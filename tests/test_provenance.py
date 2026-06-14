"""Tests for provenance tracing and the opencobalt why command.

All state lives in tmp_path-isolated SQLite. Execution uses the noop
adapter only; trace building itself is read-only.
"""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from opencobalt.cli import app
from opencobalt.core.approval_bridge import ApprovalBridge
from opencobalt.core.opportunity_engine import OpportunityEngine
from opencobalt.core.opportunity_store import OpportunityStore
from opencobalt.core.provenance import (
    ProvenanceBuilder,
    ProvenanceTrace,
    render_trace_lines,
)
from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.store import ExecutionStore

runner = CliRunner()


def _invoke(*args: str, **kwargs):
    env = {**kwargs.pop("env", {}), "NO_COLOR": "1", "COLUMNS": "200"}
    kwargs.setdefault("color", False)
    return runner.invoke(app, list(args), env=env, **kwargs)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Full loop fixture: brainstorm -> promote -> approve -> execute (noop)."""
    monkeypatch.chdir(tmp_path)
    # Seed a tiny "repo" so evidence collectors attach test-gap evidence.
    (tmp_path / "alpha.py").write_text("x = 1\n")
    (tmp_path / "beta.py").write_text("y = 2  # TODO tighten\n")
    db = tmp_path / "ledger.db"
    events = tmp_path / "events"
    engine = OpportunityEngine(
        root=tmp_path, db_path=db, events_path=events / "opportunity.jsonl"
    )
    run = engine.brainstorm("improve code quality and test coverage", plan=True)
    bridge = ApprovalBridge(db_path=db, events_path=events / "approval.jsonl")
    track = next(t for t in run.tracks if t.name == "test gaps")
    store = OpportunityStore(db)
    request, _ = bridge.promote(run, track.track_id, opportunity_store=store)
    bridge.approve(request.request_id)
    exec_engine = ExecutionEngine(
        store=ExecutionStore(db), events_path=events / "execution.jsonl"
    )
    reports = bridge.run_steps(
        request.request_id, engine=exec_engine, runtime="noop", execute=True
    )
    receipt_id = reports[0].step.receipt_id
    outcome_id = store.record_outcome(
        track.track_id, outcome="useful",
        plan_id=track.plan_id, receipt_id=receipt_id,
    )
    return {
        "db": db,
        "run": run,
        "track": track,
        "request": bridge.store.get_request(request.request_id),
        "receipt_id": receipt_id,
        "outcome_id": outcome_id,
        "builder": ProvenanceBuilder(db),
    }


def _kinds(trace: ProvenanceTrace) -> set[str]:
    return {node.kind for node in trace.nodes}


def _ids(trace: ProvenanceTrace) -> set[str]:
    return {node.node_id for node in trace.nodes}


class TestBuilder:
    def test_trace_track_includes_full_chain(self, env):
        trace = env["builder"].trace(env["track"].track_id)
        assert trace is not None
        assert trace.focus_kind == "track"
        assert {"goal", "track", "evidence", "plan", "approval", "step",
                "exec_plan", "receipt", "outcome"} <= _kinds(trace)
        assert env["track"].track_id in _ids(trace)
        assert env["request"].request_id in _ids(trace)
        assert env["receipt_id"] in _ids(trace)
        assert env["outcome_id"] in _ids(trace)

    def test_trace_track_by_prefix(self, env):
        trace = env["builder"].trace(env["track"].track_id[:12])
        assert trace is not None
        assert trace.focus_id == env["track"].track_id

    def test_trace_approval_request(self, env):
        trace = env["builder"].trace(env["request"].request_id)
        assert trace is not None
        assert trace.focus_kind == "approval"
        assert {"goal", "track", "approval", "step", "receipt"} <= _kinds(trace)

    def test_trace_step(self, env):
        step = env["request"].steps[0]
        trace = env["builder"].trace(step.step_id)
        assert trace is not None
        assert trace.focus_kind == "step"
        assert step.step_id in _ids(trace)

    def test_trace_receipt_climbs_to_opportunity(self, env):
        trace = env["builder"].trace(env["receipt_id"])
        assert trace is not None
        assert trace.focus_kind == "receipt"
        assert {"goal", "track", "approval", "receipt", "artifact"} <= _kinds(trace)
        receipt_node = trace.get_node(env["receipt_id"])
        assert receipt_node is not None
        assert receipt_node.data["adapter_id"] == "noop"
        assert receipt_node.data["capability_snapshot_hash"]
        assert receipt_node.data["verifiability_level"] in ("full", "partial")

    def test_trace_outcome(self, env):
        trace = env["builder"].trace(env["outcome_id"])
        assert trace is not None
        assert trace.focus_kind == "outcome"
        assert env["track"].track_id in _ids(trace)

    def test_trace_goal_and_run(self, env):
        goal_trace = env["builder"].trace(env["run"].goal.goal_id)
        assert goal_trace is not None
        assert goal_trace.focus_kind == "goal"
        run_trace = env["builder"].trace(env["run"].run_id)
        assert run_trace is not None
        # A run trace anchors on its goal and includes every track.
        track_nodes = [n for n in run_trace.nodes if n.kind == "track"]
        assert len(track_nodes) == len(env["run"].tracks)

    def test_trace_opportunity_plan(self, env):
        trace = env["builder"].trace(env["track"].plan_id)
        assert trace is not None
        assert trace.focus_kind == "plan"
        assert env["track"].plan_id in _ids(trace)

    def test_trace_evidence(self, env):
        evidence = next(
            e for e in env["run"].evidence if e.track_id == env["track"].track_id
        )
        trace = env["builder"].trace(evidence.evidence_id)
        assert trace is not None
        assert evidence.evidence_id in _ids(trace)

    def test_standalone_receipt_traces_without_approval(self, env):
        exec_engine = ExecutionEngine(store=ExecutionStore(env["db"]))
        outcome = exec_engine.run_task("hello world", runtime="noop", execute=True)
        trace = env["builder"].trace(outcome.receipt.receipt_id)
        assert trace is not None
        assert trace.focus_kind == "receipt"
        assert {"exec_plan", "receipt", "artifact"} <= _kinds(trace)
        assert "goal" not in _kinds(trace)
        receipt_node = trace.get_node(outcome.receipt.receipt_id)
        assert receipt_node is not None
        assert receipt_node.data["adapter_id"] == "noop"

    def test_unknown_id_returns_none(self, env):
        assert env["builder"].trace("zzz-doesnotexist") is None
        assert env["builder"].trace("") is None

    def test_render_lines_mark_focus(self, env):
        trace = env["builder"].trace(env["track"].track_id)
        lines = render_trace_lines(trace)
        assert any("you asked about this" in line for line in lines)
        # Every node appears exactly once.
        rendered = "\n".join(lines)
        for node in trace.nodes:
            assert node.node_id[:14] in rendered

    def test_trace_is_read_only(self, env):
        import subprocess

        trace_before = env["builder"].trace(env["track"].track_id)
        assert trace_before is not None
        # No subprocess may ever start while tracing.
        real_run = subprocess.run
        try:
            subprocess.run = lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("provenance must not start a subprocess")
            )
            env["builder"].trace(env["track"].track_id)
        finally:
            subprocess.run = real_run


class TestWhyCommand:
    def _setup_loop(self) -> dict:
        result = _invoke("opportunities", "brainstorm", "improve code quality")
        track_id = re.search(r"(otrk-[0-9a-f]{6,})\s+test gaps", result.output).group(1)
        promoted = _invoke("opportunities", "approve", track_id)
        request_id = re.search(r"(areq-[0-9a-f]{6,})", promoted.output).group(1)
        _invoke("approvals", "approve", request_id)
        ran = _invoke("approvals", "run", request_id, "--runtime", "noop", "--execute")
        receipt_id = re.search(r"receipt: ([0-9a-f-]{12,})", ran.output).group(1)
        return {"track_id": track_id, "request_id": request_id, "receipt_id": receipt_id}

    def test_why_track(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ids = self._setup_loop()
        result = _invoke("why", ids["track_id"])
        assert result.exit_code == 0
        assert "kind: track" in result.output
        assert "goal" in result.output
        assert "decomposed_into" in result.output
        assert "you asked about this" in result.output

    def test_why_approval(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ids = self._setup_loop()
        result = _invoke("why", ids["request_id"])
        assert result.exit_code == 0
        assert "kind: approval" in result.output
        assert "promoted_to" in result.output
        assert "contains" in result.output

    def test_why_receipt(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ids = self._setup_loop()
        result = _invoke("why", ids["receipt_id"])
        assert result.exit_code == 0
        assert "kind: receipt" in result.output
        assert "produced" in result.output
        assert "verification_status" in result.output
        assert "adapter_id=noop" in result.output
        assert "capability_snapshot_hash=" in result.output

    def test_why_unknown_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = _invoke("why", "nope-123456")
        assert result.exit_code == 1
