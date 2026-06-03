"""Outcome-weighted wrapper around the deterministic task router."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, cast

from .ledger import Ledger
from .models import RouteDecision
from .router import _TOOL_PROFILES, route_task

_MAX_ADJUSTMENT = 0.15
_DECAY_DAYS = 30
_OUTCOME_WEIGHTS = {
    "committed": 1.0,
    "test_failed": -0.5,
    "reverted": -1.0,
    "skipped": 0.0,
}


class LearningRouter:
    """Route tasks using keyword scoring plus learned outcome weights."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def route(self, task: str) -> RouteDecision:
        """Route with base keyword scoring adjusted by learned weights."""
        decision = route_task(task, record=False)
        weights = self.get_weights()
        if not weights:
            return decision

        adjusted_scores = {}
        for tool, score in decision.scores.items():
            adjustment = weights.get(tool, 0.0)
            adjusted_scores[tool] = max(0, int(score * (1 + adjustment)))

        best_tool = max(adjusted_scores, key=lambda tool: adjusted_scores[tool])
        if best_tool != decision.recommended_tool:
            tier = cast(
                Literal["executive", "manager", "worker"],
                _TOOL_PROFILES[best_tool]["tier"],
            )
            return RouteDecision(
                task=task,
                recommended_tool=best_tool,
                score=adjusted_scores[best_tool],
                reasoning=(
                    f"Routed to {best_tool} "
                    f"(learned weight {weights.get(best_tool, 0):+.0%}). "
                    f"Base: {decision.reasoning}"
                ),
                tier=tier,
                scores=adjusted_scores,
            )
        return decision

    def record_outcome(self, task_id: str, tool: str, outcome: str) -> None:
        """Record how a task turned out for future weight computation."""
        self._ledger.insert_outcome(task_id=task_id, tool=tool, outcome=outcome)

    def get_weights(self) -> dict[str, float]:
        """Compute per-tool score adjustment factors from recent outcomes."""
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=_DECAY_DAYS)).isoformat()
        try:
            all_outcomes = self._ledger.list_outcomes(limit=500)
        except Exception:
            return {}

        recent = [outcome for outcome in all_outcomes if outcome.get("timestamp", "") >= cutoff]
        if not recent:
            return {}

        tool_scores: dict[str, list[float]] = {}
        for outcome in recent:
            tool = outcome["tool"]
            weight = _OUTCOME_WEIGHTS.get(outcome["outcome"], 0.0)
            tool_scores.setdefault(tool, []).append(weight)

        weights: dict[str, float] = {}
        for tool, scores in tool_scores.items():
            avg = sum(scores) / len(scores)
            weights[tool] = max(
                -_MAX_ADJUSTMENT,
                min(_MAX_ADJUSTMENT, avg * _MAX_ADJUSTMENT),
            )

        return weights
