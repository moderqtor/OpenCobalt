"""Deterministic task router.

Recommends which tool should handle a given task based on keyword matching
and task classification. No LLM calls, no ML -- purely rule-based.

Adapted from Cobalt Forge automation/lib/economic_router.py.

Routing tiers:
  executive -- Claude Code and Google Antigravity agent runtimes
               architecture, final code, security, public docs, strategy
  manager   -- Codex CLI, Cursor
               structured cleanup, tests, extraction, intermediate review
  worker    -- local Ollama models only
               summarization, tagging, extraction, rough drafts, local fallback
"""

from __future__ import annotations

from typing import Literal, cast

from .models import RouteDecision

_TOOL_PROFILES: dict[str, dict] = {
    "google-antigravity": {
        "tier": "executive",
        "task_types": [
            "agent-runtime",
            "multi-agent",
            "browser-validation",
            "artifact-workflow",
            "workspace-coding",
            "google-ecosystem",
        ],
        "keywords": [
            "antigravity", "multi-agent", "multi agent", "agent manager", "browser",
            "screenshot", "screenshots", "browser recording", "recording", "artifact",
            "artifacts", "visual regression", "validate ui", "browser validation",
            "workspace-level", "workspace level", "autonomous", "terminal + browser",
            "terminal and browser", "editor context", "google ecosystem", "google",
        ],
        "base_score": 58,
    },
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
    "summarize", "summary", "tag", "label", "rough draft", "extract", "compress",
    "paraphrase", "shorten", "filename", "local fallback",
}

_ANTIGRAVITY_PREFERRED_TASKS = {
    "multi-agent", "multi agent", "browser", "screenshot", "screenshots",
    "browser recording", "artifact", "artifacts", "visual regression",
    "browser validation", "workspace-level", "workspace level",
    "agent manager", "terminal + browser", "terminal and browser",
    "editor context", "google ecosystem",
}

_DETERMINISTIC_LOCAL_TASKS = {
    "tiny", "single-file", "single file", "mechanical", "deterministic",
    "typo", "one-line", "one line", "small edit",
}

_RUNTIME_COMMANDS = {
    "google-antigravity": "agy",
    "claude-code": "claude",
    "codex-cli": "codex",
    "cursor": "cursor",
    "ollama": "ollama",
}

_MODEL_POLICIES = {
    "google-antigravity": "high_reasoning_or_browser_capable",
    "claude-code": "high_reasoning",
    "codex-cli": "deterministic_code_repair",
    "cursor": "editor_assisted_ui",
    "ollama": "local_low_cost",
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
        for t in ("google-antigravity", "claude-code", "codex-cli", "cursor"):
            scores[t] = max(scores[t] - 20, 0)

    # Hard rules: executive tasks must not route to Ollama
    if any(w in task_lower for w in _EXECUTIVE_TASKS):
        scores["ollama"] = 0

    if any(w in task_lower for w in _ANTIGRAVITY_PREFERRED_TASKS):
        scores["google-antigravity"] += 35

    if any(w in task_lower for w in _DETERMINISTIC_LOCAL_TASKS):
        scores["codex-cli"] += 25
        scores["google-antigravity"] = max(scores["google-antigravity"] - 35, 0)
        scores["claude-code"] = max(scores["claude-code"] - 10, 0)

    best_tool = max(scores, key=lambda t: scores[t])
    profile = _TOOL_PROFILES[best_tool]
    tier = cast(Literal["executive", "manager", "worker"], profile["tier"])

    reasoning = _build_reasoning(task_lower, best_tool, scores)
    risk_level = _risk_level(task_lower, best_tool)

    decision = RouteDecision(
        task=task,
        recommended_tool=best_tool,
        score=scores[best_tool],
        reasoning=reasoning,
        tier=tier,
        scores=scores,
        metadata={
            "runtime": best_tool,
            "runtime_command": _RUNTIME_COMMANDS.get(best_tool, best_tool),
            "model_policy": _MODEL_POLICIES.get(best_tool, "unspecified"),
            "risk_level": risk_level,
            "approval_required": _approval_required(best_tool, risk_level),
        },
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


def _risk_level(task_lower: str, tool: str) -> str:
    if any(w in task_lower for w in ("credential export", "delete everything", "rm -rf", "wipe")):
        return "black"
    if any(
        w in task_lower
        for w in (
            ".env", "browser login", "browser profile", "browser profiles",
            "credential", "deploy",
            "deployment", "package publishing", "publish package",
            "environment configuration", "external network automation",
            "secret", "secrets", "ssh key", "ssh keys", "token", "tokens",
        )
    ):
        return "red"
    if tool == "google-antigravity" or any(
        w in task_lower
        for w in ("edit", "tests", "test", "artifact", "screenshot", "browser", "file")
    ):
        return "yellow"
    return "green"


def _approval_required(tool: str, risk_level: str) -> bool:
    return tool == "google-antigravity" or risk_level in {"red", "black"}
