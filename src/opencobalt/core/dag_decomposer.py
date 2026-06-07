"""DAG-based task decomposer with dependency and artifact declarations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .decomposer import TaskDecomposer

_DEPENDS_ON: dict[str, list[str]] = {
    "impl":      [],
    "tests":     ["impl"],
    "docs":      ["impl"],
    "review":    ["impl", "tests"],
    "analyze":   ["impl"],
    "summarize": ["impl", "tests", "docs"],
}

_CONSUMES: dict[str, list[str]] = {
    "impl":      [],
    "tests":     ["impl_code"],
    "docs":      ["impl_code"],
    "review":    ["impl_code", "test_code"],
    "analyze":   ["impl_code"],
    "summarize": ["impl_code", "test_code", "doc_text"],
}

_PRODUCES: dict[str, list[str]] = {
    "impl":      ["impl_code", "diff"],
    "tests":     ["test_code"],
    "docs":      ["doc_text"],
    "review":    ["review_score"],
    "analyze":   ["analysis"],
    "summarize": ["summary"],
}


@dataclass
class DAGSubTask:
    id: str
    prompt: str
    task_type: str
    preferred_tool: str
    depends_on: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)


class DAGDecomposer(TaskDecomposer):
    """Extends TaskDecomposer with DAG dependency and artifact declarations.

    Dependency and artifact declarations are inferred from task type via
    keyword tables. No LLM call required.
    """

    def decompose_dag(self, task: str) -> list[DAGSubTask]:
        """Decompose task into DAGSubTasks with dependency/artifact metadata."""
        subtasks = self.decompose(task)
        dag_tasks: list[DAGSubTask] = []
        id_by_type: dict[str, str] = {}

        for st in subtasks:
            dag_id = str(uuid.uuid4())
            id_by_type[st.task_type] = dag_id
            dag_tasks.append(
                DAGSubTask(
                    id=dag_id,
                    prompt=st.prompt,
                    task_type=st.task_type,
                    preferred_tool=st.preferred_tool,
                    produces=list(_PRODUCES.get(st.task_type, [])),
                    consumes=list(_CONSUMES.get(st.task_type, [])),
                )
            )

        # Second pass: resolve depends_on from type names to IDs
        for dag_task in dag_tasks:
            dep_types = _DEPENDS_ON.get(dag_task.task_type, [])
            dag_task.depends_on = [
                id_by_type[dt] for dt in dep_types if dt in id_by_type
            ]

        return dag_tasks

    def to_waves(self, subtasks: list[DAGSubTask]) -> list[list[DAGSubTask]]:
        """Topological sort -> execution waves. Each wave runs in parallel."""
        completed: set[str] = set()
        remaining = list(subtasks)
        waves: list[list[DAGSubTask]] = []

        while remaining:
            wave = [
                st for st in remaining
                if all(dep in completed for dep in st.depends_on)
            ]
            if not wave:
                # Unresolvable dependencies; treat remainder as final wave
                waves.append(remaining)
                break
            waves.append(wave)
            for st in wave:
                completed.add(st.id)
            remaining = [st for st in remaining if st not in wave]

        return waves
