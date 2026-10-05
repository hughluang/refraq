"""Cron schedule expansion with Schedule Timezone (daily-for-all DST).

Gap → next legal local time; ambiguous → fold=1 once for every cron expression
(including hourly). See docs/conventions-time.md.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from celery.schedules import BaseSchedule, schedstate

from backend.core.time import ensure_aware_utc, resolve_wall_time, utc_now
from backend.core.time_zones import canonical_zone_id
from backend.worker.parameters import BEAT_SYNC_EVERY_SEC


def validate_schedule_timezone(name: str) -> ZoneInfo:
    canonical = canonical_zone_id(name)
    if canonical is None:
        raise ValueError(f"unknown Schedule Timezone: {name!r}")
    return ZoneInfo(canonical)


_NUMBER = re.compile(r"-?\d+")
_FIRE_HORIZON_YEARS = 8
# 2922 days is 8 * 365.25, the same horizon as the cron fire window above.
# Interval and running-timeout writes share this ceiling, under the Integer max.
MAX_CADENCE_SECONDS = 2922 * 86400


def _parse_number(token: str) -> int:
    text = token.strip()
    if not _NUMBER.fullmatch(text):
        raise ValueError(f"invalid cron number: {token!r}")
    return int(text)


def _require_in_range(value: int, minimum: int, maximum: int, field: str) -> None:
    if value < minimum or value > maximum:
        raise ValueError(
            f"cron value {value} is outside {minimum}-{maximum} in {field!r}"
        )


def _parse_part(part: str, minimum: int, maximum: int, field: str) -> set[int]:
    step = 1
    base = part
    stepped = "/" in part
    if stepped:
        base, step_text = part.split("/", 1)
        if not base.strip() or not step_text.strip() or "/" in step_text:
            raise ValueError(f"invalid cron step in {field!r}")
        step = _parse_number(step_text)
        if step < 1:
            raise ValueError(f"cron step must be >= 1 in {field!r}")
    base = base.strip()
    if base == "*":
        start, end = minimum, maximum
    elif "-" in base:
        if base.startswith("-"):
            raise ValueError(f"invalid cron range in {field!r}")
        start_text, end_text = base.split("-", 1)
        if not start_text.strip() or not end_text.strip():
            raise ValueError(f"invalid cron range in {field!r}")
        start = _parse_number(start_text)
        end = _parse_number(end_text)
        if start > end:
            raise ValueError(
                f"cron range start {start} is greater than end {end} in {field!r}"
            )
    else:
        start = _parse_number(base)
        end = maximum if stepped else start
    _require_in_range(start, minimum, maximum, field)
    _require_in_range(end, minimum, maximum, field)
    return set(range(start, end + 1, step))


def _parse_field(field: str, minimum: int, maximum: int) -> set[int]:
    """Parse one cron field (``*``, ``n``, ``a-b``, ``*/n``, ``a-b/n``, ``n/step``, lists)."""
    if not field.strip():
        raise ValueError("empty cron field")
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty cron list item in {field!r}")
        values.update(_parse_part(part, minimum, maximum, field))
    return values


def parse_cron_fields(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron must have 5 fields, got {expr!r}")
    minute, hour, day_of_month, month, day_of_week = parts
    if day_of_month != "*" and day_of_week != "*":
        raise ValueError("day-of-month and day-of-week cannot both be restricted")
    # Cron day-of-week: 0 or 7 is Sunday.
    dow = _parse_field(day_of_week, 0, 7)
    if 7 in dow:
        dow.add(0)
        dow.discard(7)
    return (
        _parse_field(minute, 0, 59),
        _parse_field(hour, 0, 23),
        _parse_field(day_of_month, 1, 31),
        _parse_field(month, 1, 12),
        dow,
    )


def _cron_weekday(day: date) -> int:
    """Cron weekday for a calendar date. Monday=1 … Saturday=6, Sunday=0."""
    return (day.weekday() + 1) % 7


def _local_matches(naive: datetime, fields: tuple[set[int], set[int], set[int], set[int], set[int]]) -> bool:
    minutes, hours, doms, months, dows = fields
    return (
        naive.minute in minutes
        and naive.hour in hours
        and naive.day in doms
        and naive.month in months
        and _cron_weekday(naive.date()) in dows
    )


def _plus_years(moment: datetime, years: int) -> datetime:
    try:
        return moment.replace(year=moment.year + years)
    except ValueError:
        return moment.replace(year=moment.year + years, day=28)


def first_cron_fire_after(
    fields: tuple[set[int], set[int], set[int], set[int], set[int]],
    tz: ZoneInfo,
    after: datetime,
) -> datetime | None:
    """First legal fire strictly after ``after``, or None when none exists within 8 years.

    Walks calendar days (month, day, weekday), then hour and minute on a matching day.
    Each candidate wall time goes through ``resolve_wall_time`` (gap rolls forward,
    ambiguous local time uses fold=1).
    """
    after = ensure_aware_utc(after)
    minutes, hours, doms, months, dows = fields
    local_after = after.astimezone(tz)
    limit = ensure_aware_utc(_plus_years(local_after, _FIRE_HORIZON_YEARS))
    day = local_after.date()
    last_day = limit.astimezone(tz).date()
    ordered_hours = sorted(hours)
    ordered_minutes = sorted(minutes)
    while day <= last_day:
        if day.month in months and day.day in doms and _cron_weekday(day) in dows:
            for hour in ordered_hours:
                for minute in ordered_minutes:
                    resolved = resolve_wall_time(
                        day.year,
                        day.month,
                        day.day,
                        hour,
                        minute,
                        0,
                        tz,
                    )
                    if resolved > after:
                        if resolved <= limit:
                            return resolved
                        return None
        day += timedelta(days=1)
    return None


class ZoneCronSchedule:
    """Cron wall clock interpreted in an IANA Schedule Timezone."""

    def __init__(self, cron_expr: str, schedule_timezone: str = "UTC"):
        self.cron_expr = cron_expr
        self.schedule_timezone = schedule_timezone or "UTC"
        self._fields = parse_cron_fields(cron_expr)
        self._tz = validate_schedule_timezone(self.schedule_timezone)

    def _next_fire_after(self, last_run_at: datetime | None) -> datetime:
        start = last_run_at if last_run_at is not None else utc_now() - timedelta(seconds=1)
        found = first_cron_fire_after(self._fields, self._tz, start)
        if found is None:
            raise RuntimeError(
                f"no cron fire found for {self.cron_expr!r} in {self.schedule_timezone}"
            )
        return found


def compute_next_run_at(
    *,
    cron: str | None,
    schedule_timezone: str,
    interval_seconds: int | None,
    after: datetime,
) -> datetime:
    """Next legal fire Instant strictly after ``after`` (Clock Instant)."""
    after = ensure_aware_utc(after)
    if interval_seconds and interval_seconds > 0:
        nxt = after + timedelta(seconds=interval_seconds)
        now = utc_now()
        return nxt if nxt >= now else now
    if cron:
        return ZoneCronSchedule(cron, schedule_timezone=schedule_timezone)._next_fire_after(
            after
        )
    raise ValueError("exactly one of cron or interval_seconds is required")


def current_cron_slot_instant(
    *,
    cron: str,
    schedule_timezone: str,
    now: datetime | None = None,
) -> datetime | None:
    """Current minute-aligned wall slot Instant if the expression matches; else None."""
    zone = ZoneCronSchedule(cron, schedule_timezone=schedule_timezone)
    clock = ensure_aware_utc(now or utc_now())
    local_now = clock.astimezone(zone._tz)
    naive = local_now.replace(second=0, microsecond=0, tzinfo=None)
    if not _local_matches(naive, zone._fields):
        return None
    return resolve_wall_time(
        naive.year,
        naive.month,
        naive.day,
        naive.hour,
        naive.minute,
        0,
        zone._tz,
    )


class CommitmentSchedule(BaseSchedule):
    """Celery schedule driven only by a stored next_run_at commitment.

    Business due remains ``next_run_at <= now``. Beat's ``last_run_at`` is only a
    delivery cursor for this in-memory snapshot: after one dispatch of a given
    commitment Instant, do not tight-loop send. Retry if the store is still
    overdue after ``BEAT_SYNC_EVERY_SEC``.
    """

    def __init__(self, next_run_at: datetime | None, **kwargs):
        self.next_run_at = (
            ensure_aware_utc(next_run_at) if next_run_at is not None else None
        )
        super().__init__(**kwargs)

    def remaining_estimate(self, last_run_at: datetime | None) -> timedelta:
        is_due, next_s = self.is_due(last_run_at)
        if is_due:
            return timedelta(seconds=0)
        return timedelta(seconds=float(next_s))

    def is_due(self, last_run_at: datetime | None):
        now = ensure_aware_utc(self.now())
        if self.next_run_at is None:
            return schedstate(False, float(BEAT_SYNC_EVERY_SEC))
        if self.next_run_at > now:
            rem = (self.next_run_at - now).total_seconds()
            return schedstate(False, max(rem, 1.0))
        if last_run_at is not None:
            dispatched_at = ensure_aware_utc(last_run_at)
            if dispatched_at >= self.next_run_at:
                wait = float(BEAT_SYNC_EVERY_SEC) - (now - dispatched_at).total_seconds()
                if wait > 0:
                    return schedstate(False, max(wait, 1.0))
        return schedstate(True, float(BEAT_SYNC_EVERY_SEC))

    def now(self) -> datetime:
        return utc_now()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CommitmentSchedule):
            return self.next_run_at == other.next_run_at and super().__eq__(other)
        return NotImplemented
