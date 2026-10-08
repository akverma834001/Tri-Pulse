"""Time management and injectable Clock module for Project Pulse.

Ensures all stored timestamps are UTC and tests can precisely control 'now'.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional


class Clock:
    def __init__(self, frozen_time: Optional[datetime] = None):
        self._frozen_time = frozen_time

    def now(self) -> datetime:
        """Return the current datetime in UTC."""
        if self._frozen_time is not None:
            if self._frozen_time.tzinfo is None:
                return self._frozen_time.replace(tzinfo=timezone.utc)
            return self._frozen_time.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    def set_time(self, dt: Optional[datetime]) -> None:
        """Freeze the clock to a specific time (useful for deterministic tests)."""
        if dt is not None and dt.tzinfo is None:
            self._frozen_time = dt.replace(tzinfo=timezone.utc)
        else:
            self._frozen_time = dt

    def reset(self) -> None:
        """Reset to actual system time."""
        self._frozen_time = None


# Default global clock instance
_global_clock = Clock()


def get_clock() -> Clock:
    return _global_clock


def utc_now() -> datetime:
    return _global_clock.now()


def to_local(dt: datetime, tz_name: str = "Asia/Kolkata") -> datetime:
    """Convert a UTC datetime to local timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        target_tz = ZoneInfo(tz_name)
    except Exception:
        target_tz = ZoneInfo("Asia/Kolkata")
    return dt.astimezone(target_tz)


def to_utc(dt: datetime, tz_name: str = "Asia/Kolkata") -> datetime:
    """Convert a local datetime to UTC."""
    if dt.tzinfo is None:
        try:
            local_tz = ZoneInfo(tz_name)
        except Exception:
            local_tz = ZoneInfo("Asia/Kolkata")
        dt = dt.replace(tzinfo=local_tz)
    return dt.astimezone(timezone.utc)


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure a datetime is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
