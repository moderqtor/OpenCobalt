"""Tests for the Phase 14 overlay controller."""

from __future__ import annotations

from unittest.mock import MagicMock

from opencobalt.core.overlay import OverlayController


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
