"""Data models for Autonomous Creation v0: IntentContract, WorkGraph, and Node specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class IntentSource(str, Enum):
    EXPLICIT_USER = "explicit_user"
    INFERRED_OPENCOBALT = "inferred_opencobalt"


@dataclass
class IntentItem:
    """A single constraint, preference, objective, or assumption with provenance."""

    text: str
    source: IntentSource = IntentSource.EXPLICIT_USER
    category: str = "general"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source.value if isinstance(self.source, IntentSource) else str(self.source),
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentItem:
        return cls(
            text=data["text"],
            source=IntentSource(data.get("source", IntentSource.EXPLICIT_USER.value)),
            category=data.get("category", "general"),
        )


@dataclass
class IntentContract:
    """The declarative specification compiled from human desire."""

    contract_id: str
    literal_request: str
    hard_constraints: list[IntentItem] = field(default_factory=list)
    user_preferences: list[IntentItem] = field(default_factory=list)
    inferred_objectives: list[IntentItem] = field(default_factory=list)
    inferred_assumptions: list[IntentItem] = field(default_factory=list)
    open_creative_dimensions: list[IntentItem] = field(default_factory=list)
    quality_criteria: dict[str, Any] = field(default_factory=dict)
    authority_level: str = "autonomous_lab"
    budget: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "literal_request": self.literal_request,
            "hard_constraints": [item.to_dict() for item in self.hard_constraints],
            "user_preferences": [item.to_dict() for item in self.user_preferences],
            "inferred_objectives": [item.to_dict() for item in self.inferred_objectives],
            "inferred_assumptions": [item.to_dict() for item in self.inferred_assumptions],
            "open_creative_dimensions": [item.to_dict() for item in self.open_creative_dimensions],
            "quality_criteria": self.quality_criteria,
            "authority_level": self.authority_level,
            "budget": self.budget,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentContract:
        return cls(
            contract_id=data["contract_id"],
            literal_request=data["literal_request"],
            hard_constraints=[IntentItem.from_dict(d) for d in data.get("hard_constraints", [])],
            user_preferences=[IntentItem.from_dict(d) for d in data.get("user_preferences", [])],
            inferred_objectives=[IntentItem.from_dict(d) for d in data.get("inferred_objectives", [])],
            inferred_assumptions=[IntentItem.from_dict(d) for d in data.get("inferred_assumptions", [])],
            open_creative_dimensions=[IntentItem.from_dict(d) for d in data.get("open_creative_dimensions", [])],
            quality_criteria=data.get("quality_criteria", {}),
            authority_level=data.get("authority_level", "autonomous_lab"),
            budget=data.get("budget", {}),
            created_at=data.get("created_at", _now_iso()),
            metadata=data.get("metadata", {}),
        )


class WorkNodeType(str, Enum):
    EXPLORATION = "exploration"
    CRITIQUE = "critique"
    SYNTHESIS = "synthesis"
    IMPLEMENTATION = "implementation"
    EVALUATION = "evaluation"
    REVISION = "revision"


class WorkNodeStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    REVISED = "revised"


@dataclass
class WorkNode:
    """A single unit of work that needs to become true."""

    node_id: str
    title: str
    work_type: WorkNodeType
    required_capability: str
    incentive_profile: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    input_artifact_ids: list[str] = field(default_factory=list)
    output_contract: str = "json"
    evaluation_criteria: list[str] = field(default_factory=list)
    status: WorkNodeStatus = WorkNodeStatus.PENDING
    assigned_executor: str | None = None
    receipt_id: str | None = None
    result_artifact_id: str | None = None
    result_summary: str | None = None
    evaluation_score: float | None = None
    retry_count: int = 0
    created_at: str = field(default_factory=_now_iso)
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "work_type": self.work_type.value if isinstance(self.work_type, WorkNodeType) else str(self.work_type),
            "required_capability": self.required_capability,
            "incentive_profile": self.incentive_profile,
            "description": self.description,
            "dependencies": list(self.dependencies),
            "input_artifact_ids": list(self.input_artifact_ids),
            "output_contract": self.output_contract,
            "evaluation_criteria": list(self.evaluation_criteria),
            "status": self.status.value if isinstance(self.status, WorkNodeStatus) else str(self.status),
            "assigned_executor": self.assigned_executor,
            "receipt_id": self.receipt_id,
            "result_artifact_id": self.result_artifact_id,
            "result_summary": self.result_summary,
            "evaluation_score": self.evaluation_score,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkNode:
        return cls(
            node_id=data["node_id"],
            title=data["title"],
            work_type=WorkNodeType(data["work_type"]),
            required_capability=data.get("required_capability", "strong_reasoning"),
            incentive_profile=data.get("incentive_profile", "neutral"),
            description=data.get("description", ""),
            dependencies=data.get("dependencies", []),
            input_artifact_ids=data.get("input_artifact_ids", []),
            output_contract=data.get("output_contract", "json"),
            evaluation_criteria=data.get("evaluation_criteria", []),
            status=WorkNodeStatus(data.get("status", WorkNodeStatus.PENDING.value)),
            assigned_executor=data.get("assigned_executor"),
            receipt_id=data.get("receipt_id"),
            result_artifact_id=data.get("result_artifact_id"),
            result_summary=data.get("result_summary"),
            evaluation_score=data.get("evaluation_score"),
            retry_count=data.get("retry_count", 0),
            created_at=data.get("created_at", _now_iso()),
            completed_at=data.get("completed_at"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class WorkGraph:
    """An adaptive network of provider-neutral work nodes."""

    graph_id: str
    contract_id: str
    nodes: dict[str, WorkNode] = field(default_factory=dict)
    status: str = "active"  # active, completed, failed, revised
    iteration: int = 0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: WorkNode) -> None:
        self.nodes[node.node_id] = node
        self.updated_at = _now_iso()

    def get_ready_nodes(self) -> list[WorkNode]:
        ready: list[WorkNode] = []
        for node in self.nodes.values():
            if node.status != WorkNodeStatus.PENDING:
                continue
            deps_met = True
            for dep_id in node.dependencies:
                dep_node = self.nodes.get(dep_id)
                if not dep_node or dep_node.status != WorkNodeStatus.COMPLETED:
                    deps_met = False
                    break
            if deps_met:
                ready.append(node)
        return ready

    def is_completed(self) -> bool:
        if not self.nodes:
            return False
        return all(
            node.status in (WorkNodeStatus.COMPLETED, WorkNodeStatus.REJECTED, WorkNodeStatus.REVISED)
            for node in self.nodes.values()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "contract_id": self.contract_id,
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
            "status": self.status,
            "iteration": self.iteration,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkGraph:
        nodes = {nid: WorkNode.from_dict(nd) for nid, nd in data.get("nodes", {}).items()}
        return cls(
            graph_id=data["graph_id"],
            contract_id=data["contract_id"],
            nodes=nodes,
            status=data.get("status", "active"),
            iteration=data.get("iteration", 0),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
            metadata=data.get("metadata", {}),
        )
