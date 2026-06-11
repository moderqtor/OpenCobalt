"""Multi-model consultation and autonomous subprocess execution."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Generator


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


# ── Subprocess execution ───────────────────────────────────────────────────────

_BINARY_CMDS: dict[str, list[str]] = {
    "claude": ["claude", "--print"],
    "codex": ["codex", "exec"],
    "antigravity": [],
    "ollama": [],  # filled dynamically
}

# Autonomous (yolo) mode flags — bypass all approval prompts for maximum throughput
_AUTONOMOUS_FLAGS: dict[str, list[str]] = {
    "claude": ["--dangerously-skip-permissions"],
    "codex": ["--dangerously-bypass-approvals-and-sandbox", "-s", "danger-full-access"],
    "antigravity": [],
    "ollama": [],
}

_INSTALL_HINTS: dict[str, str] = {
    "claude": "npm install -g @anthropic-ai/claude-code",
    "codex": "npm install -g @openai/codex",
    "gemini": "Gemini CLI is legacy; use google-antigravity with agy",
    "antigravity": "Install Google Antigravity CLI and run agy install",
    "ollama": "brew install ollama && ollama pull llama3",
}

_IMPL_INSTRUCTIONS: dict[str, str] = {
    "impl": (
        "You are an autonomous senior developer with full permission to create and modify files. "
        "Complete the following task entirely. Write all necessary code, create all required files, "
        "and execute the implementation. Make all architectural decisions yourself. "
        "Do not ask for clarification. Begin immediately and finish completely.\n\n"
    ),
    "tests": (
        "You are an autonomous test engineer. Write comprehensive, runnable tests for the following. "
        "Include unit tests, integration tests, and edge cases. Aim for full coverage. "
        "Make all decisions yourself. Do not ask for clarification. Begin immediately.\n\n"
    ),
    "docs": (
        "You are an autonomous technical writer. Write complete, production-quality documentation. "
        "Include API reference, usage examples, architecture notes, and getting-started guide. "
        "Make all decisions yourself. Do not ask for clarification. Begin immediately.\n\n"
    ),
    "review": (
        "You are an autonomous code reviewer. Perform a thorough, expert review. "
        "Identify bugs, security vulnerabilities, performance issues, and code quality problems. "
        "Provide specific, actionable feedback with file and line references. Be comprehensive.\n\n"
    ),
    "analyze": (
        "You are an autonomous systems analyst. Perform deep technical analysis. "
        "Examine architecture, dependencies, performance characteristics, security posture, "
        "and tradeoffs. Provide data-backed insights and concrete recommendations.\n\n"
    ),
    "summarize": (
        "You are an autonomous summarizer. Create a structured, comprehensive summary. "
        "Extract key decisions, outcomes, action items, and open questions. "
        "Format with clear sections. Be thorough and precise.\n\n"
    ),
}


def _best_ollama_model() -> str:
    """Return the best available local ollama model."""
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if not parts:
                continue
            name = parts[0]
            for preferred in ("llama3", "mistral", "gemma", "phi"):
                if preferred in name:
                    return name
            return name  # first available
    except Exception:
        pass
    return "llama3"


def _ollama_cmd() -> list[str]:
    return ["ollama", "run", _best_ollama_model()]


def _antigravity_cmd() -> list[str]:
    from opencobalt.integrations.antigravity_integration import discover_antigravity_runtime

    result = discover_antigravity_runtime()
    capability = result["capabilities"]["non_interactive_mode"]
    evidence = capability.get("evidence")
    if result["installed"] and capability["source"] == "runtime_discovered" and evidence in {"--print", "--prompt"}:
        return ["agy", str(evidence)]
    return []


def _cmd_for(model: str, autonomous: bool = False) -> list[str]:
    if model == "ollama":
        return _ollama_cmd()
    if model in {"antigravity", "google-antigravity", "gemini"}:
        return _antigravity_cmd()
    base = list(_BINARY_CMDS.get(model, [model]))
    if autonomous:
        # Insert autonomy flags after the binary, before the subcommand
        flags = _AUTONOMOUS_FLAGS.get(model, [])
        if flags:
            # For codex: ["codex", "exec", flags...] → keep exec, add flags
            if len(base) > 1:
                base = [base[0]] + flags + base[1:]
            else:
                base = base + flags
    return base


def _build_prompt(task: str, intent: str, task_type: str) -> str:
    if intent == "implement":
        instruction = _IMPL_INSTRUCTIONS.get(task_type, _IMPL_INSTRUCTIONS["impl"])
        return f"{instruction}Task: {task}"
    return (
        f"You are a technical advisor. Task: {task}\n\n"
        "Give your expert analysis in 3-5 bullet points. Be specific and direct."
    )


def consult_subprocess(
    task: str,
    model: str = "claude",
    intent: str = "advise",
    task_type: str = "impl",
    timeout: int | None = None,
    autonomous: bool = True,
) -> str:
    """Call a CLI binary non-interactively and return its full text output.

    intent="advise"      -- quick advisory bullet points (60s timeout)
    intent="implement"   -- full autonomous implementation (600s timeout)
    autonomous=True      -- bypass all approval prompts (yolo mode)
    """
    cmd = _cmd_for(model, autonomous=(autonomous and intent == "implement"))
    binary = cmd[0] if cmd else model

    if not shutil.which(binary):
        hint = _INSTALL_HINTS.get(model, "check tool documentation")
        return f"[{model} unavailable — install: {hint}]"

    prompt = _build_prompt(task, intent, task_type)
    effective_timeout = timeout or (600 if intent == "implement" else 60)

    try:
        result = subprocess.run(
            cmd + [prompt],
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return output or f"[{model}: no output]"
    except subprocess.TimeoutExpired:
        return f"[{model}: timed out after {effective_timeout}s]"
    except Exception as exc:
        return f"[{model}: error — {exc}]"


def stream_subprocess(
    task: str,
    model: str = "claude",
    intent: str = "implement",
    task_type: str = "impl",
    timeout: int = 600,
    autonomous: bool = True,
) -> Generator[str, None, str]:
    """Stream output from a CLI binary line by line.

    Yields each line as it arrives. Returns full output on completion.
    autonomous=True bypasses all approval prompts.
    """
    cmd = _cmd_for(model, autonomous=(autonomous and intent == "implement"))
    binary = cmd[0] if cmd else model

    if not shutil.which(binary):
        hint = _INSTALL_HINTS.get(model, "check tool documentation")
        yield f"[{model} unavailable — install: {hint}]\n"
        return ""

    prompt = _build_prompt(task, intent, task_type)
    collected: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd + [prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None

        # Kill timer
        def _kill():
            if proc.poll() is None:
                proc.kill()

        timer = threading.Timer(timeout, _kill)
        timer.start()
        try:
            for line in proc.stdout:
                collected.append(line)
                yield line
            proc.wait()
        finally:
            timer.cancel()

    except Exception as exc:
        error_line = f"[{model}: error — {exc}]\n"
        collected.append(error_line)
        yield error_line

    return "".join(collected)


def advise_subprocess(task: str, model: str = "ollama", timeout: int = 45) -> str:
    """Quick advisory call — wrapper for the common advise intent."""
    return consult_subprocess(task, model=model, intent="advise", timeout=timeout)


# ── Available models (API-based CouncilSession) ────────────────────────────────

def _available_models() -> list[str]:
    available = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        available.append("claude")
    if os.environ.get("GEMINI_API_KEY"):
        available.append("gemini")
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

    prompt = f"Technical advisor task: {task}\n\nGive 3-5 bullet points of advice. Be direct."
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


# ── Agreement scoring (used by CouncilSession) ─────────────────────────────────

def _build_result(task: str, responses: dict[str, str], synthesize: bool) -> CouncilResult:
    real = {
        m: r for m, r in responses.items()
        if not r.startswith("[skipped") and not r.startswith("[error") and not r.startswith("[unavailable")
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
