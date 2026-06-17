"""Multi-model consultation and legacy subprocess boundary helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Generator

from .runtime_boundary import legacy_runtime_block_message, normalize_runtime_id


@dataclass
class CouncilResult:
    task: str
    responses: dict[str, str]
    agreement_score: float
    agreements: list[str]
    disagreements: list[str]
    synthesis: str
    recommended_action: str


class CouncilSession:
    """Consult multiple models in parallel and synthesise their responses."""

    def consult(
        self,
        task: str,
        models: list[str] | None = None,
        synthesize: bool = True,
    ) -> CouncilResult:
        if models is None:
            models = _available_models()
        if not models:
            return CouncilResult(
                task=task,
                responses={},
                agreement_score=0.0,
                agreements=[],
                disagreements=[],
                synthesis="No models available.",
                recommended_action="Configure at least one model.",
            )
        responses = asyncio.run(_query_all(task, models))
        return _build_result(task, responses, synthesize)


# ── Legacy subprocess boundary ────────────────────────────────────────────────


def _cmd_for(model: str, autonomous: bool = False) -> list[str]:
    """Legacy direct commands are disabled outside ExecutionEngine."""
    _ = autonomous
    if normalize_runtime_id(model):
        return []
    return []


def _blocked_direct_subprocess_message(model: str) -> str:
    return legacy_runtime_block_message(model)


def consult_subprocess(
    task: str,
    model: str = "claude",
    intent: str = "advise",
    task_type: str = "impl",
    timeout: int | None = None,
    autonomous: bool = True,
) -> str:
    """Block legacy direct CLI execution and point to ExecutionEngine."""
    _ = task, intent, task_type, timeout, autonomous
    return _blocked_direct_subprocess_message(model)


def stream_subprocess(
    task: str,
    model: str = "claude",
    intent: str = "implement",
    task_type: str = "impl",
    timeout: int = 600,
    autonomous: bool = True,
) -> Generator[str, None, str]:
    """Block legacy direct CLI streaming and point to ExecutionEngine."""
    _ = task, intent, task_type, timeout, autonomous
    yield f"{_blocked_direct_subprocess_message(model)}\n"
    return ""


def advise_subprocess(task: str, model: str = "ollama", timeout: int = 45) -> str:
    """Quick advisory call — wrapper for the common advise intent."""
    return consult_subprocess(task, model=model, intent="advise", timeout=timeout)


# ── Available models (API-based CouncilSession) ────────────────────────────────

def _available_models() -> list[str]:
    return []


async def _query_all(task: str, models: list[str]) -> dict[str, str]:
    tasks = [_query_model(task, m) for m in models]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return {m: (r if isinstance(r, str) else f"[error: {r}]") for m, r in zip(models, results)}


async def _query_model(task: str, model: str) -> str:
    _ = task
    if normalize_runtime_id(model):
        return legacy_runtime_block_message(model)
    return f"[unknown model: {model}]"


# ── Agreement scoring (used by CouncilSession) ─────────────────────────────────

def _build_result(task: str, responses: dict[str, str], synthesize: bool) -> CouncilResult:
    real = {
        m: r for m, r in responses.items()
        if not r.startswith("[skipped")
        and not r.startswith("[error")
        and not r.startswith("[unavailable")
        and not r.startswith("[blocked")
    }
    agreements, disagreements = _score_agreement(real)
    score = _agreement_score(real)
    synthesis = recommended_action = ""
    if synthesize and real:
        synthesis, recommended_action = _synthesize(real, agreements, disagreements)
    elif not real:
        synthesis = "No models responded."
        recommended_action = "Check API keys or start Ollama."
    return CouncilResult(
        task=task, responses=responses, agreement_score=score,
        agreements=agreements, disagreements=disagreements,
        synthesis=synthesis, recommended_action=recommended_action,
    )


def _score_agreement(responses: dict[str, str]) -> tuple[list[str], list[str]]:
    if len(responses) < 2:
        return [], []
    bullet_sets: list[list[str]] = []
    for text in responses.values():
        bullets = [
            line.lstrip("- •*").strip().lower()
            for line in text.splitlines()
            if line.strip().startswith(("-", "•", "*", "1", "2", "3"))
        ]
        if bullets:
            bullet_sets.append(bullets)
    if not bullet_sets:
        return [], []
    agreements: list[str] = []
    disagreements: list[str] = []
    for bullet in bullet_sets[0]:
        words = set(bullet.split())
        appears_in_all = all(
            any(len(words & set(b.split())) >= 2 for b in bs)
            for bs in bullet_sets[1:]
        )
        (agreements if appears_in_all else disagreements).append(bullet[:80])
    return agreements[:5], disagreements[:5]


def _agreement_score(responses: dict[str, str]) -> float:
    if len(responses) < 2:
        return 1.0 if responses else 0.0
    bullet_sets = [
        [line.lstrip("- •*").strip().lower()
         for line in text.splitlines()
         if line.strip().startswith(("-", "•", "*"))]
        for text in responses.values()
    ]
    total = sum(len(bs) for bs in bullet_sets)
    if not total:
        return 0.5
    match_count = sum(
        1 for i, bs in enumerate(bullet_sets) for bullet in bs
        if any(
            len(set(bullet.split()) & set(b.split())) >= 2
            for j, other_bs in enumerate(bullet_sets) if j != i
            for b in other_bs
        )
    )
    return round(min(match_count / total, 1.0), 2)


def _synthesize(
    responses: dict[str, str],
    agreements: list[str],
    disagreements: list[str],
) -> tuple[str, str]:
    agreed_block = "\n".join(f"- {a}" for a in agreements) if agreements else "- (varied responses)"
    disagreed_block = "\n".join(f"- {d}" for d in disagreements) if disagreements else "- (no clear disagreements)"
    synthesis = (
        f"Based on {len(responses)} model(s):\n\n"
        f"**Agreed:**\n{agreed_block}\n\n"
        f"**Varied:**\n{disagreed_block}"
    )
    recommended_action = agreements[0] if agreements else "Review individual responses."
    return synthesis, recommended_action
