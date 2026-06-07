"""Multi-dimensional run scorer using OllamaJudge + heuristics."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .ollama_judge import OllamaJudge
from .telemetry import TelemetryStore

_WEIGHTS = {
    "output_quality": 0.25,
    "prompt_adherence": 0.15,
    "token_efficiency": 0.12,
    "tool_appropriateness": 0.10,
    "novel_ideation": 0.10,
    "context_handling": 0.08,
    "latency_score": 0.08,
    "task_decomposition": 0.06,
    "agent_selection": 0.05,
    "convergence_quality": 0.01,
}


class ScoringEngine:
    def __init__(self, store: TelemetryStore, judge: OllamaJudge | None = None) -> None:
        self._store = store
        self._judge = judge or OllamaJudge()

    def score(self, run_id: str) -> dict:
        run = self._store.get_run(run_id)
        if run is None:
            raise ValueError(f"Unknown run: {run_id}")

        events = self._store.list_events(run_id)
        heuristics = self._compute_heuristics(run, events)

        qualitative = self._judge.judge(
            prompt=run["seed_prompt"],
            output=run.get("raw_output") or "",
            heuristics=heuristics,
        )

        token_efficiency = _score_token_efficiency(heuristics)
        latency_score = _score_latency(heuristics)
        convergence_quality = _score_convergence(heuristics)

        all_scores: dict[str, int] = {}
        for k in _WEIGHTS:
            if k in ("token_efficiency", "latency_score", "convergence_quality"):
                continue
            val = qualitative.get(k, 50)
            try:
                all_scores[k] = max(1, min(100, int(val)))
            except (ValueError, TypeError):
                all_scores[k] = 50
        all_scores["token_efficiency"] = token_efficiency
        all_scores["latency_score"] = latency_score
        all_scores["convergence_quality"] = convergence_quality
        overall = round(sum(all_scores[cat] * w for cat, w in _WEIGHTS.items()))

        judge_label = qualitative.get("_judge", self._judge.judge_name)

        score = {
            "run_id": run_id,
            "scored_at": datetime.now(tz=timezone.utc).isoformat(),
            "judge": judge_label,
            "overall": overall,
            **all_scores,
            "judge_reasoning": qualitative.get("reasoning", ""),
            "heuristics": heuristics,
        }

        self._store.save_score(score)

        if summary := qualitative.get("summary"):
            self._store.set_summary(run_id, summary)

        return score

    def _compute_heuristics(self, run: dict, events: list[dict]) -> dict:
        def _payloads(etype: str) -> list[dict]:
            return [json.loads(e["payload_json"]) for e in events if e["event_type"] == etype]

        tool_events = _payloads("tool_use")
        retry_events = _payloads("retry")
        gate_pass = [e for e in events if e["event_type"] == "gate_pass"]
        gate_fail = [e for e in events if e["event_type"] == "gate_fail"]

        distinct_tools = len({p.get("tool", "") for p in tool_events} - {""})
        total_gates = len(gate_pass) + len(gate_fail)
        gate_pass_rate = len(gate_pass) / total_gates if total_gates > 0 else 1.0

        token_in = run.get("token_count_in") or 0
        token_out = run.get("token_count_out") or 0
        if token_out > 0 and token_in > 0:
            token_ratio = token_out / token_in
        else:
            raw_out = run.get("raw_output") or ""
            seed = run.get("seed_prompt") or ""
            token_ratio = len(raw_out) / max(len(seed), 1)

        return {
            "token_count_in": token_in,
            "token_count_out": token_out,
            "token_ratio": round(token_ratio, 2),
            "distinct_tool_count": distinct_tools,
            "retry_count": len(retry_events),
            "latency_ms": run.get("latency_ms") or 0,
            "gate_pass_rate": round(gate_pass_rate, 2),
            "total_gates": total_gates,
            "artifacts_produced": run.get("artifacts_produced") or 0,
        }


def _score_token_efficiency(h: dict) -> int:
    ratio = h["token_ratio"]
    if ratio >= 5:
        return 90
    if ratio >= 3:
        return 75
    if ratio >= 1.5:
        return 60
    if ratio >= 0.5:
        return 45
    return 30


def _score_latency(h: dict) -> int:
    ms = h["latency_ms"]
    if ms == 0:
        return 70
    if ms < 5_000:
        return 95
    if ms < 15_000:
        return 85
    if ms < 30_000:
        return 75
    if ms < 60_000:
        return 65
    if ms < 120_000:
        return 55
    return 40


def _score_convergence(h: dict) -> int:
    base = int(h["gate_pass_rate"] * 80) + 20
    penalty = min(h["retry_count"] * 5, 30)
    return max(base - penalty, 1)
