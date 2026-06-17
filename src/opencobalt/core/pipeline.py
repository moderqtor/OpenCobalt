"""Pipeline executor for ordered tool steps."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .runtime_boundary import legacy_runtime_block_message, normalize_runtime_id


@dataclass
class PipelineStep:
    tool: str
    hint: str = ""


@dataclass
class PipelineResult:
    task: str
    run_id: str
    steps_completed: int
    steps_total: int
    success: bool
    output_dir: Path
    errors: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(self, output_dir: Path | None = None) -> None:
        self._output_dir = output_dir or (Path(".opencobalt") / "pipelines")

    def parse(self, expr: str) -> tuple[str, list[PipelineStep]]:
        """Parse /pipe "task" -> step1 -> step2 into a task and step list."""
        expr = re.sub(r"^/?pipe\s*", "", expr.strip())

        match = re.match(r'"([^"]+)"\s*(.*)', expr)
        if not match:
            match = re.match(r"'([^']+)'\s*(.*)", expr)
        if not match:
            raise ValueError('Pipeline task must be quoted: /pipe "task" -> ...')
        task = match.group(1).strip()
        rest = match.group(2).strip()

        if not rest:
            raise ValueError('No steps defined. Example: /pipe "task" -> claude -> /verify')

        raw_steps = [step.strip() for step in re.split(r"→|->", rest) if step.strip()]
        steps = []
        for raw in raw_steps:
            raw = raw.lstrip("/").strip()
            if raw.startswith("note "):
                steps.append(PipelineStep(tool="note", hint=raw[5:].strip()))
            elif raw.startswith("verify"):
                steps.append(PipelineStep(tool="verify"))
            else:
                parts = raw.split(None, 1)
                tool = parts[0].lower()
                hint = parts[1].strip() if len(parts) > 1 else ""
                steps.append(PipelineStep(tool=tool, hint=hint))

        if not steps:
            raise ValueError("No steps defined.")
        return task, steps

    def run(self, task: str, steps: list[PipelineStep]) -> PipelineResult:
        run_id = str(uuid.uuid4())[:8]
        run_dir = self._output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        context = f"Task: {task}"
        errors = []

        for index, step in enumerate(steps):
            out_path = self._step_output_path(run_id, index)
            result = self._run_step(step, context, out_path)
            if not result:
                errors.append(f"Step {index + 1} ({step.tool}) failed or was skipped")
                return PipelineResult(
                    task=task,
                    run_id=run_id,
                    steps_completed=index,
                    steps_total=len(steps),
                    success=False,
                    output_dir=run_dir,
                    errors=errors,
                )
            if out_path.exists():
                context = out_path.read_text(encoding="utf-8", errors="ignore")

        return PipelineResult(
            task=task,
            run_id=run_id,
            steps_completed=len(steps),
            steps_total=len(steps),
            success=True,
            output_dir=run_dir,
            errors=errors,
        )

    def _run_step(self, step: PipelineStep, context: str, out_path: Path) -> bool:
        if step.tool == "note":
            out_path.write_text(step.hint, encoding="utf-8")
            return True

        if step.tool == "verify":
            from .ledger import Ledger
            from .verify import run_all

            results = run_all(root=Path("."), ledger=Ledger())
            out_path.write_text("\n".join(result.output_summary for result in results))
            return all(result.passed for result in results)

        if normalize_runtime_id(step.tool) is None:
            out_path.write_text(f"[{step.tool} not available]")
            return False

        _ = context
        out_path.write_text(legacy_runtime_block_message(step.tool), encoding="utf-8")
        return False

    def _step_output_path(self, run_id: str, step_index: int) -> Path:
        run_dir = self._output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir / f"step-{step_index}.txt"
