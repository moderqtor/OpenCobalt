"""Inspectable request lifecycle phases and bounded phase timings.

Phase names are durable and UI-facing. They distinguish OpenCobalt work
(routing, discovery, verification) from provider runtime so a slow catalog
or preflight step is not reported as a slow model.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Literal

LifecyclePhase = Literal[
    "interpreting",
    "checking_capabilities",
    "routing",
    "starting_provider",
    "running",
    "verifying",
    "persisting",
    "complete",
    "failed",
    "cancelled",
    "blocked",
]

TERMINAL_PHASES = frozenset({"complete", "failed", "cancelled", "blocked"})
CANCELLABLE_PHASES = frozenset(
    {
        "interpreting",
        "checking_capabilities",
        "routing",
        "starting_provider",
        "running",
        "verifying",
        "persisting",
    }
)

_PHASE_TIMING_KEYS = {
    "interpreting": "interpretation_ms",
    "checking_capabilities": "discovery_ms",
    "routing": "routing_ms",
    "starting_provider": "provider_start_ms",
    "running": "provider_runtime_ms",
    "verifying": "verification_ms",
    "persisting": "persist_ms",
}

_OUTCOME_FOR_PHASE = {
    "interpreting": "interpreting",
    "checking_capabilities": "checking_capabilities",
    "routing": "routing",
    "starting_provider": "starting",
    "running": "running",
    "verifying": "verifying",
    "persisting": "persisting",
    "complete": "complete",
    "failed": "failed",
    "cancelled": "cancelled",
    "blocked": "blocked",
}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class RequestLifecycle:
    """Mutable per-request phase clock used by ChatService."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.started_monotonic = time.monotonic()
        self.started_at = _now()
        self.phase: LifecyclePhase = "interpreting"
        self._phase_started = self.started_monotonic
        self.phases: list[dict[str, Any]] = []
        self.timings: dict[str, int] = {}

    def enter(self, phase: LifecyclePhase) -> dict[str, Any]:
        now = time.monotonic()
        duration_ms = max(0, int((now - self._phase_started) * 1000))
        previous = self.phase
        if previous not in TERMINAL_PHASES:
            key = _PHASE_TIMING_KEYS.get(previous)
            if key is not None:
                self.timings[key] = self.timings.get(key, 0) + duration_ms
            self.phases.append(
                {
                    "phase": previous,
                    "duration_ms": duration_ms,
                    "completed_at": _now().isoformat(),
                }
            )
        self.phase = phase
        self._phase_started = now
        self.timings["total_ms"] = max(0, int((now - self.started_monotonic) * 1000))
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        current_ms = max(0, int((now - self._phase_started) * 1000))
        return {
            "phase": self.phase,
            "outcome_status": outcome_status_for_phase(self.phase),
            "started_at": self.started_at.isoformat(),
            "current_phase_ms": current_ms,
            "phases": list(self.phases),
            "timings": {
                **self.timings,
                "total_ms": max(0, int((now - self.started_monotonic) * 1000)),
            },
        }


def outcome_status_for_phase(phase: LifecyclePhase) -> str:
    return _OUTCOME_FOR_PHASE[phase]


def phase_label(phase: str, *, provider_id: str | None = None, model_id: str | None = None) -> str:
    """Short UI copy. Does not claim the provider is slow before invocation."""
    if phase == "interpreting":
        return "Interpreting request"
    if phase == "checking_capabilities":
        return "Checking capabilities"
    if phase == "routing":
        return "Routing"
    if phase == "starting_provider":
        target = _provider_target(provider_id, model_id)
        return f"Starting {target}" if target else "Starting provider"
    if phase == "running":
        target = _provider_target(provider_id, model_id)
        return f"Provider running ({target})" if target else "Provider running"
    if phase == "verifying":
        return "Verifying"
    if phase == "persisting":
        return "Saving"
    if phase == "complete":
        return "Complete"
    if phase == "cancelled":
        return "Cancelled"
    if phase == "blocked":
        return "Blocked"
    if phase == "failed":
        return "Failed"
    return phase.replace("_", " ")


def _provider_target(provider_id: str | None, model_id: str | None) -> str:
    parts = [part for part in (model_id, provider_id) if part]
    return " via ".join(parts[:2])
