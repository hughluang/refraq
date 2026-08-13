"""Unified Instant / Clock contract for the shared kernel.

See docs/conventions-time.md and docs/adr/0022-unified-time-contract.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, AwareDatetime, PlainSerializer
from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator

UTC = timezone.utc


class NaiveDateTimeError(TypeError):
    """Raised when a naive datetime crosses an Instant boundary."""


def ensure_aware_utc(value: datetime) -> datetime:
    """Normalize to aware UTC. Boundary-only; business code must not call this as insurance."""
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value)!r}")
    if value.tzinfo is None:
        raise NaiveDateTimeError("naive datetime is not allowed for Instant")
    return value.astimezone(UTC)


def format_instant(value: datetime, *, timespec: str = "seconds") -> str:
    """Serialize an Instant as UTC with a trailing Z."""
    aware = ensure_aware_utc(value)
    text = aware.isoformat(timespec=timespec)
    if text.endswith("+00:00"):
        return f"{text[:-6]}Z"
    if text.endswith("-00:00"):
        return f"{text[:-6]}Z"
    return text


def parse_instant(value: str) -> datetime:
    """Parse RFC 3339 / ISO-8601 with required offset into aware UTC."""
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid Instant: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("Instant requires an offset (RFC 3339)")
    return ensure_aware_utc(parsed)


def _instant_after(value: datetime) -> datetime:
    return ensure_aware_utc(value)


def _instant_json(value: datetime) -> str:
    return format_instant(value)


Instant = Annotated[
    AwareDatetime,
    AfterValidator(_instant_after),
    PlainSerializer(_instant_json, return_type=str, when_used="json"),
]


class UtcDateTime(TypeDecorator):
    """SQLAlchemy Instant column: timestamptz, reject naive bind, normalize results to UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return ensure_aware_utc(value)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current Instant (aware UTC)."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Deterministic clock for tests."""

    def __init__(self, instant: datetime) -> None:
        self._instant = ensure_aware_utc(instant)

    def now(self) -> datetime:
        return self._instant

    def set(self, instant: datetime) -> None:
        self._instant = ensure_aware_utc(instant)

    def advance(self, delta: timedelta) -> datetime:
        self._instant = self._instant + delta
        return self._instant


_clock: Clock = SystemClock()


def get_clock() -> Clock:
    return _clock


def set_clock(clock: Clock) -> None:
    global _clock
    _clock = clock


def reset_clock() -> None:
    set_clock(SystemClock())


def utc_now() -> datetime:
    return get_clock().now()


def resolve_wall_time(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    tz: ZoneInfo,
    *,
    microsecond: int = 0,
) -> datetime:
    """Map a local wall clock to an Instant (same DST rule for all cron).

    - Nonexistent local time (spring forward): next legal local instant.
    - Ambiguous local time (fall back): second occurrence (fold=1) once.
    Applies to hourly cron as well; does not fire both folds on fall-back.
    """
    naive = datetime(year, month, day, hour, minute, second, microsecond)  # noqa: DTZ001
    first = naive.replace(tzinfo=tz, fold=0)
    second = naive.replace(tzinfo=tz, fold=1)
    if first.utcoffset() != second.utcoffset():
        # PEP 495: ambiguous ⇒ fold=0 earlier; gap ⇒ fold=1 earlier.
        if first.timestamp() < second.timestamp():
            return ensure_aware_utc(second)
        cursor = naive
        for _ in range(24 * 60):
            cursor = cursor + timedelta(minutes=1)
            cand0 = cursor.replace(tzinfo=tz, fold=0)
            cand1 = cursor.replace(tzinfo=tz, fold=1)
            if cand0.utcoffset() == cand1.utcoffset():
                return ensure_aware_utc(cand0)
        raise ValueError(f"unable to resolve wall time {naive.isoformat()} in {tz}")
    return ensure_aware_utc(first)


__all__ = [
    "UTC",
    "Clock",
    "FixedClock",
    "Instant",
    "NaiveDateTimeError",
    "SystemClock",
    "UtcDateTime",
    "ensure_aware_utc",
    "format_instant",
    "get_clock",
    "parse_instant",
    "reset_clock",
    "resolve_wall_time",
    "set_clock",
    "utc_now",
]
