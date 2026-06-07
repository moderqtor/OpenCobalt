"""Gate-based convergence checker. TestsGate runs pytest; VerifierGate calls critic agent."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable

_VERIFIER_THRESHOLD = 0.75

_VERIFIER_PROMPT = (
    "Review this diff against the task description.\n"
    "Task: {task}\n\nDiff:\n{diff}\n\n"
    "Score 0.0-1.0. Reply with JSON only:\n"
    '{{"score": <float>, "approved": <bool>, "feedback": "<str>"}}'
)


@dataclass
class ConvergenceResult:
    passed: bool
    tests_ok: bool | None
    verifier_ok: bool | None
    verifier_score: float | None
    retry_count: int
    feedback: str


class TestsGate:
    """Run pytest and report pass/fail. Injectable for testing."""

    __test__ = False

    def __init__(
        self,
        run_tests: Callable[[], tuple[bool, str]] | None = None,
    ) -> None:
        self._run_tests = run_tests or self._default_run

    def _default_run(self) -> tuple[bool, str]:
        result = subprocess.run(
            ["python3", "-m", "pytest", "-q"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = (result.stdout + result.stderr)[:5000]
        return result.returncode == 0, output

    def check(self) -> tuple[bool, str]:
        return self._run_tests()


class VerifierGate:
    """Send diff to critic agent (Gemini or Claude). Injectable for testing."""

    def __init__(
        self,
        consult: Callable[[str], str] | None = None,
        threshold: float = _VERIFIER_THRESHOLD,
    ) -> None:
        self._consult = consult or self._default_consult
        self._threshold = threshold

    def _default_consult(self, prompt: str) -> str:
        import shutil

        from .council import consult_subprocess

        model = "gemini" if shutil.which("gemini") else "claude"
        return consult_subprocess(prompt, model=model, intent="advise", timeout=60)

    def check(self, task: str, diff: str) -> tuple[bool, float, str]:
        prompt = _VERIFIER_PROMPT.format(task=task, diff=diff)
        raw = self._consult(prompt)
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end]) if start >= 0 and end > start else {}
            score = float(data.get("score", 0.0))
            feedback = str(data.get("feedback", ""))
        except (ValueError, KeyError, json.JSONDecodeError):
            return False, 0.0, f"verifier parse error: {raw[:200]}"

        return score >= self._threshold, score, feedback


class ConvergenceChecker:
    """Select and run gates based on task types present in the session."""

    _GATE_MAP: dict[str, set[str]] = {
        "impl":      {"tests", "verifier"},
        "refactor":  {"tests"},
        "tests":     {"tests"},
        "docs":      {"verifier"},
        "review":    {"verifier"},
        "analyze":   {"verifier"},
        "summarize": {"verifier"},
    }

    def __init__(
        self,
        tests_gate: TestsGate | None = None,
        verifier_gate: VerifierGate | None = None,
    ) -> None:
        self._tests_gate = tests_gate or TestsGate()
        self._verifier_gate = verifier_gate or VerifierGate()

    def _required_gates(self, task_types: list[str]) -> set[str]:
        required: set[str] = set()
        for tt in task_types:
            required |= self._GATE_MAP.get(tt, {"verifier"})
        return required

    def check(
        self,
        task_types: list[str],
        task: str = "",
        diff: str = "",
        retry_count: int = 0,
        telemetry_session=None,
    ) -> ConvergenceResult:
        gates = self._required_gates(task_types)
        tests_ok: bool | None = None
        verifier_ok: bool | None = None
        verifier_score: float | None = None
        feedback_parts: list[str] = []

        if "tests" in gates:
            ok, output = self._tests_gate.check()
            tests_ok = ok
            if not ok:
                feedback_parts.append(f"tests failed:\n{output[:500]}")
            if telemetry_session is not None:
                if ok:
                    telemetry_session.record_gate_pass("tests")
                else:
                    telemetry_session.record_gate_fail("tests", output[:200])

        if "verifier" in gates:
            ok, score, fb = self._verifier_gate.check(task, diff)
            verifier_ok = ok
            verifier_score = score
            if not ok:
                feedback_parts.append(f"verifier score {score:.2f}: {fb}")
            if telemetry_session is not None:
                if ok:
                    telemetry_session.record_gate_pass("verifier")
                else:
                    telemetry_session.record_gate_fail("verifier", fb[:200])

        passed = (tests_ok is not False) and (verifier_ok is not False)
        feedback = "\n".join(feedback_parts) if feedback_parts else "all gates passed"

        return ConvergenceResult(
            passed=passed,
            tests_ok=tests_ok,
            verifier_ok=verifier_ok,
            verifier_score=verifier_score,
            retry_count=retry_count,
            feedback=feedback,
        )
