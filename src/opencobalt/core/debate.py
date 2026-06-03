"""Two-model debate with adjudication."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from .council import _query_model


@dataclass
class DebateResult:
    question: str
    for_model: str
    against_model: str
    judge_model: str
    for_argument: str
    against_argument: str
    judgment: str
    winner: str
    recommendation: str


class DebateSession:
    """Run a structured for/against debate with a third-model adjudicator."""

    def run(
        self,
        question: str,
        for_model: str | None = None,
        against_model: str | None = None,
        judge_model: str | None = None,
    ) -> DebateResult:
        models = _available_models()
        for_model = for_model or (models[0] if models else "claude")
        against_model = against_model or (models[1] if len(models) > 1 else for_model)
        judge_model = judge_model or models[-1]

        return asyncio.run(_run_debate(question, for_model, against_model, judge_model))


def _available_models() -> list[str]:
    available = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        available.append("claude")
    if os.environ.get("GEMINI_API_KEY"):
        available.append("gemini")
    available.append("ollama")
    return available


async def _run_debate(
    question: str,
    for_model: str,
    against_model: str,
    judge_model: str,
) -> DebateResult:
    for_prompt = (
        f"Argue FOR this position as strongly as possible: {question}\n\n"
        "Be specific. Use technical reasoning. 3-5 bullet points."
    )
    against_prompt = (
        f"Argue AGAINST this position as strongly as possible: {question}\n\n"
        "Be specific. Use technical reasoning. 3-5 bullet points."
    )

    for_arg, against_arg = await asyncio.gather(
        _query_model(for_prompt, for_model),
        _query_model(against_prompt, against_model),
    )

    judge_prompt = (
        f"Two AI models debated: {question}\n\n"
        f"FOR:\n{for_arg}\n\n"
        f"AGAINST:\n{against_arg}\n\n"
        "Your job: identify the strongest point on each side, declare a winner with reasoning, "
        "and give a practical recommendation. Be direct."
    )
    judgment_raw = await _query_model(judge_prompt, judge_model)

    winner, recommendation = _extract_verdict(judgment_raw)

    return DebateResult(
        question=question,
        for_model=for_model,
        against_model=against_model,
        judge_model=judge_model,
        for_argument=for_arg,
        against_argument=against_arg,
        judgment=judgment_raw,
        winner=winner,
        recommendation=recommendation,
    )


def _extract_verdict(judgment: str) -> tuple[str, str]:
    """Heuristic extraction of winner and recommendation from free-form judgment."""
    lower = judgment.lower()
    winner = "unclear"
    for label in ("for wins", "for side wins", "position for", "argues for"):
        if label in lower:
            winner = "FOR"
            break
    for label in ("against wins", "against side wins", "position against", "argues against"):
        if label in lower:
            winner = "AGAINST"
            break

    # Last sentence as recommendation fallback
    sentences = [s.strip() for s in judgment.replace("\n", " ").split(".") if s.strip()]
    recommendation = sentences[-1] if sentences else judgment[:100]
    return winner, recommendation
