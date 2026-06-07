"""Default prompt overlay for Phase 14 autonomy routing."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass

from .ledger import Ledger
from .router import route_task


@dataclass(frozen=True)
class PromptClassification:
    mode: str
    prompt: str
    profile: str = "balanced"
    hours: float | None = None
    allowed_actions: list[str] | None = None
    denied_actions: list[str] | None = None


@dataclass(frozen=True)
class OverlayOutcome:
    mode: str
    summary: str
    run_id: str | None = None


class OverlayController:
    """Classify shell prompts and dispatch to the right local runtime."""

    def __init__(
        self,
        *,
        ledger: Ledger | None = None,
        route_runner: Callable[[str], object] | None = None,
        convergence_runner: Callable[[str], object] | None = None,
        auto_runner: Callable[[str], object] | None = None,
        mission_runner: Callable[[str], object] | None = None,
    ) -> None:
        self._ledger = ledger or Ledger()
        self._route_runner = route_runner
        self._convergence_runner = convergence_runner
        self._auto_runner = auto_runner
        self._mission_runner = mission_runner

    def classify(self, text: str) -> PromptClassification:
        raw = text.strip()
        lower = raw.lower()
        if lower.startswith("/auto"):
            return self._classify_auto(raw[5:].strip())
        if lower.startswith("/mission"):
            return self._classify_mission(raw[8:].strip())
        if self._looks_like_mission(lower):
            return PromptClassification(mode="mission", prompt=raw)
        if self._looks_like_auto(lower):
            return PromptClassification(mode="auto", prompt=raw, hours=self._extract_hours(raw))
        if self._looks_like_convergence(lower):
            return PromptClassification(mode="converge", prompt=raw)
        return PromptClassification(mode="route", prompt=raw)

    def handle_prompt(self, text: str) -> OverlayOutcome:
        classification = self.classify(text)
        if classification.mode == "route":
            return self._handle_route(classification.prompt)
        if classification.mode == "converge":
            return self._handle_converge(classification.prompt)
        if classification.mode == "auto":
            return self._handle_auto(classification)
        if classification.mode == "mission":
            return self._handle_mission(classification)
        raise ValueError(f"unknown overlay mode: {classification.mode}")

    def _handle_route(self, prompt: str) -> OverlayOutcome:
        if self._route_runner is not None:
            self._route_runner(prompt)
            return OverlayOutcome(mode="route", summary="routed")
        decision = route_task(prompt, record=False)
        self._ledger.insert_route_decision(decision)
        return OverlayOutcome(mode="route", summary=decision.recommended_tool)

    def _handle_converge(self, prompt: str) -> OverlayOutcome:
        if self._convergence_runner is not None:
            result = self._convergence_runner(prompt)
            run_id = getattr(result, "id", None)
            return OverlayOutcome(mode="converge", summary="convergence run started", run_id=run_id)
        from .convergence_orchestrator import ConvergenceOrchestrator

        session = ConvergenceOrchestrator(ledger=self._ledger).run(prompt)
        return OverlayOutcome(mode="converge", summary=session.status, run_id=session.id)

    def _handle_auto(self, classification: PromptClassification) -> OverlayOutcome:
        prompt = classification.prompt
        if self._auto_runner is not None:
            result = self._auto_runner(prompt)
            run_id = getattr(result, "id", None)
            return OverlayOutcome(mode="auto", summary="autonomy run started", run_id=run_id)
        from .autonomy_engine import AutonomyEngine

        run = AutonomyEngine(ledger=self._ledger).start(
            prompt,
            profile=classification.profile,
            hours=classification.hours or 5.0,
            allowed_actions=classification.allowed_actions or [],
            denied_actions=classification.denied_actions or [],
        )
        return OverlayOutcome(mode="auto", summary=run["status"], run_id=run["id"])

    def _handle_mission(self, classification: PromptClassification) -> OverlayOutcome:
        prompt = classification.prompt
        if self._mission_runner is not None:
            result = self._mission_runner(prompt)
            run_id = result.get("run_id") if isinstance(result, dict) else getattr(result, "id", None)
            return OverlayOutcome(mode="mission", summary="mission planned", run_id=run_id)
        from .autonomy_policy import PermissionEnvelope
        from .mission import MissionPlanner

        mission = MissionPlanner(ledger=self._ledger).plan(
            seed_goal=prompt,
            profile=classification.profile,
            envelope=PermissionEnvelope(
                allowed_actions=classification.allowed_actions or [],
                denied_actions=classification.denied_actions or [],
            ),
        )
        return OverlayOutcome(mode="mission", summary="mission planned", run_id=mission["run_id"])

    def _classify_auto(self, text: str) -> PromptClassification:
        parsed = _parse_overlay_args(text)
        return PromptClassification(
            mode="auto",
            prompt=parsed["prompt"],
            profile=parsed["profile"],
            hours=parsed["hours"],
            allowed_actions=parsed["allowed"],
            denied_actions=parsed["denied"],
        )

    def _classify_mission(self, text: str) -> PromptClassification:
        parsed = _parse_overlay_args(text)
        return PromptClassification(
            mode="mission",
            prompt=parsed["prompt"],
            profile=parsed["profile"],
            hours=parsed["hours"],
            allowed_actions=parsed["allowed"],
            denied_actions=parsed["denied"],
        )

    def _looks_like_convergence(self, lower: str) -> bool:
        has_impl = any(word in lower for word in ("build", "implement", "create", "add", "fix"))
        has_multiple_outputs = " and " in lower or any(word in lower for word in ("tests", "docs"))
        return has_impl and has_multiple_outputs

    def _looks_like_auto(self, lower: str) -> bool:
        return "--hours" in lower or "use-limits" in lower or "for hours" in lower

    def _looks_like_mission(self, lower: str) -> bool:
        return "make me money" in lower or "launch a business" in lower or "open-ended" in lower

    def _extract_hours(self, text: str) -> float | None:
        parts = shlex.split(text)
        for index, token in enumerate(parts):
            if token == "--hours" and index + 1 < len(parts):
                return _to_float(parts[index + 1])
        return None


def _parse_overlay_args(text: str) -> dict:
    parts = shlex.split(text)
    prompt_parts: list[str] = []
    profile = "balanced"
    hours: float | None = None
    allowed: list[str] = []
    denied: list[str] = []
    index = 0
    while index < len(parts):
        token = parts[index]
        if token == "--hours" and index + 1 < len(parts):
            hours = _to_float(parts[index + 1])
            index += 2
            continue
        if token in {"--use-limits", "--profile"} and index + 1 < len(parts):
            profile = parts[index + 1]
            index += 2
            continue
        if token == "--allow" and index + 1 < len(parts):
            allowed = _split_actions(parts[index + 1])
            index += 2
            continue
        if token == "--deny" and index + 1 < len(parts):
            denied = _split_actions(parts[index + 1])
            index += 2
            continue
        prompt_parts.append(token)
        index += 1
    return {
        "prompt": " ".join(prompt_parts).strip(),
        "profile": profile,
        "hours": hours,
        "allowed": allowed,
        "denied": denied,
    }


def _split_actions(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None
