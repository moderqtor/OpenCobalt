"""Clock abstraction for deterministic time handling in OpenCobalt daily operator."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone


class Clock(ABC):
    """Abstract clock interface."""

    @abstractmethod
    def now(self) -> datetime:
        """Return current datetime with UTC timezone."""
        pass

    def now_iso(self) -> str:
        """Return current datetime as ISO-8601 string."""
        return self.now().isoformat()


class SystemClock(Clock):
    """Production clock returning system UTC time."""

    def now(self) -> datetime:
        return datetime.now(tz=timezone.utc)


class FrozenClock(Clock):
    """Deterministic clock for unit testing and time-travel simulation."""

    def __init__(self, fixed_time: datetime | str):
        if isinstance(fixed_time, str):
            # Parse ISO format, ensuring UTC timezone if offset missing
            dt = datetime.fromisoformat(fixed_time)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            self._current = dt
        else:
            if fixed_time.tzinfo is None:
                fixed_time = fixed_time.replace(tzinfo=timezone.utc)
            self._current = fixed_time

    def now(self) -> datetime:
        return self._current

    def set_time(self, new_time: datetime | str) -> None:
        """Explicitly set current frozen time."""
        if isinstance(new_time, str):
            dt = datetime.fromisoformat(new_time)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            self._current = dt
        else:
            if new_time.tzinfo is None:
                new_time = new_time.replace(tzinfo=timezone.utc)
            self._current = new_time

    def advance_minutes(self, minutes: float) -> None:
        """Advance time by specified number of minutes."""
        from datetime import timedelta
        self._current += timedelta(minutes=minutes)

    def advance_days(self, days: float) -> None:
        """Advance time by specified number of days."""
        from datetime import timedelta
        self._current += timedelta(days=days)
