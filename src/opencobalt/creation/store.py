"""SQLite persistence store for Autonomous Creation entities."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import (
    IntentContract,
    IntentItem,
    WorkGraph,
    WorkNode,
    WorkNodeStatus,
    WorkNodeType,
)


class CreationStore:
    """Manages SQLite tables for IntentContracts, WorkGraphs, Nodes, and Artifacts."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS creation_intent_contracts (
                    contract_id TEXT PRIMARY KEY,
                    literal_request TEXT NOT NULL,
                    hard_constraints TEXT NOT NULL DEFAULT '[]',
                    user_preferences TEXT NOT NULL DEFAULT '[]',
                    inferred_objectives TEXT NOT NULL DEFAULT '[]',
                    inferred_assumptions TEXT NOT NULL DEFAULT '[]',
                    open_creative_dimensions TEXT NOT NULL DEFAULT '[]',
                    quality_criteria TEXT NOT NULL DEFAULT '{}',
                    authority_level TEXT NOT NULL DEFAULT 'autonomous_lab',
                    budget TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS creation_work_graphs (
                    graph_id TEXT PRIMARY KEY,
                    contract_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    iteration INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (contract_id) REFERENCES creation_intent_contracts(contract_id)
                );

                CREATE TABLE IF NOT EXISTS creation_graph_nodes (
                    node_id TEXT NOT NULL,
                    graph_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    work_type TEXT NOT NULL,
                    required_capability TEXT NOT NULL,
                    incentive_profile TEXT NOT NULL,
                    description TEXT NOT NULL,
                    dependencies TEXT NOT NULL DEFAULT '[]',
                    input_artifact_ids TEXT NOT NULL DEFAULT '[]',
                    output_contract TEXT NOT NULL DEFAULT 'json',
                    evaluation_criteria TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    assigned_executor TEXT,
                    receipt_id TEXT,
                    result_artifact_id TEXT,
                    result_summary TEXT,
                    evaluation_score REAL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (graph_id, node_id),
                    FOREIGN KEY (graph_id) REFERENCES creation_work_graphs(graph_id)
                );

                CREATE TABLE IF NOT EXISTS creation_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (graph_id) REFERENCES creation_work_graphs(graph_id)
                );
                """
            )
            conn.commit()

    def save_intent(self, intent: IntentContract) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO creation_intent_contracts (
                    contract_id, literal_request, hard_constraints, user_preferences,
                    inferred_objectives, inferred_assumptions, open_creative_dimensions,
                    quality_criteria, authority_level, budget, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.contract_id,
                    intent.literal_request,
                    json.dumps([item.to_dict() for item in intent.hard_constraints]),
                    json.dumps([item.to_dict() for item in intent.user_preferences]),
                    json.dumps([item.to_dict() for item in intent.inferred_objectives]),
                    json.dumps([item.to_dict() for item in intent.inferred_assumptions]),
                    json.dumps([item.to_dict() for item in intent.open_creative_dimensions]),
                    json.dumps(intent.quality_criteria),
                    intent.authority_level,
                    json.dumps(intent.budget),
                    intent.created_at,
                    json.dumps(intent.metadata),
                ),
            )
            conn.commit()

    def get_intent(self, contract_id: str) -> IntentContract | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM creation_intent_contracts WHERE contract_id = ?",
                (contract_id,),
            ).fetchone()
            if not row:
                return None
            return IntentContract(
                contract_id=row["contract_id"],
                literal_request=row["literal_request"],
                hard_constraints=[IntentItem.from_dict(d) for d in json.loads(row["hard_constraints"])],
                user_preferences=[IntentItem.from_dict(d) for d in json.loads(row["user_preferences"])],
                inferred_objectives=[IntentItem.from_dict(d) for d in json.loads(row["inferred_objectives"])],
                inferred_assumptions=[IntentItem.from_dict(d) for d in json.loads(row["inferred_assumptions"])],
                open_creative_dimensions=[IntentItem.from_dict(d) for d in json.loads(row["open_creative_dimensions"])],
                quality_criteria=json.loads(row["quality_criteria"]),
                authority_level=row["authority_level"],
                budget=json.loads(row["budget"]),
                created_at=row["created_at"],
                metadata=json.loads(row["metadata"]),
            )

    def save_work_graph(self, graph: WorkGraph) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO creation_work_graphs (
                    graph_id, contract_id, status, iteration, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    graph.graph_id,
                    graph.contract_id,
                    graph.status,
                    graph.iteration,
                    graph.created_at,
                    graph.updated_at,
                    json.dumps(graph.metadata),
                ),
            )
            for node in graph.nodes.values():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO creation_graph_nodes (
                        node_id, graph_id, title, work_type, required_capability,
                        incentive_profile, description, dependencies, input_artifact_ids,
                        output_contract, evaluation_criteria, status, assigned_executor,
                        receipt_id, result_artifact_id, result_summary, evaluation_score,
                        retry_count, created_at, completed_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        node.node_id,
                        graph.graph_id,
                        node.title,
                        node.work_type.value if isinstance(node.work_type, WorkNodeType) else str(node.work_type),
                        node.required_capability,
                        node.incentive_profile,
                        node.description,
                        json.dumps(node.dependencies),
                        json.dumps(node.input_artifact_ids),
                        node.output_contract,
                        json.dumps(node.evaluation_criteria),
                        node.status.value if isinstance(node.status, WorkNodeStatus) else str(node.status),
                        node.assigned_executor,
                        node.receipt_id,
                        node.result_artifact_id,
                        node.result_summary,
                        node.evaluation_score,
                        node.retry_count,
                        node.created_at,
                        node.completed_at,
                        json.dumps(node.metadata),
                    ),
                )
            conn.commit()

    def get_work_graph(self, graph_id: str) -> WorkGraph | None:
        with self._connect() as conn:
            grow = conn.execute(
                "SELECT * FROM creation_work_graphs WHERE graph_id = ?",
                (graph_id,),
            ).fetchone()
            if not grow:
                return None
            nodes: dict[str, WorkNode] = {}
            for nrow in conn.execute(
                "SELECT * FROM creation_graph_nodes WHERE graph_id = ?",
                (graph_id,),
            ).fetchall():
                node = WorkNode(
                    node_id=nrow["node_id"],
                    title=nrow["title"],
                    work_type=WorkNodeType(nrow["work_type"]),
                    required_capability=nrow["required_capability"],
                    incentive_profile=nrow["incentive_profile"],
                    description=nrow["description"],
                    dependencies=json.loads(nrow["dependencies"]),
                    input_artifact_ids=json.loads(nrow["input_artifact_ids"]),
                    output_contract=nrow["output_contract"],
                    evaluation_criteria=json.loads(nrow["evaluation_criteria"]),
                    status=WorkNodeStatus(nrow["status"]),
                    assigned_executor=nrow["assigned_executor"],
                    receipt_id=nrow["receipt_id"],
                    result_artifact_id=nrow["result_artifact_id"],
                    result_summary=nrow["result_summary"],
                    evaluation_score=nrow["evaluation_score"],
                    retry_count=nrow["retry_count"],
                    created_at=nrow["created_at"],
                    completed_at=nrow["completed_at"],
                    metadata=json.loads(nrow["metadata"]),
                )
                nodes[node.node_id] = node
            return WorkGraph(
                graph_id=grow["graph_id"],
                contract_id=grow["contract_id"],
                nodes=nodes,
                status=grow["status"],
                iteration=grow["iteration"],
                created_at=grow["created_at"],
                updated_at=grow["updated_at"],
                metadata=json.loads(grow["metadata"]),
            )

    def save_artifact(self, artifact_id: str, graph_id: str, node_id: str, artifact_type: str, content: dict[str, Any], created_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO creation_artifacts (
                    artifact_id, graph_id, node_id, artifact_type, content_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (artifact_id, graph_id, node_id, artifact_type, json.dumps(content), created_at),
            )
            conn.commit()

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM creation_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "artifact_id": row["artifact_id"],
                "graph_id": row["graph_id"],
                "node_id": row["node_id"],
                "artifact_type": row["artifact_type"],
                "content": json.loads(row["content_json"]),
                "created_at": row["created_at"],
            }
