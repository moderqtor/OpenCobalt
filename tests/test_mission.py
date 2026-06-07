"""Tests for mission planning and permission gates."""

from __future__ import annotations

from pathlib import Path

from opencobalt.core.artifact_bus import ArtifactBus, ArtifactType
from opencobalt.core.autonomy_policy import PermissionEnvelope
from opencobalt.core.ledger import Ledger
from opencobalt.core.mission import MissionPlanner


def test_mission_creates_ranked_plan_artifact(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "ledger.db")
    bus = ArtifactBus(tmp_path / "artifacts.db")
    planner = MissionPlanner(ledger=ledger, artifact_bus=bus)

    mission = planner.plan(
        seed_goal="make me money",
        profile="max",
        envelope=PermissionEnvelope(
            allowed_actions=["local-build", "draft-content"],
            denied_actions=["purchases", "messages"],
        ),
    )

    artifact = bus.latest(ArtifactType.RANKED_PLAN, mission["run_id"])
    assert artifact is not None
    assert "local-build" in artifact.content
    assert mission["selected_plan"]["allowed_actions"] == ["local-build", "draft-content"]


def test_mission_denies_disallowed_external_action(tmp_path: Path) -> None:
    planner = MissionPlanner(
        ledger=Ledger(tmp_path / "ledger.db"),
        artifact_bus=ArtifactBus(tmp_path / "artifacts.db"),
    )

    result = planner.validate_action(
        "purchases",
        PermissionEnvelope(allowed_actions=["local-build"], denied_actions=["purchases"]),
    )

    assert result.allowed is False
    assert "not permitted" in result.reason
