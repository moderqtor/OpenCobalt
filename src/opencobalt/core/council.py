"""Multi-model parallel consultation with agreement scoring and synthesis."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass


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
                synthesis="No models available. Set ANTHROPIC_API_KEY or GEMINI_API_KEY.",
                recommended_action="Configure at least one model API key.",
            )
        responses = asyncio.run(_query_all(task, models))
        return _build_result(task, responses, synthesize)


def _available_models() -> list[str]:
    available = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        available.append("claude")
    if os.environ.get("GEMINI_API_KEY"):
        available.append("gemini")
    # ollama is always available as worker-tier fallback
    available.append("ollama")
    return available


async def _query_all(task: str, models: list[str]) -> dict[str, str]:
    tasks = [_query_model(task, m) for m in models]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return {m: (r if isinstance(r, str) else f"[error: {r}]") for m, r in zip(models, results)}


async def _query_model(task: str, model: str) -> str:
    try:
        if model == "claude":
            return await _query_anthropic(task)
        if model == "gemini":
            return await _query_gemini(task)
        if model == "ollama":
            return await _query_ollama(task)
        return f"[unknown model: {model}]"
    except Exception as exc:
        return f"[unavailable: {exc}]"


async def _query_anthropic(task: str) -> str:
    import httpx

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "[skipped: ANTHROPIC_API_KEY not set]"
    prompt = (
        f"You are a technical advisor. A developer is asking for your perspective on this task:\n\n"
        f"{task}\n\n"
        "Give your recommendation in 3-5 bullet points. Be specific and direct."
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 512,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]


async def _query_gemini(task: str) -> str:
    import httpx

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return "[skipped: GEMINI_API_KEY not set]"
    prompt = (
        f"You are a technical advisor. A developer is asking for your perspective on this task:\n\n"
        f"{task}\n\n"
        "Give your recommendation in 3-5 bullet points. Be specific and direct."
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


async def _query_ollama(task: str) -> str:
    import httpx

    prompt = (
        f"Technical advisor task: {task}\n\n"
        "Give 3-5 bullet points of advice. Be direct."
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "http://localhost:11434/api/generate",
                json={"model": "llama3", "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "[empty response]")
    except Exception:
        return "[skipped: ollama not running]"


def _build_result(task: str, responses: dict[str, str], synthesize: bool) -> CouncilResult:
    real_responses = {m: r for m, r in responses.items() if not r.startswith("[skipped") and not r.startswith("[error") and not r.startswith("[unavailable")}

    agreements, disagreements = _score_agreement(real_responses)
    score = _agreement_score(real_responses)

    synthesis = ""
    recommended_action = ""
    if synthesize and real_responses:
        synthesis, recommended_action = _synthesize(real_responses, agreements, disagreements)
    elif not real_responses:
        synthesis = "No models responded. Check API keys or Ollama availability."
        recommended_action = "Set ANTHROPIC_API_KEY or GEMINI_API_KEY, or start Ollama."

    return CouncilResult(
        task=task,
        responses=responses,
        agreement_score=score,
        agreements=agreements,
        disagreements=disagreements,
        synthesis=synthesis,
        recommended_action=recommended_action,
    )


def _score_agreement(responses: dict[str, str]) -> tuple[list[str], list[str]]:
    """Extract rough agreement/disagreement signals from response text."""
    if len(responses) < 2:
        return [], []

    # Collect all lines starting with bullet-like patterns
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

    # Find overlapping themes (simple word overlap)
    agreements: list[str] = []
    disagreements: list[str] = []

    for bullet in bullet_sets[0]:
        words = set(bullet.split())
        appears_in_all = all(
            any(len(words & set(b.split())) >= 2 for b in bs)
            for bs in bullet_sets[1:]
        )
        if appears_in_all:
            agreements.append(bullet[:80])
        else:
            disagreements.append(bullet[:80])

    return agreements[:5], disagreements[:5]


def _agreement_score(responses: dict[str, str]) -> float:
    if len(responses) < 2:
        return 1.0 if responses else 0.0
    bullet_sets: list[list[str]] = []
    for text in responses.values():
        bullets = [
            line.lstrip("- •*").strip().lower()
            for line in text.splitlines()
            if line.strip().startswith(("-", "•", "*"))
        ]
        bullet_sets.append(bullets)

    if not any(bullet_sets):
        return 0.5

    total_bullets = sum(len(bs) for bs in bullet_sets)
    if not total_bullets:
        return 0.5

    match_count = 0
    for i, bs in enumerate(bullet_sets):
        for bullet in bs:
            words = set(bullet.split())
            for j, other_bs in enumerate(bullet_sets):
                if j == i:
                    continue
                if any(len(words & set(b.split())) >= 2 for b in other_bs):
                    match_count += 1
                    break

    return round(min(match_count / max(total_bullets, 1), 1.0), 2)


def _synthesize(
    responses: dict[str, str],
    agreements: list[str],
    disagreements: list[str],
) -> tuple[str, str]:
    agreed_block = "\n".join(f"- {a}" for a in agreements) if agreements else "- (models gave varied responses)"
    disagreed_block = "\n".join(f"- {d}" for d in disagreements) if disagreements else "- (no clear disagreements detected)"

    synthesis = (
        f"Based on {len(responses)} model(s) consulted:\n\n"
        f"**Agreed:**\n{agreed_block}\n\n"
        f"**Varied:**\n{disagreed_block}"
    )
    recommended_action = agreements[0] if agreements else "Review the individual responses above."
    return synthesis, recommended_action
