"""Durable long-run autonomy queue management."""

from __future__ import annotations

from .decomposer import TaskDecomposer
from .ledger import Ledger


class AutonomyEngine:
    """Create, resume, and checkpoint SQLite-backed autonomy runs."""

    def __init__(
        self,
        ledger: Ledger | None = None,
        decomposer: TaskDecomposer | None = None,
        max_iterations: int | None = None,
    ) -> None:
        self.ledger = ledger or Ledger()
        self.decomposer = decomposer or TaskDecomposer()
        self.max_iterations = max_iterations

    def start(
        self,
        seed_goal: str,
        profile: str = "balanced",
        hours: int | float | None = None,
        allowed_actions: list[str] | None = None,
        denied_actions: list[str] | None = None,
        telemetry_session=None,
    ) -> dict:
        """Create a running autonomy run and persist its initial task queue."""
        metadata: dict[str, int | float] = {}
        if hours is not None:
            metadata["hours"] = hours
        if self.max_iterations is not None:
            metadata["max_iterations"] = self.max_iterations

        run_id = self.ledger.create_autonomy_run(
            seed_goal,
            profile=profile,
            allowed_actions=list(allowed_actions or []),
            denied_actions=list(denied_actions or []),
            status="running",
            metadata=metadata,
        )

        subtasks = self.decomposer.decompose(seed_goal)
        priority = len(subtasks)
        for subtask in subtasks:
            self.ledger.add_autonomy_task(
                run_id=run_id,
                prompt=subtask.prompt,
                task_type=subtask.task_type,
                preferred_tool=subtask.preferred_tool,
                preferred_subagent=subtask.preferred_agent,
                priority=priority,
                status="queued",
            )
            priority -= 1

        run = self.ledger.get_autonomy_run(run_id)
        if run is None:
            raise RuntimeError(f"Autonomy run {run_id} was not persisted")
        return run

    def resume(self, run_id: str) -> dict:
        """Return durable run state with completed tasks excluded from next work."""
        run = self.ledger.get_autonomy_run(run_id)
        if run is None:
            raise ValueError(f"Unknown autonomy run: {run_id}")

        tasks = self.ledger.list_autonomy_tasks(run_id)
        run["next_tasks"] = [
            task for task in tasks
            if task["status"] != "completed"
        ]
        return run

    def checkpoint_task(
        self,
        run_id: str,
        task_id: str,
        *,
        status: str,
        artifact_ids: list[str] | None = None,
    ) -> dict:
        """Persist task checkpoint state and return the saved task."""
        tasks = self.ledger.list_autonomy_tasks(run_id)
        if not any(task["id"] == task_id for task in tasks):
            raise ValueError(f"Task {task_id} does not belong to run {run_id}")

        self.ledger.update_autonomy_task(
            task_id,
            status=status,
            artifact_ids=list(artifact_ids or []),
        )
        for task in self.ledger.list_autonomy_tasks(run_id):
            if task["id"] == task_id:
                return task
        raise RuntimeError(f"Autonomy task {task_id} was not persisted")
