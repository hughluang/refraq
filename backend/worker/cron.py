"""Cron schedule expansion with Schedule Timezone (daily-for-all DST).

Gap → next legal local time; ambiguous → fold=1 once for every cron expression
(including hourly). See docs/conventions-time.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from celery.schedules import BaseSchedule, schedstate
from celery.schedules import schedule as interval_schedule

from backend.core.time import ensure_aware_utc, resolve_wall_time, utc_now


def validate_schedule_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown Schedule Timezone: {name!r}") from exc


def _parse_field(field: str, minimum: int, maximum: int) -> set[int]:
    """Parse one cron field into a set of allowed integers (*, n, a-b, */n, lists)."""
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(minimum, maximum + 1))
            continue
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if base == "*":
                start, end = minimum, maximum
            elif "-" in base:
                start_s, end_s = base.split("-", 1)
                start, end = int(start_s), int(end_s)
            else:
                start, end = int(base), maximum
            values.update(range(start, end + 1, step))
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            values.update(range(int(start_s), int(end_s) + 1))
            continue
        values.add(int(part))
    return values


def parse_cron_fields(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron must have 5 fields, got {expr!r}")
    minute, hour, day_of_month, month, day_of_week = parts
    # Cron day-of-week: 0-6 or 7=Sunday; accept both.
    dow = _parse_field(day_of_week, 0, 7)
    if 7 in dow:
        dow.add(0)
    return (
        _parse_field(minute, 0, 59),
        _parse_field(hour, 0, 23),
        _parse_field(day_of_month, 1, 31),
        _parse_field(month, 1, 12),
        dow,
    )


def _local_matches(naive: datetime, fields: tuple[set[int], set[int], set[int], set[int], set[int]]) -> bool:
    minutes, hours, doms, months, dows = fields
    # Python weekday: Monday=0 … Sunday=6; cron often Sunday=0.
    cron_dow = (naive.weekday() + 1) % 7
    return (
        naive.minute in minutes
        and naive.hour in hours
        and naive.day in doms
        and naive.month in months
        and cron_dow in dows
    )


class ZoneCronSchedule(BaseSchedule):
    """Celery schedule: cron wall clock interpreted in an IANA Schedule Timezone."""

    def __init__(self, cron_expr: str, schedule_timezone: str = "UTC", **kwargs):
        self.cron_expr = cron_expr
        self.schedule_timezone = schedule_timezone or "UTC"
        self._fields = parse_cron_fields(cron_expr)
        self._tz = validate_schedule_timezone(self.schedule_timezone)
        super().__init__(**kwargs)

    def remaining_estimate(self, last_run_at: datetime | None) -> timedelta:
        last = ensure_aware_utc(last_run_at) if last_run_at is not None else None
        nxt = self._next_fire_after(last)
        now = ensure_aware_utc(self.now())
        return nxt - now

    def is_due(self, last_run_at: datetime | None):
        rem = self.remaining_estimate(last_run_at)
        if rem.total_seconds() <= 0:
            return schedstate(True, 60.0)
        return schedstate(False, rem.total_seconds())

    def now(self) -> datetime:
        return utc_now()

    def _next_fire_after(self, last_run_at: datetime | None) -> datetime:
        start = last_run_at if last_run_at is not None else self.now() - timedelta(seconds=1)
        start = ensure_aware_utc(start)
        cursor_local = start.astimezone(self._tz).replace(second=0, microsecond=0) + timedelta(
            minutes=1
        )
        for _ in range(60 * 24 * 8):
            naive = cursor_local.replace(tzinfo=None)
            if _local_matches(naive, self._fields):
                resolved = resolve_wall_time(
                    naive.year,
                    naive.month,
                    naive.day,
                    naive.hour,
                    naive.minute,
                    0,
                    self._tz,
                )
                if resolved > start:
                    return resolved
            cursor_local = cursor_local + timedelta(minutes=1)
        raise RuntimeError(
            f"no cron fire found for {self.cron_expr!r} in {self.schedule_timezone}"
        )


def build_celery_schedule(
    *,
    cron: str | None,
    schedule_timezone: str,
    interval_seconds: int | None,
):
    """Build a Celery schedule for a Scheduled Task. Interval ignores Schedule Timezone."""
    if interval_seconds and interval_seconds > 0:
        return interval_schedule(run_every=timedelta(seconds=interval_seconds))
    if cron:
        return ZoneCronSchedule(cron, schedule_timezone=schedule_timezone)
    return None
