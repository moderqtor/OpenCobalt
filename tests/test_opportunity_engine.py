"""Tests for the Autonomous Opportunity Engine v0.

Hermetic: no external calls, no live agent runtimes, all state in tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opencobalt.core.delegation import DelegationDepthError, DelegationPlan
from opencobalt.core.opportunity_engine import (
    EVENT_EVIDENCE_ATTACHED,
    EVENT_GOAL_RECEIVED,
    EVENT_PLAN_CREATED,
    EVENT_REPORT_CREATED,
    EVENT_SCORED,
    EVENT_TRACK_CREATED,
    GOAL_CLASSES,
    OpportunityEngine,
    OpportunityEvidence,
    OpportunityRun,
    OpportunityTrack,
    TrackTemplate,
    build_delegation_tree,
    classify_goal,
    opportunity_registry,
    register_track_template,
    score_track,
)
from opencobalt.core.opportunity_store import OpportunityStore


def make_engine(tmp_path: Path, **kwargs) -> OpportunityEngine:
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "module.py").write_text("# TODO: improve\n", encoding="utf-8")
    return OpportunityEngine(
        root=tmp_path,
        db_path=tmp_path / "ledger.db",
        events_path=tmp_path / "events" / "opportunity.jsonl",
        **kwargs,
    )


class TestGoalClassification:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("improve code quality and test coverage", "code_quality"),
            ("authorized security audit of policy gates", "security_authorized"),
            ("reduce token spend and budget", "cost_saving"),
            ("redesign the TUI dashboard layout", "design"),
            ("automate the release workflow pipeline", "automation"),
            ("research prior art and compare options", "research"),
            ("grow community adoption and stars", "growth"),
            ("find useful opportunities for this product", "product"),
            ("zzz qqq", "unknown"),
        ],
    )
    def test_classify_goal(self, text: str, expected: str) -> None:
        assert classify_goal(text) == expected
        assert expected in GOAL_CLASSES


class TestTrackGeneration:
    def test_generates_base_and_class_tracks(self, tmp_path) -> None:
        engine = make_engine(tmp_path)
        run = engine.brainstorm("improve code quality", plan=False)
        names = [t.name for t in run.tracks]
        assert "test gaps" in names
        assert "docs improvement" in names
        assert "refactor hotspots" in names  # code_quality specific
        assert all(t.goal_id == run.goal.goal_id for t in run.tracks)

    def test_track_library_is_extensible(self, tmp_path) -> None:
        template = TrackTemplate(
            name="custom compliance sweep",
            track_type="security",
            description="custom",
            priors={"expected_impact": 0.9},
        )
        register_track_template("design", template)
        try:
            engine = make_engine(tmp_path)
            run = engine.brainstorm("redesign the TUI layout", plan=False)
            assert "custom compliance sweep" in [t.name for t in run.tracks]
        finally:
            from opencobalt.core.opportunity_engine import _CLASS_TRACKS

            _CLASS_TRACKS["design"].remove(template)

    def test_unknown_goal_class_rejected(self) -> None:
        with pytest.raises(ValueError):
            register_track_template("nonsense", TrackTemplate("x", "x", "x"))


def _track(**priors) -> OpportunityTrack:
    return OpportunityTrack(
        track_id="otrk-test", goal_id="goal-test", name="t", track_type="docs",
        priors=priors,
    )


def _evidence(strength: float) -> OpportunityEvidence:
    return OpportunityEvidence(
        evidence_id="ev-test", track_id="otrk-test", source_type="note",
        reference="manual", summary="s", strength=strength,
    )


class TestScoring:
    def test_score_is_explainable_and_bounded(self) -> None:
        score = score_track(_track(expected_impact=0.8), [_evidence(0.6)])
        assert 0.0 <= score.total <= 1.0
        assert any("expected_impact" in line for line in score.explanation)
        assert any(line.startswith("total=") for line in score.explanation)

    def test_risk_lowers_score(self) -> None:
        low_risk = score_track(_track(risk=0.1), [_evidence(0.5)])
        high_risk = score_track(_track(risk=0.9), [_evidence(0.5)])
        assert high_risk.total < low_risk.total

    def test_evidence_strength_raises_score(self) -> None:
        weak = score_track(_track(), [_evidence(0.1)])
        strong = score_track(_track(), [_evidence(0.9)])
        assert strong.total > weak.total

    def test_no_evidence_scores_below_strong_evidence(self) -> None:
        none = score_track(_track(), [])
        strong = score_track(_track(), [_evidence(0.9)])
        assert none.total < strong.total

    def test_receipt_evidence_boosts_verification_quality(self) -> None:
        receipt_ev = OpportunityEvidence(
            evidence_id="ev-r", track_id="otrk-test", source_type="receipt",
            reference="ledger", summary="verified receipts", strength=0.5,
        )
        with_receipt = score_track(_track(), [receipt_ev])
        without = score_track(_track(), [_evidence(0.5)])
        assert (
            with_receipt.dimensions["verification_quality"]
            > without.dimensions["verification_quality"]
        )


class TestDelegation:
    def test_delegation_tree_has_nested_fanout(self) -> None:
        track = OpportunityTrack(
            track_id="otrk-x", goal_id="g", name="test gaps", track_type="tests",
        )
        plan = build_delegation_tree(track)
        assert plan.root_id is not None
        root = plan.nodes[plan.root_id]
        assert root.agent_id == "strategist"
        children = [plan.nodes[c] for c in root.child_ids]
        assert {c.agent_id for c in children} == {"researcher", "receipt-verifier"}
        researcher = next(c for c in children if c.agent_id == "researcher")
        grandchildren = [plan.nodes[c].agent_id for c in researcher.child_ids]
        assert "test-writer" in grandchildren  # depth-2 fan-out within a subagent
        assert all(plan.nodes[c].depth == 2 for c in researcher.child_ids)

    def test_every_node_has_bounded_contract(self) -> None:
        track = OpportunityTrack(
            track_id="otrk-x", goal_id="g", name="docs improvement", track_type="docs",
        )
        plan = build_delegation_tree(track)
        for node in plan.nodes.values():
            assert node.risk_level in ("green", "yellow", "red", "black")
            assert node.permission_scope in ("read", "write", "execute")
            assert node.output_contract
            assert node.depth <= plan.max_depth

    def test_max_depth_enforced(self) -> None:
        registry = opportunity_registry()
        plan = DelegationPlan("deep task", registry=registry, max_depth=1)
        root = plan.add_root("strategist")
        child = plan.delegate(root.node_id, "researcher", "level 1")
        with pytest.raises(DelegationDepthError):
            plan.delegate(child.node_id, "implementer", "level 2 exceeds max")


class TestEngine:
    def test_brainstorm_never_executes(self, tmp_path, monkeypatch) -> None:
        import subprocess

        def explode(*args, **kwargs):
            raise AssertionError("opportunity engine must not start subprocesses")

        monkeypatch.setattr(subprocess, "run", explode)
        monkeypatch.setattr(subprocess, "Popen", explode)
        engine = make_engine(tmp_path)
        run = engine.brainstorm("find useful opportunities for this product")
        assert run.plans
        for plan in run.plans:
            assert plan.executed is False
            assert plan.approval_state in ("not_required", "pending")

    def test_plans_above_green_need_approval(self, tmp_path) -> None:
        engine = make_engine(tmp_path)
        run = engine.brainstorm("improve code quality and test coverage")
        track = next(t for t in run.tracks if t.track_type == "tests")
        plan = next(p for p in run.plans if p.track_id == track.track_id)
        assert plan.risk_level != "green"  # test-run steps classify yellow
        assert plan.approval_state == "pending"

    def test_event_emission_covers_pipeline(self, tmp_path) -> None:
        engine = make_engine(tmp_path)
        engine.brainstorm("find useful opportunities for this product")
        types = {e["event_type"] for e in engine.events}
        assert {
            EVENT_GOAL_RECEIVED,
            EVENT_TRACK_CREATED,
            EVENT_EVIDENCE_ATTACHED,
            EVENT_SCORED,
            EVENT_PLAN_CREATED,
            EVENT_REPORT_CREATED,
        } <= types
        # events also land on the JSONL spine
        assert (tmp_path / "events" / "opportunity.jsonl").exists()

    def test_json_round_trip(self, tmp_path) -> None:
        engine = make_engine(tmp_path)
        run = engine.brainstorm("improve code quality")
        restored = OpportunityRun.from_dict(run.to_dict())
        assert restored.to_dict() == run.to_dict()
        assert restored.goal.goal_class == run.goal.goal_class
        assert len(restored.plans) == len(run.plans)

    def test_attach_note_rescores(self, tmp_path) -> None:
        engine = make_engine(tmp_path)
        run = engine.brainstorm("improve code quality", plan=False)
        track = run.tracks[0]
        before = run.score_for(track.track_id).total
        engine.attach_note(run, track.track_id, "users keep asking for this", strength=1.0)
        after = run.score_for(track.track_id).total
        assert after > before  # strong manual evidence raises the score

    def test_broken_collector_never_blocks_run(self, tmp_path) -> None:
        class Broken:
            source_type = "note"

            def collect(self, track, *, context):
                raise RuntimeError("boom")

        engine = make_engine(tmp_path, collectors=[Broken()])
        run = engine.brainstorm("improve code quality", plan=False)
        assert run.tracks  # pipeline survives, just with no evidence
        assert run.evidence == []


class TestStore:
    def test_run_persists_and_loads(self, tmp_path) -> None:
        engine = make_engine(tmp_path)
        run = engine.brainstorm("find useful opportunities for this product")
        store = OpportunityStore(tmp_path / "ledger.db")
        loaded = store.get_run(run.run_id)
        assert loaded is not None
        assert loaded.to_dict() == run.to_dict()
        assert store.latest_run().run_id == run.run_id
        assert store.list_runs()[0]["goal_class"] == "product"

    def test_find_run_for_track_prefix(self, tmp_path) -> None:
        engine = make_engine(tmp_path)
        run = engine.brainstorm("improve code quality", plan=False)
        store = OpportunityStore(tmp_path / "ledger.db")
        track_id = run.tracks[0].track_id
        found = store.find_run_for_track(track_id[:10])
        assert found is not None and found.run_id == run.run_id

    def test_outcome_recording(self, tmp_path) -> None:
        store = OpportunityStore(tmp_path / "ledger.db")
        outcome_id = store.record_outcome(
            "otrk-abc", outcome="useful", notes="shipped and adopted"
        )
        assert outcome_id.startswith("oout-")
        outcomes = store.list_outcomes(track_id="otrk-abc")
        assert outcomes[0]["outcome"] == "useful"
        with pytest.raises(ValueError):
            store.record_outcome("otrk-abc", outcome="amazing")
