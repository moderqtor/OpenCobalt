"""Optional markdown export for scored telemetry runs."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


class MarkdownExporter:
    def export_run(self, run: dict, score: dict, output_dir: Path) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        dt = datetime.fromtimestamp(run["started_at"], tz=timezone.utc)
        timestamp_str = dt.strftime("%Y-%m-%d_%H%M%S")
        run_type = run["run_type"]
        run_id_short = run["id"][:8]
        filename = f"{timestamp_str}_{run_type}_{run_id_short}.md"
        filepath = output_dir / filename

        related = self._find_related(run_type, filepath.stem, output_dir)
        content = self._render(run, score, related)
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def _find_related(self, run_type: str, current_stem: str, output_dir: Path) -> list[str]:
        pattern = re.compile(
            rf"\d{{4}}-\d{{2}}-\d{{2}}_\d{{6}}_{re.escape(run_type)}_[0-9a-f]{{8}}"
        )
        candidates = [
            f.stem
            for f in sorted(output_dir.glob(f"*_{run_type}_*.md"), reverse=True)
            if f.stem != current_stem and pattern.match(f.stem)
        ]
        return candidates[:3]

    def _render(self, run: dict, score: dict, related: list[str]) -> str:
        tool_calls = json.loads(run.get("tool_calls_json") or "[]")
        skills = json.loads(run.get("skills_used_json") or "[]")
        connectors = json.loads(run.get("connectors_used_json") or "[]")
        latency_s = f"{run['latency_ms'] // 1000}s" if run.get("latency_ms") else "unknown"
        related_links = ", ".join(f"[[{r}]]" for r in related)

        lines = [
            "---",
            f"id: {run['id']}",
            f"date: {_iso(run['started_at'])}",
            f"run_type: {run['run_type']}",
            f"agent: {run['agent_id']}",
            f"model: {run.get('model_used', '')}",
            f"overall_score: {score['overall']}",
            f"tags: [{run['run_type']}, {run['agent_id']}]",
        ]
        if related_links:
            lines.append(f"related: {related_links}")
        lines += [
            "---",
            "",
            f"# Run: {run['seed_prompt']}",
            "",
            f"**Score:** {score['overall']}/100 | **Judge:** {score['judge']}",
            "",
            "## Summary",
            "",
            run.get("summary") or "_No summary available._",
            "",
            "## Scores",
            "",
            "| Category | Score |",
            "|---|---|",
            f"| Output Quality | {score.get('output_quality', '-')} |",
            f"| Prompt Adherence | {score.get('prompt_adherence', '-')} |",
            f"| Novel Ideation | {score.get('novel_ideation', '-')} |",
            f"| Context Handling | {score.get('context_handling', '-')} |",
            f"| Tool Appropriateness | {score.get('tool_appropriateness', '-')} |",
            f"| Token Efficiency | {score.get('token_efficiency', '-')} |",
            f"| Latency | {score.get('latency_score', '-')} |",
            f"| Task Decomposition | {score.get('task_decomposition', '-')} |",
            f"| Agent Selection | {score.get('agent_selection', '-')} |",
            f"| Convergence Quality | {score.get('convergence_quality', '-')} |",
            "",
        ]
        if score.get("judge_reasoning"):
            lines += ["## Reasoning", "", score["judge_reasoning"], ""]
        lines += [
            "## Run Details",
            "",
            f"- **Tools used:** {', '.join(tool_calls) or 'none'}",
            f"- **Skills used:** {', '.join(skills) or 'none'}",
            f"- **Connectors used:** {', '.join(connectors) or 'none'}",
            f"- **Retries:** {run.get('retry_count', 0)} | **Latency:** {latency_s}",
            f"- **Tokens:** {run.get('token_count_in') or '?'} in / {run.get('token_count_out') or '?'} out",
            "",
        ]
        return "\n".join(lines)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
