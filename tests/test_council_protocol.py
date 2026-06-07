"""Tests for Phase 14 typed council artifacts."""

from __future__ import annotations

from pathlib import Path

from opencobalt.core.artifact_bus import ArtifactBus, ArtifactType
from opencobalt.core.council_protocol import CouncilProtocol


def test_council_protocol_publishes_typed_artifact(tmp_path: Path) -> None:
    bus = ArtifactBus(tmp_path / "artifacts.db")
    protocol = CouncilProtocol(bus)

    artifact = protocol.publish(
        session_id="run-1",
        mode="coordinate",
        artifact_type=ArtifactType.HANDOFF,
        content="tests should start after implementation",
        producer="codex-cli",
    )

    saved = bus.latest(ArtifactType.HANDOFF, "run-1")
    assert saved is not None
    assert saved.id == artifact.id
    assert saved.metadata["council_mode"] == "coordinate"


def test_council_protocol_rejects_unknown_mode(tmp_path: Path) -> None:
    protocol = CouncilProtocol(ArtifactBus(tmp_path / "artifacts.db"))

    try:
        protocol.publish(
            session_id="run-1",
            mode="chat",
            artifact_type=ArtifactType.CLAIM,
            content="unstructured",
        )
    except ValueError as exc:
        assert "mode" in str(exc)
    else:
        raise AssertionError("unknown council mode should fail")


def test_phase14_artifact_types_are_registered() -> None:
    assert ArtifactType.PROPOSAL == "proposal"
    assert ArtifactType.OBJECTION == "objection"
    assert ArtifactType.RANKED_PLAN == "ranked_plan"
