"""Profile-aware tool choice adjustments over deterministic router scores."""

from __future__ import annotations

from dataclasses import dataclass

from .ledger import Ledger


@dataclass(frozen=True)
class ToolChoice:
    tool: str
    score: float
    reasons: list[str]


class UsageOptimizer:
    def __init__(self, ledger: Ledger, benchmark_store=None) -> None:
        self.ledger = ledger
        self.benchmark_store = benchmark_store

    def choose_tool(
        self,
        *,
        task_type: str,
        profile: str,
        router_scores: dict[str, int | float],
        run_id: str | None = None,
        telemetry_session=None,
    ) -> ToolChoice:
        scores = {tool: float(score) for tool, score in router_scores.items()}
        reasons = ["router"]
        router_winner = max(scores, key=lambda t: scores[t]) if scores else None

        if profile == "cheap" and task_type == "summarize" and "ollama" in scores:
            scores["ollama"] += 8.0
            reasons.append("cheap-profile")

        if profile == "max":
            observations = self.ledger.list_usage_observations(run_id, limit=50)
            rate_limited_tools = {
                item["tool"]
                for item in observations
                if item["event_type"] == "rate_limit" and item["tool"] in scores
            }
            for tool in rate_limited_tools:
                scores[tool] -= 6.0
            if rate_limited_tools:
                reasons.append("rate-limit")

        if self.benchmark_store is not None:
            best = self.benchmark_store.get_best_for_task_type(task_type)
            if best in scores:
                scores[best] += 3.0
                reasons.append("benchmark")

        tool = max(scores, key=lambda t: scores[t])

        if telemetry_session is not None and router_winner is not None and tool != router_winner:
            telemetry_session.record_agent_switch(router_winner, tool)

        return ToolChoice(tool=tool, score=scores[tool], reasons=reasons)
