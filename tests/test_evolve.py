"""Tests for Evolve Mode v0: missions, candidates, scoring, and gating.

Everything runs against tmp_path-isolated SQLite. Candidate generation and
mission creation never start a subprocess; execution handoff uses noop only.
"""

from __future__ import annotations

import subprocess

import pytest

from opencobalt.core.evolve import (
    EVOLVE_STATUS,
    EvolveEngine,
    EvolveMission,
    EvolvePolicy,
    EvolveStore,
    build_evolve_delegation,
    load_roadmap_snapshot,
    score_candidate,
    wrapperware_escape_value,
)
from opencobalt.execution.engine import ExecutionEngine
from opencobalt.execution.store import ExecutionStore

ROADMAP = """# Roadmap

## Completed

### Phase 1

- something done

## In Progress / Next

### Phase X

- Outcome-weighted scoring: feed outcomes back into track priors
- UI panels for opportunity tracks and approval state

## End Goal

text
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ROADMAP.md").write_text(ROADMAP)
    (tmp_path / "README.md").write_text("# OpenCobalt\n")
    (tmp_path / "alpha.py").write_text("x = 1\n")
    db = tmp_path / "ledger.db"
    engine = EvolveEngine(
        root=tmp_path,
        db_path=db,
        events_path=tmp_path / "events" / "evolve.jsonl",
    )
    return {"engine": engine, "db": db, "root": tmp_path}


class TestRoadmapSnapshot:
    def test_loads_docs_and_next_items(self, env):
        snapshot = load_roadmap_snapshot(env["root"])
        assert "docs/ROADMAP.md" in snapshot.docs_found
        assert "README.md" in snapshot.docs_found
        assert "docs/SUBAGENTS.md" in snapshot.docs_missing
        assert any("Outcome-weighted" in item for item in snapshot.next_items)

    def test_missing_roadmap_is_fine(self, tmp_path):
        snapshot = load_roadmap_snapshot(tmp_path)
        assert snapshot.next_items == []


class TestMission:
    def test_start_mission_proposes_and_scores(self, env):
        result = env["engine"].start_mission("make OpenCobalt more useful this week")
        mission = result.mission
        assert mission.status == "scored"
        assert mission.status in EVOLVE_STATUS
        assert mission.run_id is not None
        assert result.candidates
        assert all(c.score is not None for c in result.candidates)
        assert all(c.status == "scored" for c in result.candidates)
        assert result.report.ranked
        assert result.report.next_commands

    def test_roadmap_items_become_candidates(self, env):
        result = env["engine"].start_mission("improve this week")
        titles = [c.title for c in result.candidates]
        assert any("Outcome-weighted" in t for t in titles)

    def test_candidates_are_backed_by_tracks(self, env):
        from opencobalt.core.opportunity_store import OpportunityStore

        result = env["engine"].start_mission("improve this week")
        run = OpportunityStore(env["db"]).get_run(result.mission.run_id)
        assert run is not None
        track_ids = {t.track_id for t in run.tracks}
        for candidate in result.candidates:
            assert candidate.track_id in track_ids

    def test_top_candidates_get_plans(self, env):
        result = env["engine"].start_mission("improve this week")
        planned = [c for c in result.candidates if c.opportunity_plan_id]
        assert len(planned) == env["engine"].policy.plan_top_n

    def test_delegation_tree_is_analysis_only(self, env):
        plan = build_evolve_delegation("test goal")
        agents = {n.agent_id for n in plan.nodes.values()}
        assert "evolution-strategist" in agents
        assert "repo-cartographer" in agents
        assert "safety-auditor" in agents
        assert "receipt-verifier" in agents
        for node in plan.nodes.values():
            assert node.permission_scope in ("read", "write")

    def test_no_subprocess_during_mission(self, env, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("evolve mission must not start a subprocess")

        monkeypatch.setattr(subprocess, "run", explode)
        monkeypatch.setattr(subprocess, "Popen", explode)
        result = env["engine"].start_mission("improve quietly")
        assert result.candidates

    def test_events_emitted(self, env):
        env["engine"].start_mission("improve this week")
        types = {e["event_type"] for e in env["engine"].events}
        assert "evolve.mission_started" in types
        assert "evolve.roadmap_loaded" in types
        assert "evolve.candidate_created" in types
        assert "evolve.candidate_scored" in types
        assert "evolve.delegation_created" in types
        assert "evolve.report_created" in types

    def test_persistence_round_trip(self, env):
        result = env["engine"].start_mission("improve this week")
        store = EvolveStore(env["db"])
        mission = store.get_mission(result.mission.mission_id)
        assert mission is not None
        assert mission.to_dict() == result.mission.to_dict()
        clone = EvolveMission.from_dict(mission.to_dict())
        assert clone.to_dict() == mission.to_dict()
        candidates = store.list_candidates(mission.mission_id)
        assert len(candidates) == len(result.candidates)
        # Prefix lookups work.
        first = result.candidates[0]
        assert store.get_candidate(first.candidate_id[:12]) is not None


class TestScoring:
    def test_wrapperware_escape_rewards_vertical_loop(self):
        loop = wrapperware_escape_value(
            "vertical_loop", "connect approval receipts into the outcome loop"
        )
        wrapper = wrapperware_escape_value("adapter_integration", "wrap another cli tool")
        assert loop > wrapper
        assert loop > 0.8
        assert wrapper < 0.5

    def test_score_is_explainable(self, env):
        result = env["engine"].start_mission("improve this week")
        candidate = result.candidates[0]
        assert candidate.score.explanation
        assert any("wrapperware_escape_value" in line for line in candidate.score.explanation)
        assert any(line.startswith("total=") for line in candidate.score.explanation)

    def test_vertical_loop_candidate_outranks_adapter(self, env):
        result = env["engine"].start_mission("improve this week")
        by_type = {}
        for candidate in result.candidates:
            by_type.setdefault(candidate.candidate_type, candidate)
        if "vertical_loop" in by_type and "adapter_integration" in by_type:
            assert (
                by_type["vertical_loop"].score.total
                > by_type["adapter_integration"].score.total
            )

    def test_score_candidate_clamps(self):
        from opencobalt.core.evolve import EvolveCandidate

        candidate = EvolveCandidate(
            candidate_id="ecand-x", mission_id="emis-x",
            title="x", candidate_type="vertical_loop",
        )
        score = score_candidate(candidate, priors={"user_value": 5.0})
        assert 0.0 <= score.total <= 1.0


class TestApprovalAndRun:
    def _mission(self, env):
        return env["engine"].start_mission("improve this week")

    def test_approve_candidate_uses_bridge(self, env):
        result = self._mission(env)
        planned = next(c for c in result.candidates if c.opportunity_plan_id)
        candidate, request = env["engine"].approve_candidate(planned.candidate_id)
        assert candidate.approval_request_id == request.request_id
        assert request.state in ("approved", "pending")
        assert candidate.status in ("approved", "approval_pending")

    def test_run_refuses_without_approval_request(self, env):
        result = self._mission(env)
        planned = next(c for c in result.candidates if c.opportunity_plan_id)
        engine = ExecutionEngine(store=ExecutionStore(env["db"]))
        with pytest.raises(KeyError, match="evolve approve"):
            env["engine"].run_candidate(
                planned.candidate_id, engine=engine, runtime="noop"
            )

    def test_run_is_dry_run_by_default(self, env):
        result = self._mission(env)
        planned = next(c for c in result.candidates if c.opportunity_plan_id)
        env["engine"].approve_candidate(planned.candidate_id)
        engine = ExecutionEngine(store=ExecutionStore(env["db"]))
        candidate, reports = env["engine"].run_candidate(
            planned.candidate_id, engine=engine, runtime="noop"
        )
        assert all(r.action in ("dry_run", "refused", "blocked", "skipped") for r in reports)
        assert any(r.action == "dry_run" for r in reports)
        assert candidate.status != "verified"

    def test_run_executes_and_links_receipts(self, env):
        result = self._mission(env)
        planned = next(c for c in result.candidates if c.opportunity_plan_id)
        env["engine"].approve_candidate(planned.candidate_id)
        engine = ExecutionEngine(store=ExecutionStore(env["db"]))
        candidate, reports = env["engine"].run_candidate(
            planned.candidate_id, engine=engine, runtime="noop", execute=True
        )
        assert candidate.status == "verified"
        assert candidate.receipt_ids
        assert candidate.execution_plan_ids
        receipt = ExecutionStore(env["db"]).get_receipt(candidate.receipt_ids[0])
        assert receipt is not None

    def test_outcome_recorded_with_receipt(self, env):
        from opencobalt.core.opportunity_store import OpportunityStore

        result = self._mission(env)
        planned = next(c for c in result.candidates if c.opportunity_plan_id)
        env["engine"].approve_candidate(planned.candidate_id)
        engine = ExecutionEngine(store=ExecutionStore(env["db"]))
        env["engine"].run_candidate(
            planned.candidate_id, engine=engine, runtime="noop", execute=True
        )
        outcome_id = env["engine"].record_outcome(planned.candidate_id, "useful")
        outcomes = OpportunityStore(env["db"]).list_outcomes()
        assert outcomes[0]["outcome_id"] == outcome_id
        assert outcomes[0]["receipt_id"]


class TestRoadmapWriteGate:
    def test_write_blocked_without_policy(self, env):
        result = env["engine"].start_mission("improve this week")
        with pytest.raises(PermissionError, match="--write"):
            env["engine"].write_roadmap_proposals(result.mission)
        # Roadmap unchanged.
        text = (env["root"] / "docs" / "ROADMAP.md").read_text()
        assert "evolve mission" not in text

    def test_write_appends_marked_section_with_policy(self, env):
        engine = EvolveEngine(
            root=env["root"],
            db_path=env["db"],
            events_path=env["root"] / "events" / "evolve.jsonl",
            policy=EvolvePolicy(allow_roadmap_write=True),
        )
        result = engine.start_mission("improve this week")
        before = (env["root"] / "docs" / "ROADMAP.md").read_text()
        engine.write_roadmap_proposals(result.mission)
        after = (env["root"] / "docs" / "ROADMAP.md").read_text()
        assert after.startswith(before)  # append only, never rewrites
        assert f"evolve mission {result.mission.mission_id[:13]}" in after
        # Idempotent: a second write does not duplicate the section.
        engine.write_roadmap_proposals(result.mission)
        assert after == (env["root"] / "docs" / "ROADMAP.md").read_text()

    def test_policy_defaults_are_safe(self):
        policy = EvolvePolicy()
        assert policy.allow_roadmap_write is False
        assert policy.allow_push is False
        assert policy.network_collectors_enabled is False
