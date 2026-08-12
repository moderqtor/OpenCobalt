"""Durable coding missions for Cursor ACP repository work."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from opencobalt.core.mission_engine import Mission, MissionStore
from opencobalt.personal_ai.store import PersonalAIStore


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


class CodingMissionStore:
    """Persist coding-agent work without treating ACP as source of truth."""

    def __init__(self, store: PersonalAIStore, missions: MissionStore) -> None:
        self.store = store
        self.missions = missions

    def create(
        self,
        *,
        objective: str,
        repository_path: str,
        conversation_id: str | None,
        route_id: str | None,
        capability_role: str,
        provider_id: str | None = None,
        acp_session_id: str | None = None,
    ) -> dict[str, Any]:
        started = _iso()
        mission = Mission(
            mission_id=_uid("mis"),
            goal=objective,
            mission_type="coding",
            status="created",
            max_risk="yellow",
            summary="Coding mission created; Cursor ACP has not finished.",
        )
        self.missions.save_mission(mission)
        record = {
            "coding_id": _uid("cod"),
            "mission_id": mission.mission_id,
            "conversation_id": conversation_id,
            "route_id": route_id,
            "objective": objective,
            "repository_path": repository_path,
            "status": "running",
            "acp_session_id": acp_session_id,
            "capability_role": capability_role,
            "provider_id": provider_id,
            "model_id": None,
            "plan_text": "",
            "outcome": "",
            "receipt_id": None,
            "files_changed": [],
            "terminal_operations": [],
            "tests": [],
            "approvals": [],
            "limitations": [],
            "created_at": started,
            "updated_at": started,
            "metadata": {},
        }
        self.store.save_coding_mission(record)
        return record

    def complete(
        self,
        record: dict[str, Any],
        *,
        status: str,
        outcome: str,
        receipt_id: str | None,
        acp_session_id: str | None,
        model_id: str | None,
        files_changed: list[str],
        terminal_operations: list[str],
        tests: list[str],
        approvals: list[dict[str, Any]],
        limitations: list[str],
        plan_text: str = "",
    ) -> dict[str, Any]:
        record.update(
            {
                "status": status,
                "outcome": outcome,
                "receipt_id": receipt_id,
                "acp_session_id": acp_session_id or record.get("acp_session_id"),
                "model_id": model_id or record.get("model_id"),
                "files_changed": files_changed,
                "terminal_operations": terminal_operations,
                "tests": tests,
                "approvals": approvals,
                "limitations": limitations,
                "plan_text": plan_text or record.get("plan_text", ""),
                "updated_at": _iso(),
            }
        )
        self.store.save_coding_mission(record)
        mission = self.missions.get_mission(record["mission_id"])
        if mission is not None:
            mission.status = "completed" if status == "complete" else status
            mission.summary = outcome[:500]
            mission.last_receipt_id = receipt_id
            mission.outcome = status
            mission.updated_at = _iso()
            self.missions.save_mission(mission)
        return record
