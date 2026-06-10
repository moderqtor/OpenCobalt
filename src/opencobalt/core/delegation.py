"""Nested subagent delegation planning.

Planning-only foundation for subagents that delegate to subagents. A
DelegationPlan is a tree of DelegationNodes: each node names a registered
subagent, a task, a risk level, and a permission scope. The planner enforces
max depth, per-subagent risk ceilings, and parent-bounded permission scopes
at construction time. Nothing here starts a process; results arrive later as
SubagentResults that reference receipts and artifacts from the execution
layer.

Every delegation and recorded result emits a structured event (in memory,
via core.events.make_event) so callers can persist or stream them.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .events import make_event
from .subagent_registry import (
    PERMISSION_SCOPES,
    RISK_LEVELS,
    SubagentRegistry,
)

DEFAULT_MAX_DEPTH = 3

_RISK_ORDER = {level: i for i, level in enumerate(RISK_LEVELS)}
_SCOPE_ORDER = {scope: i for i, scope in enumerate(PERMISSION_SCOPES)}

EVENT_DELEGATION_CREATED = "delegation.created"
EVENT_DELEGATION_RESULT = "delegation.result_recorded"


class DelegationError(Exception):
    """Base error for delegation planning failures."""


class UnknownSubagentError(DelegationError):
    """Named subagent is not in the registry."""


class DelegationDepthError(DelegationError):
    """Delegation would exceed the plan's max depth."""


class RiskCeilingError(DelegationError):
    """Requested risk exceeds the subagent's declared ceiling."""


class PermissionScopeError(DelegationError):
    """Child scope would exceed what the parent node holds."""


@dataclass
class DelegationNode:
    """One subagent assignment in the tree."""

    node_id: str
    agent_id: str
    task: str
    depth: int
    parent_id: str | None = None
    child_ids: list[str] = field(default_factory=list)
    risk_level: str = "green"
    permission_scope: str = "read"
    output_contract: str = "report"
    receipt_id: str | None = None
    artifact_ids: list[str] = field(default_factory=list)


@dataclass
class SubagentResult:
    """What a subagent returned: a status plus receipt/artifact references."""

    node_id: str
    agent_id: str
    status: str = "pending"  # pending / succeeded / failed
    summary: str = ""
    receipt_id: str | None = None
    artifact_ids: list[str] = field(default_factory=list)


class DelegationPlan:
    """A validated tree of subagent delegations. Planning-only."""

    def __init__(
        self,
        task: str,
        *,
        registry: SubagentRegistry | None = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> None:
        if max_depth < 1:
            raise ValueError("max_depth must be at least 1")
        self.plan_id = uuid.uuid4().hex
        self.task = task
        self.max_depth = max_depth
        self.registry = registry or SubagentRegistry()
        self.nodes: dict[str, DelegationNode] = {}
        self.root_id: str | None = None
        self.results: dict[str, SubagentResult] = {}
        self.events: list[dict[str, Any]] = []

    # --- Construction ---

    def add_root(self, agent_id: str, task: str | None = None, *, risk_level: str = "green") -> DelegationNode:
        if self.root_id is not None:
            raise DelegationError("plan already has a root node")
        node = self._make_node(
            agent_id=agent_id,
            task=task or self.task,
            depth=0,
            parent=None,
            risk_level=risk_level,
            permission_scope=None,
        )
        self.root_id = node.node_id
        return node

    def delegate(
        self,
        parent_node_id: str,
        agent_id: str,
        task: str,
        *,
        risk_level: str = "green",
        permission_scope: str | None = None,
    ) -> DelegationNode:
        """Fan one task out from a parent node to a child subagent."""
        parent = self.nodes.get(parent_node_id)
        if parent is None:
            raise DelegationError(f"unknown parent node: {parent_node_id}")
        node = self._make_node(
            agent_id=agent_id,
            task=task,
            depth=parent.depth + 1,
            parent=parent,
            risk_level=risk_level,
            permission_scope=permission_scope,
        )
        parent.child_ids.append(node.node_id)
        return node

    def _make_node(
        self,
        *,
        agent_id: str,
        task: str,
        depth: int,
        parent: DelegationNode | None,
        risk_level: str,
        permission_scope: str | None,
    ) -> DelegationNode:
        spec = self.registry.get(agent_id)
        if spec is None:
            raise UnknownSubagentError(f"unknown subagent: {agent_id}")
        if depth > self.max_depth:
            raise DelegationDepthError(
                f"delegation depth {depth} exceeds max_depth {self.max_depth}"
            )
        if risk_level not in _RISK_ORDER:
            raise DelegationError(f"unknown risk level: {risk_level}")
        if _RISK_ORDER[risk_level] > _RISK_ORDER[spec.risk_ceiling]:
            raise RiskCeilingError(
                f"{agent_id} accepts at most {spec.risk_ceiling} risk, requested {risk_level}"
            )

        if permission_scope is None:
            # Inherit the spec's scope, narrowed to what the parent holds.
            scope = spec.permission_scope
            if parent is not None and _SCOPE_ORDER[scope] > _SCOPE_ORDER[parent.permission_scope]:
                scope = parent.permission_scope
        else:
            scope = permission_scope
            if scope not in _SCOPE_ORDER:
                raise DelegationError(f"unknown permission scope: {scope}")
            if _SCOPE_ORDER[scope] > _SCOPE_ORDER[spec.permission_scope]:
                raise PermissionScopeError(
                    f"{agent_id} holds at most {spec.permission_scope} scope, requested {scope}"
                )
            if parent is not None and _SCOPE_ORDER[scope] > _SCOPE_ORDER[parent.permission_scope]:
                raise PermissionScopeError(
                    f"child scope {scope} exceeds parent scope {parent.permission_scope}"
                )

        node = DelegationNode(
            node_id=uuid.uuid4().hex,
            agent_id=agent_id,
            task=task,
            depth=depth,
            parent_id=parent.node_id if parent else None,
            risk_level=risk_level,
            permission_scope=scope,
            output_contract=spec.output_contract,
        )
        self.nodes[node.node_id] = node
        self._emit(
            EVENT_DELEGATION_CREATED,
            node.node_id,
            f"{parent.agent_id if parent else 'plan'} -> {agent_id} (depth {depth})",
            agent_id=agent_id,
            parent_id=node.parent_id,
            depth=depth,
            risk_level=risk_level,
            permission_scope=scope,
        )
        return node

    # --- Results ---

    def record_result(
        self,
        node_id: str,
        *,
        status: str,
        summary: str = "",
        receipt_id: str | None = None,
        artifact_ids: list[str] | None = None,
    ) -> SubagentResult:
        """Attach a completed subagent's result to its node."""
        node = self.nodes.get(node_id)
        if node is None:
            raise DelegationError(f"unknown node: {node_id}")
        if status not in ("pending", "succeeded", "failed"):
            raise DelegationError(f"unknown result status: {status}")
        result = SubagentResult(
            node_id=node_id,
            agent_id=node.agent_id,
            status=status,
            summary=summary,
            receipt_id=receipt_id,
            artifact_ids=list(artifact_ids or []),
        )
        node.receipt_id = receipt_id
        node.artifact_ids = list(result.artifact_ids)
        self.results[node_id] = result
        self._emit(
            EVENT_DELEGATION_RESULT,
            node_id,
            f"{node.agent_id} result: {status}",
            status=status,
            receipt_id=receipt_id,
            artifact_count=len(result.artifact_ids),
        )
        return result

    def aggregate_results(self, node_id: str | None = None) -> list[SubagentResult]:
        """Results for a subtree (default: whole tree), depth-first order."""
        start = node_id or self.root_id
        if start is None:
            return []
        if start not in self.nodes:
            raise DelegationError(f"unknown node: {start}")
        collected: list[SubagentResult] = []
        stack = [start]
        while stack:
            current = stack.pop()
            if current in self.results:
                collected.append(self.results[current])
            stack.extend(reversed(self.nodes[current].child_ids))
        return collected

    # --- Serialization ---

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task": self.task,
            "max_depth": self.max_depth,
            "root_id": self.root_id,
            "nodes": [asdict(n) for n in self.nodes.values()],
            "results": [asdict(r) for r in self.results.values()],
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, registry: SubagentRegistry | None = None
    ) -> DelegationPlan:
        plan = cls(data["task"], registry=registry, max_depth=data["max_depth"])
        plan.plan_id = data["plan_id"]
        plan.root_id = data.get("root_id")
        for raw in data.get("nodes", []):
            node = DelegationNode(**raw)
            plan.nodes[node.node_id] = node
        for raw in data.get("results", []):
            result = SubagentResult(**raw)
            plan.results[result.node_id] = result
        return plan

    # --- Events ---

    def _emit(self, event_type: str, subject_id: str, message: str, **metadata: Any) -> None:
        self.events.append(
            make_event(
                event_type=event_type,
                subject_type="delegation",
                subject_id=subject_id,
                message=message,
                source="delegation-planner",
                metadata={"plan_id": self.plan_id, **metadata},
            )
        )
