"""Bounded evaluator loop: propose, evaluate, mutate, keep the best.

A generic, safe primitive for evaluator-driven discovery. Inspired by
evolutionary search systems, but v0 is deliberately conservative:

  - local evaluator callables only, no live external calls
  - hard max_iterations cap and wall-clock timeout
  - deterministic control flow, fully replayable history
  - a receipt (plus hashed history artifact) when a store is provided

The loop never mutates the filesystem itself. Candidates are plain values;
what the caller does with the winner goes through the normal policy gate.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from opencobalt.execution.models import ExecutionPlan, ExecutionStep, WorkReceipt

from .events import make_event

HARD_ITERATION_CAP = 1000

EVENT_CANDIDATE_EVALUATED = "evaluator.candidate_evaluated"
EVENT_LOOP_FINISHED = "evaluator.loop_finished"


@dataclass
class Candidate:
    """One proposed value and its evaluator score."""

    candidate_id: str
    payload: Any
    score: float
    iteration: int


@dataclass
class EvaluatorOutcome:
    """Everything one loop run produced."""

    loop_id: str
    name: str
    best: Candidate | None
    history: list[Candidate] = field(default_factory=list)
    iterations: int = 0
    stopped_reason: str = "max_iterations"  # max_iterations / timeout / converged
    receipt_id: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "name": self.name,
            "best": asdict(self.best) if self.best else None,
            "history": [asdict(c) for c in self.history],
            "iterations": self.iterations,
            "stopped_reason": self.stopped_reason,
            "receipt_id": self.receipt_id,
        }


class EvaluatorLoop:
    """Run a bounded propose -> evaluate -> mutate -> keep-best search.

    propose() produces the first candidate payload. evaluate(payload) returns
    a float score (higher is better). mutate(payload, score) produces the
    next payload from the current best; when omitted, the loop re-proposes.
    """

    def __init__(
        self,
        *,
        propose: Callable[[], Any],
        evaluate: Callable[[Any], float],
        mutate: Callable[[Any, float], Any] | None = None,
        max_iterations: int = 10,
        timeout_seconds: float = 30.0,
        target_score: float | None = None,
        store: Any | None = None,
        artifact_dir: Path | None = None,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        if max_iterations > HARD_ITERATION_CAP:
            raise ValueError(f"max_iterations capped at {HARD_ITERATION_CAP}")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.propose = propose
        self.evaluate = evaluate
        self.mutate = mutate
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds
        self.target_score = target_score
        self.store = store
        self.artifact_dir = artifact_dir or Path(".opencobalt") / "evaluator"

    def run(self, name: str = "evaluator-loop") -> EvaluatorOutcome:
        loop_id = f"eval-{uuid.uuid4().hex[:12]}"
        outcome = EvaluatorOutcome(loop_id=loop_id, name=name, best=None)
        started = time.monotonic()
        payload = self.propose()

        for iteration in range(1, self.max_iterations + 1):
            if time.monotonic() - started > self.timeout_seconds:
                outcome.stopped_reason = "timeout"
                break
            score = float(self.evaluate(payload))
            candidate = Candidate(
                candidate_id=f"cand-{uuid.uuid4().hex[:8]}",
                payload=payload,
                score=score,
                iteration=iteration,
            )
            outcome.history.append(candidate)
            outcome.iterations = iteration
            outcome.events.append(
                make_event(
                    event_type=EVENT_CANDIDATE_EVALUATED,
                    subject_type="evaluator",
                    subject_id=candidate.candidate_id,
                    message=f"{name} iteration {iteration}: score {score:.4f}",
                    source="evaluator-loop",
                    metadata={"loop_id": loop_id, "score": score, "iteration": iteration},
                )
            )
            if outcome.best is None or score > outcome.best.score:
                outcome.best = candidate
            if self.target_score is not None and outcome.best.score >= self.target_score:
                outcome.stopped_reason = "converged"
                break
            if self.mutate is not None:
                payload = self.mutate(outcome.best.payload, outcome.best.score)
            else:
                payload = self.propose()

        outcome.events.append(
            make_event(
                event_type=EVENT_LOOP_FINISHED,
                subject_type="evaluator",
                subject_id=loop_id,
                message=(
                    f"{name} finished: {outcome.iterations} iterations, "
                    f"best {outcome.best.score:.4f}" if outcome.best else f"{name} finished empty"
                ),
                source="evaluator-loop",
                metadata={
                    "loop_id": loop_id,
                    "stopped_reason": outcome.stopped_reason,
                    "iterations": outcome.iterations,
                },
            )
        )
        if self.store is not None:
            outcome.receipt_id = self._write_receipt(outcome)
        return outcome

    def _write_receipt(self, outcome: EvaluatorOutcome) -> str | None:
        """Persist a dry-run plan, hashed history artifact, and receipt."""
        store = self.store
        if store is None:
            return None
        try:
            from opencobalt.execution.artifacts import attach_artifact

            plan = ExecutionPlan(
                task=f"evaluator loop: {outcome.name}",
                runtime="local-evaluator",
                risk_level="green",
                steps=[
                    ExecutionStep(
                        runtime="local-evaluator",
                        command_argv=["evaluator-loop", outcome.name],
                        description=f"{outcome.iterations} bounded iterations",
                        status="succeeded",
                    )
                ],
                dry_run=True,
            )
            store.save_plan(plan)

            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            history_path = self.artifact_dir / f"{outcome.loop_id}.json"
            history_path.write_text(
                json.dumps(outcome.to_dict(), sort_keys=True, default=str, indent=2),
                encoding="utf-8",
            )
            artifact = attach_artifact(
                str(history_path),
                source_runtime="local-evaluator",
                artifact_type="report",
                plan_id=plan.plan_id,
                summary=f"evaluator history for {outcome.name}",
            )
            store.save_artifact(artifact)

            receipt = WorkReceipt(
                plan_id=plan.plan_id,
                task=f"evaluator loop: {outcome.name}",
                selected_runtime="local-evaluator",
                route_reason="bounded local evaluator loop",
                risk_level="green",
                command_plan=["evaluator-loop", outcome.name],
                artifact_ids=[artifact.artifact_id],
            )
            store.save_receipt(receipt)
            return receipt.receipt_id
        except Exception:
            return None  # receipts are best-effort; the outcome object is the result
