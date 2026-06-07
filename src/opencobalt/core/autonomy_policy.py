"""Autonomy policy defaults and permission checks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .config import Config


@dataclass(frozen=True)
class AutonomyPolicy:
    profile: str = "balanced"
    use_limits: str = "balanced"
    auto_test: bool = True
    auto_retry: bool = True
    auto_commit: bool = True
    auto_push: bool = False
    api_usage: bool = False
    push_requires_explicit: bool = True

    @classmethod
    def default(cls) -> AutonomyPolicy:
        return cls()

    @classmethod
    def for_profile(cls, profile: str) -> AutonomyPolicy:
        base = cls.default()
        if profile == "max":
            return replace(base, profile="max", use_limits="max")
        if profile == "cheap":
            return replace(base, profile="cheap", use_limits="cheap")
        return replace(base, profile=profile, use_limits=profile)


@dataclass(frozen=True)
class PermissionEnvelope:
    allowed_actions: list[str]
    denied_actions: list[str]

    def permits(self, action: str) -> bool:
        if action in self.denied_actions:
            return False
        return action in self.allowed_actions


class PolicyStore:
    def __init__(self, db_path: Path) -> None:
        self.config = Config(db_path)

    def set(self, key: str, value: str) -> None:
        self.config.set(key, value)

    def get_policy(self) -> AutonomyPolicy:
        profile = self.config.get("profile", "balanced") or "balanced"
        policy = AutonomyPolicy.for_profile(profile)
        values = {
            "auto_test": self._get_bool("auto_test", policy.auto_test),
            "auto_retry": self._get_bool("auto_retry", policy.auto_retry),
            "auto_commit": self._get_bool("auto_commit", policy.auto_commit),
            "auto_push": self._get_bool("auto_push", policy.auto_push),
            "api_usage": self._get_bool("api_usage", policy.api_usage),
            "push_requires_explicit": self._get_bool(
                "push_requires_explicit",
                policy.push_requires_explicit,
            ),
        }
        return replace(policy, **values)

    def _get_bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}
