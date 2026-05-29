"""Named session tracking backed by the config store.

A session is a named window of work. Starting a session stores its name and
start time in config. Ending it clears the active session. The session name
tags route decisions and events for later filtering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .config import Config

_SESSION_KEY = "_active_session"
_SESSION_START_KEY = "_session_start"


class SessionManager:
    def __init__(self, db_path: Path) -> None:
        self._cfg = Config(db_path)

    def start(self, name: str) -> None:
        self._cfg.set(_SESSION_KEY, name)
        self._cfg.set(_SESSION_START_KEY, datetime.now(tz=timezone.utc).isoformat())

    def end(self) -> str | None:
        name = self._cfg.get(_SESSION_KEY)
        self._cfg.delete(_SESSION_KEY)
        self._cfg.delete(_SESSION_START_KEY)
        return name

    def active(self) -> str | None:
        return self._cfg.get(_SESSION_KEY)

    def started_at(self) -> str | None:
        return self._cfg.get(_SESSION_START_KEY)
