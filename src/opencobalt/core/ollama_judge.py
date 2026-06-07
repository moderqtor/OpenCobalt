"""Ollama-backed judge for multi-dimensional run scoring."""
from __future__ import annotations

import json
import subprocess

_QUALITATIVE_KEYS = [
    "output_quality",
    "prompt_adherence",
    "novel_ideation",
    "context_handling",
    "tool_appropriateness",
    "task_decomposition",
    "agent_selection",
]

_FALLBACK = 50

_PROMPT_TEMPLATE = """\
You are a precise AI output evaluator. Score the following AI task run.

## Original Prompt
{prompt}

## Output
{output}

## Heuristic Signals
{heuristics}

## Instructions
Return ONLY valid JSON with these exact keys. Each value is an integer 1-100.
"reasoning" is a 2-3 sentence explanation of the overall score.
"summary" is a 2-3 sentence description of what was done and the result.

{{
  "output_quality": <int>,
  "prompt_adherence": <int>,
  "novel_ideation": <int>,
  "context_handling": <int>,
  "tool_appropriateness": <int>,
  "task_decomposition": <int>,
  "agent_selection": <int>,
  "reasoning": "<string>",
  "summary": "<string>"
}}

Score strictly. 50 = average. 80+ = genuinely good. 95+ = exceptional.\
"""

_MAX_OUTPUT_CHARS = 4000
_OLLAMA_TIMEOUT_SECONDS = 15


class OllamaJudge:
    def __init__(self, model: str = "llama3") -> None:
        self.model = model

    @property
    def judge_name(self) -> str:
        return f"ollama:{self.model}"

    def judge(self, *, prompt: str, output: str, heuristics: dict) -> dict:
        truncated = output[:_MAX_OUTPUT_CHARS]
        scoring_prompt = _PROMPT_TEMPLATE.format(
            prompt=prompt,
            output=truncated,
            heuristics=json.dumps(heuristics, indent=2),
        )
        raw = self._call_ollama(scoring_prompt)
        if raw is None:
            return self._fallback()
        return self._parse(raw)

    def _call_ollama(self, prompt: str) -> str | None:
        try:
            result = subprocess.run(
                ["ollama", "run", self.model, prompt],
                capture_output=True,
                text=True,
                timeout=_OLLAMA_TIMEOUT_SECONDS,
            )
            return result.stdout if result.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    def _parse(self, raw: str) -> dict:
        decoder = json.JSONDecoder()
        data = None
        for i, ch in enumerate(raw):
            if ch == "{":
                try:
                    data, _ = decoder.raw_decode(raw, i)
                    break
                except json.JSONDecodeError:
                    continue
        if data is None:
            return self._fallback()

        result: dict[str, object] = {}
        for key in _QUALITATIVE_KEYS:
            val = data.get(key, _FALLBACK)
            if isinstance(val, (int, float)):
                result[key] = max(1, min(100, int(val)))
            else:
                result[key] = _FALLBACK

        result["reasoning"] = str(data.get("reasoning", ""))
        result["summary"] = str(data.get("summary", ""))
        result["_judge"] = self.judge_name
        return result

    def _fallback(self) -> dict:
        result: dict[str, object] = {key: _FALLBACK for key in _QUALITATIVE_KEYS}
        result["reasoning"] = ""
        result["summary"] = ""
        result["_judge"] = "heuristic"
        return result
