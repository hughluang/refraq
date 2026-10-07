"""Published helpers for composition / upgrade assembly and Scheduled Task CRUD."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from backend.admin.system_parameters import resolve_str
from backend.core.config import get_settings
from backend.core.time import utc_now
from backend.jobs.api import revoke_queued_delivery
from backend.jobs.store import cancel_unfinished_for_schedule
from backend.worker.cron import (
    MAX_CADENCE_SECONDS,
    ZoneCronSchedule,
    compute_next_run_at,
    cron_search_after,
    first_cron_fire_after,
    parse_cron_fields,
    validate_schedule_timezone,
)
from backend.jobs.parameters import job_lost_detection_sec
from backend.worker.errors import (
    ScheduleCadenceInvalid,
    ScheduleNotFound,
    ScheduleRunningTimeoutInvalid,
    ScheduleStartAtInvalid,
    ScheduleSystemImmutable,
    ScheduleUndeletable,
)
from backend.entity.tasks import ACCESS_LOG_SCHEDULE_KEY, ACCESS_LOG_TASK_NAME
from backend.worker.models import REAPER_SCHEDULE_KEY, REAPER_TASK_NAME
from backend.worker.schemas.schedules import ScheduleOut, ScheduleRecentJobOut
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store

logger = logging.getLogger(__name__)

__all__ = [
    "current_schedule_timezone",
    "ensure_system_schedules",
    "delete_schedule",
    "get_schedule",
    "patch_schedule",
    "schedule_out",
    "realign_cron_commitments",
    "preview_cron_runs",
    "validate_cadence",
    "validate_running_timeout",
    "validate_start_at",
    "withdraw_schedules_by_owner_ref",
    "initial_next_run_at",
]


def current_schedule_timezone() -> str:
    return resolve_str("schedule_timezone").value


def ensure_system_schedules() -> None:
    """Idempotent seed for platform Scheduled Tasks (reaper).

    Interval follows the declared lost-detection tolerance; an existing row is aligned.
    """
    store = get_schedule_store()
    interval = job_lost_detection_sec()
    existing = store.get_by_key(REAPER_SCHEDULE_KEY)
    now = utc_now()
    if existing is None:
        store.upsert(
            ScheduledTaskRecord(
                id=f"sched_{uuid.uuid4().hex[:12]}",
                key=REAPER_SCHEDULE_KEY,
                name="Reap stuck jobs",
                enabled=True,
                interval_seconds=interval,
                cron=None,
                commitment_timezone=current_schedule_timezone(),
                task_name=REAPER_TASK_NAME,
                args_json=[],
                kwargs_json={},
                hidden=True,
                locked=True,
                undeletable=True,
                store_only=True,
                owner_ref=None,
                last_run_at=now,
                next_run_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        _ensure_access_log_schedule(store, now)
        return
    if existing.interval_seconds != interval:
        store.upsert(
            replace(
                existing,
                interval_seconds=interval,
                updated_at=now,
            )
        )
    _ensure_access_log_schedule(store, now)


def _ensure_access_log_schedule(store: object, now: datetime) -> None:
    schedule_store = store
    existing = schedule_store.get_by_key(ACCESS_LOG_SCHEDULE_KEY)
    if existing is not None:
        return
    schedule_store.upsert(
        ScheduledTaskRecord(
            id=f"sched_{uuid.uuid4().hex[:12]}",
            key=ACCESS_LOG_SCHEDULE_KEY,
            name="Purge Entity access logs",
            enabled=True,
            interval_seconds=86400,
            cron=None,
            commitment_timezone=current_schedule_timezone(),
            task_name=ACCESS_LOG_TASK_NAME,
            args_json=[],
            kwargs_json={},
            hidden=True,
            locked=True,
            undeletable=True,
            store_only=True,
            owner_ref=None,
            last_run_at=now,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def validate_cron(text: str, *, start_at: datetime | None = None) -> None:
    """Parse a cron expression and require a fire within the 8-year horizon.

    With ``start_at``, the horizon is searched from the first slot it admits.
    """
    try:
        fields = parse_cron_fields(text)
    except ValueError as exc:
        raise ScheduleCadenceInvalid(str(exc)) from exc
    zone = validate_schedule_timezone(current_schedule_timezone())
    cursor = cron_search_after(utc_now(), start_at)
    if first_cron_fire_after(fields, zone, cursor) is None:
        raise ScheduleCadenceInvalid("cron expression does not fire within 8 years")


def validate_cadence(
    *,
    cron: str | None,
    interval_seconds: int | None,
    start_at: datetime | None = None,
) -> None:
    has_interval = interval_seconds is not None
    has_cron = bool(cron and str(cron).strip())
    if has_interval == has_cron:
        raise ScheduleCadenceInvalid(
            "exactly one of cron or interval_seconds is required"
        )
    if has_cron:
        validate_cron(str(cron).strip(), start_at=start_at)
        return
    if interval_seconds is None or interval_seconds < 1:
        raise ScheduleCadenceInvalid("interval_seconds must be positive")
    if interval_seconds > MAX_CADENCE_SECONDS:
        raise ScheduleCadenceInvalid("interval_seconds exceeds the 8 year horizon")


def preview_cron_runs(
    cron: str, *, start_at: datetime | None = None
) -> tuple[str, list[datetime]]:
    """Next 5 cron fires from now (not before ``start_at``) in the current Schedule Timezone.

    Validates the cron expression and start time only. Read-only: no row write and no audit.
    """
    text = str(cron).strip()
    if not text:
        raise ScheduleCadenceInvalid("cron is required")
    start = validate_start_at(start_at)
    validate_cron(text, start_at=start)
    zone_name = current_schedule_timezone()
    schedule = ZoneCronSchedule(text, schedule_timezone=zone_name)
    instants: list[datetime] = []
    cursor = cron_search_after(utc_now(), start)
    for _ in range(5):
        cursor = schedule._next_fire_after(cursor)
        instants.append(cursor)
    return zone_name, instants


def validate_running_timeout(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 1 or value > MAX_CADENCE_SECONDS:
        raise ScheduleRunningTimeoutInvalid()
    return value


def validate_start_at(value: datetime | None) -> datetime | None:
    """Past values are kept as the anchor; only the 8-year future horizon is enforced."""
    if value is None:
        return None
    if value > utc_now() + timedelta(seconds=MAX_CADENCE_SECONDS):
        raise ScheduleStartAtInvalid()
    return value


def initial_next_run_at(
    *,
    cron: str | None,
    interval_seconds: int | None,
    enabled: bool,
    after: datetime | None = None,
    schedule_timezone: str,
    start_at: datetime | None = None,
) -> datetime | None:
    if not enabled:
        return None
    return compute_next_run_at(
        cron=cron,
        schedule_timezone=schedule_timezone,
        interval_seconds=interval_seconds,
        after=utc_now() if after is None else after,
        start_at=start_at,
    )


def schedule_out(
    record: ScheduledTaskRecord,
    *,
    recent_jobs: Sequence[ScheduleRecentJobOut] = (),
) -> ScheduleOut:
    """Map a mechanism Scheduled Task record to HTTP fields (no domain work_kind)."""
    return ScheduleOut(
        id=record.id,
        key=record.key,
        name=record.name,
        enabled=record.enabled,
        work_kind=None,
        target=None,
        interval_seconds=record.interval_seconds,
        cron=record.cron,
        running_timeout_sec=record.running_timeout_sec,
        start_at=record.start_at,
        deletable=not record.undeletable,
        last_run_at=record.last_run_at,
        next_run_at=record.next_run_at,
        recent_jobs=list(recent_jobs),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def get_schedule(schedule_id: str) -> ScheduledTaskRecord:
    record = get_schedule_store().get_by_id(schedule_id)
    if record is None:
        raise ScheduleNotFound()
    return record


def patch_schedule(
    schedule_id: str,
    *,
    enabled: bool | None = None,
    name: str | None = None,
    cron: str | None = None,
    interval_seconds: int | None = None,
    running_timeout_sec: int | None = None,
    start_at: datetime | None = None,
    cron_set: bool = False,
    interval_set: bool = False,
    timeout_set: bool = False,
    start_at_set: bool = False,
) -> ScheduledTaskRecord:
    record = get_schedule(schedule_id)
    if record.locked:
        raise ScheduleSystemImmutable()
    if (
        cron_set
        and interval_set
        and cron is not None
        and str(cron).strip()
        and interval_seconds is not None
    ):
        raise ScheduleCadenceInvalid(
            "exactly one of cron or interval_seconds is required"
        )
    next_cron = cron.strip() if cron_set and cron is not None else record.cron
    if cron_set and (cron is None or not cron.strip()):
        next_cron = None
    next_interval = interval_seconds if interval_set else record.interval_seconds
    if cron_set and next_cron:
        next_interval = None
    if interval_set and next_interval is not None:
        next_cron = None
    zone = current_schedule_timezone()
    next_start = validate_start_at(start_at) if start_at_set else record.start_at
    validate_cadence(
        cron=next_cron,
        interval_seconds=next_interval,
        start_at=next_start,
    )
    next_timeout = (
        validate_running_timeout(running_timeout_sec)
        if timeout_set
        else record.running_timeout_sec
    )
    now = utc_now()
    next_enabled = record.enabled if enabled is None else enabled
    cadence_changed = cron_set or interval_set or start_at_set
    enabled_changed = enabled is not None and enabled != record.enabled

    if not next_enabled:
        next_run = None
        next_commitment = record.commitment_timezone
    elif enabled_changed or cadence_changed:
        next_run = compute_next_run_at(
            cron=next_cron,
            schedule_timezone=zone,
            interval_seconds=next_interval,
            after=now,
            start_at=next_start,
        )
        next_commitment = zone
    else:
        next_run = record.next_run_at
        next_commitment = record.commitment_timezone

    updated = replace(
        record,
        enabled=next_enabled,
        name=record.name if name is None else name.strip(),
        cron=next_cron,
        interval_seconds=next_interval,
        commitment_timezone=next_commitment,
        running_timeout_sec=next_timeout,
        start_at=next_start,
        next_run_at=next_run,
        updated_at=now,
    )
    return get_schedule_store().upsert(updated)


def realign_cron_commitments() -> int:
    """Rewrite enabled cron commitments whose zone no longer matches the parameter.

    Does not mint a Job. Interval rows are left alone. A second call is a no-op.
    """
    zone = current_schedule_timezone()
    store = get_schedule_store()
    now = utc_now()
    changed = 0
    for record in store.list_enabled():
        if not record.cron or record.interval_seconds:
            continue
        if record.commitment_timezone == zone:
            continue
        next_run = compute_next_run_at(
            cron=record.cron,
            schedule_timezone=zone,
            interval_seconds=None,
            after=now,
            start_at=record.start_at,
        )
        store.upsert(
            replace(
                record,
                next_run_at=next_run,
                commitment_timezone=zone,
                updated_at=now,
            )
        )
        changed += 1
    return changed


def _cancel_and_revoke_for_schedule(schedule_id: str) -> None:
    cancelled = cancel_unfinished_for_schedule(schedule_id)
    settings = get_settings()
    for job in cancelled:
        try:
            revoke_queued_delivery(job.id, settings=settings)
        except Exception:
            logger.exception(
                "schedule withdraw revoke failed schedule=%s job=%s",
                schedule_id,
                job.id,
            )


def delete_schedule(schedule_id: str) -> None:
    record = get_schedule(schedule_id)
    if record.undeletable:
        raise ScheduleUndeletable()
    _cancel_and_revoke_for_schedule(schedule_id)
    get_schedule_store().delete(schedule_id)


def withdraw_schedules_by_owner_ref(owner_ref: str) -> int:
    """Delete schedules with this opaque owner_ref and cancel unfinished Jobs."""
    if not owner_ref:
        return 0
    store = get_schedule_store()
    records, _ = store.list_by_owner_ref(owner_ref)
    for record in records:
        _cancel_and_revoke_for_schedule(record.id)
        store.delete(record.id)
    return len(records)
