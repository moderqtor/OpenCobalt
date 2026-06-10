"""Tests for nested subagent delegation planning.

Planning-only: nothing in this file starts a subprocess or contacts any
external agent. Results are recorded manually to simulate completed runs.
"""

from __future__ import annotations

import json

import pytest

from opencobalt.core.delegation import (
    DelegationDepthError,
    DelegationError,
    DelegationPlan,
    PermissionScopeError,
    RiskCeilingError,
    UnknownSubagentError,
)
from opencobalt.core.subagent_registry import SubagentRegistry


def _plan(**kwargs) -> DelegationPlan:
    return DelegationPlan("ship the auth feature", **kwargs)


class TestConstruction:
    def test_root_node_uses_plan_task_by_default(self):
        plan = _plan()
        root = plan.add_root("architect")
        assert root.task == "ship the auth feature"
        assert root.depth == 0
        assert plan.root_id == root.node_id

    def test_second_root_rejected(self):
        plan = _plan()
        plan.add_root("architect")
        with pytest.raises(DelegationError):
            plan.add_root("architect")

    def test_unknown_subagent_rejected(self):
        plan = _plan()
        with pytest.raises(UnknownSubagentError):
            plan.add_root("no-such-agent")

    def test_nested_delegation_builds_parent_child_graph(self):
        plan = _plan()
        root = plan.add_root("architect")
        impl = plan.delegate(root.node_id, "impl-agent", "implement auth store")
        tests = plan.delegate(impl.node_id, "test-gen", "write auth tests")
        assert impl.parent_id == root.node_id
        assert tests.parent_id == impl.node_id
        assert root.child_ids == [impl.node_id]
        assert impl.child_ids == [tests.node_id]
        assert tests.depth == 2

    def test_fan_out_to_multiple_children(self):
        plan = _plan()
        root = plan.add_root("architect")
        children = [
            plan.delegate(root.node_id, agent, f"subtask for {agent}")
            for agent in ("impl-agent", "test-gen", "doc-writer")
        ]
        assert root.child_ids == [c.node_id for c in children]

    def test_delegate_from_unknown_parent_rejected(self):
        plan = _plan()
        plan.add_root("architect")
        with pytest.raises(DelegationError):
            plan.delegate("missing-node", "impl-agent", "task")

    def test_delegation_emits_events(self):
        plan = _plan()
        root = plan.add_root("architect")
        plan.delegate(root.node_id, "impl-agent", "implement")
        types = [e["event_type"] for e in plan.events]
        assert types.count("delegation.created") == 2


class TestMaxDepth:
    def test_depth_beyond_max_rejected(self):
        plan = _plan(max_depth=2)
        root = plan.add_root("architect")
        level1 = plan.delegate(root.node_id, "impl-agent", "level 1")
        level2 = plan.delegate(level1.node_id, "test-gen", "level 2")
        with pytest.raises(DelegationDepthError):
            plan.delegate(level2.node_id, "doc-writer", "level 3")

    def test_max_depth_must_be_positive(self):
        with pytest.raises(ValueError):
            _plan(max_depth=0)


class TestCeilings:
    def test_risk_above_subagent_ceiling_rejected(self):
        plan = _plan()
        root = plan.add_root("architect")
        # security-reviewer declares a green ceiling
        with pytest.raises(RiskCeilingError):
            plan.delegate(root.node_id, "security-reviewer", "audit", risk_level="yellow")

    def test_risk_at_ceiling_allowed(self):
        plan = _plan()
        root = plan.add_root("architect")
        node = plan.delegate(root.node_id, "impl-agent", "edit files", risk_level="yellow")
        assert node.risk_level == "yellow"

    def test_unknown_risk_level_rejected(self):
        plan = _plan()
        root = plan.add_root("architect")
        with pytest.raises(DelegationError):
            plan.delegate(root.node_id, "impl-agent", "task", risk_level="purple")

    def test_scope_above_spec_rejected(self):
        plan = _plan()
        root = plan.add_root("impl-agent")
        # summarizer declares read scope; write must not be grantable
        with pytest.raises(PermissionScopeError):
            plan.delegate(root.node_id, "summarizer", "task", permission_scope="write")

    def test_child_scope_cannot_exceed_parent_scope(self):
        plan = _plan()
        root = plan.add_root("architect")  # read scope
        with pytest.raises(PermissionScopeError):
            plan.delegate(root.node_id, "impl-agent", "task", permission_scope="write")

    def test_child_inherits_spec_scope_capped_by_parent(self):
        plan = _plan()
        root = plan.add_root("impl-agent")  # write scope
        node = plan.delegate(root.node_id, "summarizer", "summarize diff")
        assert node.permission_scope == "read"


class TestResults:
    def test_no_results_until_recorded(self):
        plan = _plan()
        root = plan.add_root("architect")
        plan.delegate(root.node_id, "impl-agent", "implement")
        assert plan.aggregate_results() == []

    def test_record_and_aggregate_subtree(self):
        plan = _plan()
        root = plan.add_root("architect")
        impl = plan.delegate(root.node_id, "impl-agent", "implement")
        docs = plan.delegate(root.node_id, "doc-writer", "document")
        plan.record_result(impl.node_id, status="succeeded", summary="done")
        plan.record_result(docs.node_id, status="failed", summary="missing context")
        statuses = {r.agent_id: r.status for r in plan.aggregate_results()}
        assert statuses == {"impl-agent": "succeeded", "doc-writer": "failed"}

    def test_results_reference_receipts_and_artifacts(self):
        plan = _plan()
        root = plan.add_root("impl-agent")
        result = plan.record_result(
            root.node_id,
            status="succeeded",
            receipt_id="receipt-123",
            artifact_ids=["artifact-1", "artifact-2"],
        )
        assert result.receipt_id == "receipt-123"
        node = plan.nodes[root.node_id]
        assert node.receipt_id == "receipt-123"
        assert node.artifact_ids == ["artifact-1", "artifact-2"]

    def test_unknown_status_rejected(self):
        plan = _plan()
        root = plan.add_root("architect")
        with pytest.raises(DelegationError):
            plan.record_result(root.node_id, status="exploded")

    def test_result_for_unknown_node_rejected(self):
        plan = _plan()
        with pytest.raises(DelegationError):
            plan.record_result("missing", status="succeeded")


class TestSerialization:
    def test_round_trip_preserves_graph(self):
        plan = _plan(max_depth=4)
        root = plan.add_root("architect")
        impl = plan.delegate(root.node_id, "impl-agent", "implement")
        plan.delegate(impl.node_id, "test-gen", "test")
        plan.record_result(impl.node_id, status="succeeded", receipt_id="receipt-9")

        data = json.loads(json.dumps(plan.to_dict()))
        restored = DelegationPlan.from_dict(data, registry=SubagentRegistry())

        assert restored.plan_id == plan.plan_id
        assert restored.max_depth == 4
        assert restored.root_id == plan.root_id
        assert set(restored.nodes) == set(plan.nodes)
        assert restored.nodes[impl.node_id].child_ids == plan.nodes[impl.node_id].child_ids
        assert restored.results[impl.node_id].receipt_id == "receipt-9"

    def test_restored_plan_can_keep_delegating(self):
        plan = _plan()
        root = plan.add_root("architect")
        restored = DelegationPlan.from_dict(plan.to_dict())
        node = restored.delegate(root.node_id, "impl-agent", "continue work")
        assert restored.nodes[node.node_id].parent_id == root.node_id


def test_module_does_not_import_subprocess():
    """Planning must stay execution-free."""
    from pathlib import Path

    import opencobalt.core.delegation as delegation

    assert delegation.__file__ is not None
    source = Path(delegation.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in source
