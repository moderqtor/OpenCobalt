"""Typed council artifact publishing."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping

from .artifact_bus import AgentArtifact, ArtifactBus

_VALID_MODES = {"advise", "coordinate", "review", "ideate", "resolve"}


class CouncilProtocol:
    """Publish council records through the artifact bus."""

    def __init__(self, artifact_bus: ArtifactBus | None = None) -> None:
        self._bus = artifact_bus or ArtifactBus()

    def publish(
        self,
        *,
        session_id: str,
        mode: str,
        artifact_type: str,
        content: str,
        producer: str = "council",
        iteration: int = 0,
        wave: int = 0,
        metadata: Mapping[str, object] | None = None,
    ) -> AgentArtifact:
        if mode not in _VALID_MODES:
            valid = ", ".join(sorted(_VALID_MODES))
            raise ValueError(f"unknown council mode {mode!r}; expected one of {valid}")

        artifact_metadata = dict(metadata or {})
        artifact_metadata["council_mode"] = mode
        artifact = AgentArtifact(
            id=str(uuid.uuid4()),
            session_id=session_id,
            iteration=iteration,
            wave=wave,
            producer=producer,
            type=artifact_type,
            content=content,
            metadata=artifact_metadata,
            timestamp=time.time(),
        )
        self._bus.publish(artifact)
        return artifact
