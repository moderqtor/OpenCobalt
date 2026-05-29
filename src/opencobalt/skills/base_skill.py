"""Base class and result model for all OpenCobalt skills."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class SkillResult(BaseModel):
    id: str = Field(default_factory=_uid)
    timestamp: datetime = Field(default_factory=_now)
    skill_name: str
    success: bool
    output: Any
    error: str | None = None


class BaseSkill(ABC):
    name: str  # class attribute
    description: str  # class attribute

    @abstractmethod
    def run(self, **kwargs) -> SkillResult:
        ...
