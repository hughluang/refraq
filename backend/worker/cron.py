"""Cron schedule expansion with Schedule Timezone (daily-for-all DST).

Gap → next legal local time; ambiguous → fold=1 once for every cron expression
(including hourly). See docs/conventions-time.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from celery.schedules import BaseSchedule, schedstate

from backend.core.time import ensure_aware_utc, resolve_wall_time, utc_now

# Match DatabaseScheduler.sync_every: after dispatching an overdue commitment,
# wait this long before retrying if the store row is still overdue.
BEAT_COMMITMENT_RETRY_SECONDS = 30.0


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


class ZoneCronSchedule:
    """Cron wall clock interpreted in an IANA Schedule Timezone."""

    def __init__(self, cron_expr: str, schedule_timezone: str = "UTC"):
        self.cron_expr = cron_expr
        self.schedule_timezone = schedule_timezone or "UTC"
        self._fields = parse_cron_fields(cron_expr)
        self._tz = validate_schedule_timezone(self.schedule_timezone)

    def _next_fire_after(self, last_run_at: datetime | None) -> datetime:
        start = last_run_at if last_run_at is not None else utc_now() - timedelta(seconds=1)
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
    overdue after ``BEAT_COMMITMENT_RETRY_SECONDS``.
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
            return schedstate(False, BEAT_COMMITMENT_RETRY_SECONDS)
        if self.next_run_at > now:
            rem = (self.next_run_at - now).total_seconds()
            return schedstate(False, max(rem, 1.0))
        if last_run_at is not None:
            dispatched_at = ensure_aware_utc(last_run_at)
            if dispatched_at >= self.next_run_at:
                wait = BEAT_COMMITMENT_RETRY_SECONDS - (now - dispatched_at).total_seconds()
                if wait > 0:
                    return schedstate(False, max(wait, 1.0))
        return schedstate(True, BEAT_COMMITMENT_RETRY_SECONDS)

    def now(self) -> datetime:
        return utc_now()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CommitmentSchedule):
            return self.next_run_at == other.next_run_at and super().__eq__(other)
        return NotImplemented
