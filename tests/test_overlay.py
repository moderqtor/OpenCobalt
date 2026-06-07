"""Tests for the Phase 14 overlay controller."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from opencobalt.core.overlay import OverlayController
from opencobalt.core.telemetry import TelemetryStore


def test_overlay_classifies_simple_prompt_as_route() -> None:
    controller = OverlayController()

    result = controller.classify("summarize this log")

    assert result.mode == "route"


def test_overlay_classifies_multi_part_prompt_as_converge() -> None:
    controller = OverlayController()

    result = controller.classify("build auth with tests and docs")

    assert result.mode == "converge"


def test_overlay_classifies_time_directive_as_auto() -> None:
    controller = OverlayController()

    result = controller.classify("/auto --hours 5 --use-limits max finish this app")

    assert result.mode == "auto"
    assert result.profile == "max"
    assert result.hours == 5


def test_overlay_classifies_open_ended_outcome_as_mission() -> None:
    controller = OverlayController()

    result = controller.classify("/mission --hours 5 make me money")

    assert result.mode == "mission"
    assert result.hours == 5


def test_overlay_dispatch_calls_convergence_for_multi_part_prompt() -> None:
    convergence = MagicMock()
    controller = OverlayController(convergence_runner=convergence)

    outcome = controller.handle_prompt("build auth with tests and docs")

    convergence.assert_called_once()
    assert outcome.mode == "converge"


def test_handle_prompt_creates_telemetry_run(tmp_path) -> None:
    store = TelemetryStore(tmp_path / "telemetry.db")
    mock_score = MagicMock(return_value={"overall": 70, "judge": "heuristic"})

    with patch("opencobalt.core.overlay._get_telemetry_store", return_value=store), \
         patch("opencobalt.core.overlay._score_run", mock_score):
        controller = OverlayController(
            route_runner=lambda _: None,
            convergence_runner=lambda _: MagicMock(id="sess-1", status="converged"),
        )
        controller.handle_prompt("summarize this log")

    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["seed_prompt"] == "summarize this log"
    assert runs[0]["status"] in ("complete", "scored", "failed")
