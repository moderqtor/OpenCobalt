"""Open-ended mission planning with permission gates."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass

from .artifact_bus import AgentArtifact, ArtifactBus, ArtifactType
from .autonomy_engine import AutonomyEngine
from .autonomy_policy import PermissionEnvelope
from .ledger import Ledger


@dataclass(frozen=True)
class ActionValidation:
    allowed: bool
    reason: str


class MissionPlanner:
    """Plan missions as durable autonomy runs and ranked plan artifacts."""

    def __init__(
        self,
        ledger: Ledger | None = None,
        artifact_bus: ArtifactBus | None = None,
    ) -> None:
        self.ledger = ledger or Ledger()
        self.artifact_bus = artifact_bus or ArtifactBus()

    def plan(
        self,
        seed_goal: str,
        profile: str,
        envelope: PermissionEnvelope,
        telemetry_session=None,
    ) -> dict:
        """Create a mission run and publish the selected deterministic plan."""
        engine = AutonomyEngine(ledger=self.ledger)
        run = engine.start(
            seed_goal,
            profile=profile,
            allowed_actions=envelope.allowed_actions,
            denied_actions=envelope.denied_actions,
        )
        selected_plan = {
            "title": "Local-first mission plan",
            "seed_goal": seed_goal,
            "profile": profile,
            "allowed_actions": list(envelope.allowed_actions),
            "denied_actions": list(envelope.denied_actions),
            "rank": 1,
            "rationale": "Selected deterministic local-first plan within the permission envelope.",
        }

        artifact = AgentArtifact(
            id=str(uuid.uuid4()),
            session_id=run["id"],
            iteration=0,
            wave=0,
            producer="mission-planner",
            type=ArtifactType.RANKED_PLAN,
            content=json.dumps(selected_plan, sort_keys=True),
            metadata={"profile": profile, "rank": 1},
            timestamp=time.time(),
        )
        self.artifact_bus.publish(artifact)

        return {
            "run_id": run["id"],
            "selected_plan": selected_plan,
            "artifact_id": artifact.id,
        }

    def validate_action(
        self,
        action: str,
        envelope: PermissionEnvelope,
    ) -> ActionValidation:
        """Check whether an action is permitted by the run envelope."""
        if envelope.permits(action):
            return ActionValidation(
                allowed=True,
                reason=f"Action '{action}' is permitted by the run envelope.",
            )
        return ActionValidation(
            allowed=False,
            reason=f"Action '{action}' is not permitted by the run envelope.",
        )
