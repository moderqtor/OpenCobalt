"""Bounded TTL cache for expensive authenticated provider catalogs.

Live discovery remains the source of truth. This cache exists so a single
Chat or Research request does not launch the same catalog command repeatedly.
Failures expire quickly so they cannot poison routing.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, TypeVar

T = TypeVar("T")

DEFAULT_TTL_SECONDS = 90.0
DEFAULT_ERROR_TTL_SECONDS = 8.0


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class CacheHit(Generic[T]):
    value: T
    stored_at: datetime
    age_ms: int
    is_error: bool


class TtlCache(Generic[T]):
    """Process-local TTL cache with separate live and error lifetimes."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        error_ttl_seconds: float = DEFAULT_ERROR_TTL_SECONDS,
    ) -> None:
        if ttl_seconds <= 0 or error_ttl_seconds <= 0:
            raise ValueError("catalog cache TTLs must be positive")
        self.ttl_seconds = ttl_seconds
        self.error_ttl_seconds = error_ttl_seconds
        self._lock = threading.Lock()
        self._value: T | None = None
        self._stored_monotonic: float | None = None
        self._stored_at: datetime | None = None
        self._is_error = False

    def get(self) -> CacheHit[T] | None:
        with self._lock:
            if self._value is None or self._stored_monotonic is None or self._stored_at is None:
                return None
            age = time.monotonic() - self._stored_monotonic
            ttl = self.error_ttl_seconds if self._is_error else self.ttl_seconds
            if age > ttl:
                self._clear_locked()
                return None
            return CacheHit(
                value=self._value,
                stored_at=self._stored_at,
                age_ms=int(age * 1000),
                is_error=self._is_error,
            )

    def store(self, value: T, *, is_error: bool) -> CacheHit[T]:
        stored_at = _now()
        stored_monotonic = time.monotonic()
        with self._lock:
            self._value = value
            self._stored_at = stored_at
            self._stored_monotonic = stored_monotonic
            self._is_error = is_error
        return CacheHit(value=value, stored_at=stored_at, age_ms=0, is_error=is_error)

    def invalidate(self) -> None:
        with self._lock:
            self._clear_locked()

    def _clear_locked(self) -> None:
        self._value = None
        self._stored_monotonic = None
        self._stored_at = None
        self._is_error = False
