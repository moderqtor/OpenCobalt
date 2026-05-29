"""Deterministic task router.

Recommends which tool should handle a given task based on keyword matching
and task classification. No LLM calls, no ML -- purely rule-based.

Adapted from Cobalt Forge automation/lib/economic_router.py.

Routing tiers:
  executive -- Claude Opus/Sonnet, GPT-4o, Gemini Pro
               architecture, final code, security, public docs, strategy
  manager   -- Claude Haiku, Codex CLI, Cursor
               structured cleanup, tests, extraction, intermediate review
  worker    -- local Ollama models only
               summarization, tagging, extraction, rough drafts, local fallback
"""

from __future__ import annotations

from typing import cast, Literal

from .models import RouteDecision

_TOOL_PROFILES: dict[str, dict] = {
    "claude-code": {
        "tier": "executive",
        "task_types": ["architecture", "implementation", "refactor", "security", "review", "debug", "design"],
        "keywords": ["architecture", "design", "implement", "refactor", "security", "audit", "complex", "module", "system", "schema", "api", "class", "function", "bug", "error", "fix", "build"],
        "base_score": 70,
    },
    "codex-cli": {
        "tier": "manager",
        "task_types": ["verification", "test", "lint", "type-check", "terminal", "script"],
        "keywords": ["test", "lint", "type", "check", "verify", "pytest", "mypy", "ruff", "script", "shell", "command", "run", "validate"],
        "base_score": 65,
    },
    "gemini-cli": {
        "tier": "executive",
        "task_types": ["long-context", "audit", "read", "analyze", "search"],
        "keywords": ["entire", "all files", "codebase", "read through", "scan", "analyze all", "find all", "long", "bulk", "comprehensive"],
        "base_score": 60,
    },
    "cursor": {
        "tier": "manager",
        "task_types": ["ui", "frontend", "editor", "component", "style", "css"],
        "keywords": ["ui", "component", "style", "css", "react", "tsx", "jsx", "frontend", "layout", "design", "visual", "html", "editor"],
        "base_score": 60,
    },
    "ollama": {
        "tier": "worker",
        "task_types": ["summarize", "tag", "extract", "draft", "local"],
        "keywords": ["summarize", "summary", "tag", "label", "extract", "draft", "rough", "local", "cheap", "quick note", "paraphrase", "compress", "shorten"],
        "base_score": 40,
    },
}

_EXECUTIVE_TASKS = {
    "architecture", "security", "public docs", "resume", "employer",
    "final", "production", "strategy", "design system", "critical",
}

_WORKER_ONLY_TASKS = {
    "summarize", "tag", "label", "rough draft", "extract", "compress",
    "paraphrase", "shorten", "filename", "local fallback",
}


def route_task(task: str, *, record: bool = False) -> RouteDecision:
    """Return a deterministic routing recommendation for a task description.

    Args:
        task: Natural language description of the work to be done.
        record: If True, persist the decision to the default ledger.
    """
    task_lower = task.lower()
    scores: dict[str, int] = {}

    for tool, profile in _TOOL_PROFILES.items():
        score = profile["base_score"]
        for kw in profile["keywords"]:
            if kw in task_lower:
                score += 8
        scores[tool] = score

    # Hard rules: worker-tier ceiling for certain task types
    if any(w in task_lower for w in _WORKER_ONLY_TASKS):
        scores["ollama"] += 30
        for t in ("claude-code", "codex-cli", "gemini-cli", "cursor"):
            scores[t] = max(scores[t] - 20, 0)

    # Hard rules: executive tasks must not route to Ollama
    if any(w in task_lower for w in _EXECUTIVE_TASKS):
        scores["ollama"] = 0

    best_tool = max(scores, key=lambda t: scores[t])
    profile = _TOOL_PROFILES[best_tool]
    tier = cast(Literal["executive", "manager", "worker"], profile["tier"])

    reasoning = _build_reasoning(task_lower, best_tool, scores)

    decision = RouteDecision(
        task=task,
        recommended_tool=best_tool,
        score=scores[best_tool],
        reasoning=reasoning,
        tier=tier,
        scores=scores,
    )

    if record:
        from .ledger import Ledger
        Ledger().insert_route_decision(decision)

    return decision


def _build_reasoning(task_lower: str, tool: str, scores: dict[str, int]) -> str:
    profile = _TOOL_PROFILES[tool]
    matched_kws = [kw for kw in profile["keywords"] if kw in task_lower]
    runner_up = sorted(scores, key=lambda t: scores[t], reverse=True)[1]
    parts = [f"Routed to {tool} (score {scores[tool]})."]
    if matched_kws:
        parts.append(f"Matched keywords: {', '.join(matched_kws[:3])}.")
    parts.append(f"Tier: {profile['tier']}.")
    parts.append(f"Runner-up: {runner_up} (score {scores[runner_up]}).")
    return " ".join(parts)
