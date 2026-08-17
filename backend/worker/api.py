"""Published helpers for composition / upgrade assembly and Scheduled Task CRUD."""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import datetime

from backend.core.config import get_settings
from backend.core.time import utc_now
from backend.jobs.api import revoke_queued_delivery
from backend.jobs.store import cancel_unfinished_for_schedule
from backend.worker.cron import compute_next_run_at, parse_cron_fields, validate_schedule_timezone
from backend.worker.errors import (
    ScheduleCadenceInvalid,
    ScheduleNotFound,
    ScheduleSystemImmutable,
)
from backend.worker.models import REAPER_SCHEDULE_KEY, REAPER_TASK_NAME
from backend.worker.schemas.schedules import ScheduleLastJobOut, ScheduleOut
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_system_schedules",
    "delete_schedule",
    "get_schedule",
    "patch_schedule",
    "schedule_out",
    "validate_cadence",
    "withdraw_schedules_by_owner_ref",
    "initial_next_run_at",
]


def ensure_system_schedules() -> None:
    """Idempotent seed for platform Scheduled Tasks (reaper)."""
    store = get_schedule_store()
    if store.get_by_key(REAPER_SCHEDULE_KEY) is not None:
        return
    now = utc_now()
    store.upsert(
        ScheduledTaskRecord(
            id=f"sched_{uuid.uuid4().hex[:12]}",
            key=REAPER_SCHEDULE_KEY,
            name="Reap stuck jobs",
            enabled=True,
            interval_seconds=60,
            cron=None,
            schedule_timezone="UTC",
            task_name=REAPER_TASK_NAME,
            args_json=[],
            kwargs_json={},
            system=True,
            owner_ref=None,
            last_run_at=now,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def validate_cadence(
    *,
    cron: str | None,
    interval_seconds: int | None,
    schedule_timezone: str,
) -> None:
    has_interval = interval_seconds is not None
    has_cron = bool(cron and str(cron).strip())
    if has_interval == has_cron:
        raise ScheduleCadenceInvalid(
            "exactly one of cron or interval_seconds is required"
        )
    try:
        validate_schedule_timezone(schedule_timezone)
    except ValueError as exc:
        raise ScheduleCadenceInvalid(str(exc)) from exc
    if has_cron:
        try:
            parse_cron_fields(str(cron).strip())
        except ValueError as exc:
            raise ScheduleCadenceInvalid(str(exc)) from exc
    elif interval_seconds is not None and interval_seconds < 1:
        raise ScheduleCadenceInvalid("interval_seconds must be positive")


def initial_next_run_at(
    *,
    cron: str | None,
    schedule_timezone: str,
    interval_seconds: int | None,
    enabled: bool,
    after: datetime | None = None,
) -> datetime | None:
    if not enabled:
        return None
    return compute_next_run_at(
        cron=cron,
        schedule_timezone=schedule_timezone,
        interval_seconds=interval_seconds,
        after=utc_now() if after is None else after,
    )


def schedule_out(
    record: ScheduledTaskRecord,
    *,
    last_job: ScheduleLastJobOut | None = None,
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
        schedule_timezone=record.schedule_timezone,
        last_run_at=record.last_run_at,
        next_run_at=record.next_run_at,
        last_job=last_job,
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
    schedule_timezone: str | None = None,
    cron_set: bool = False,
    interval_set: bool = False,
    timezone_set: bool = False,
) -> ScheduledTaskRecord:
    record = get_schedule(schedule_id)
    if record.system:
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
    next_zone = (
        (schedule_timezone or "").strip()
        if timezone_set
        else record.schedule_timezone
    )
    validate_cadence(
        cron=next_cron,
        interval_seconds=next_interval,
        schedule_timezone=next_zone,
    )
    now = utc_now()
    next_enabled = record.enabled if enabled is None else enabled
    cadence_changed = cron_set or interval_set or timezone_set
    enabled_changed = enabled is not None and enabled != record.enabled

    if not next_enabled:
        next_run = None
    elif next_enabled and (enabled_changed or cadence_changed):
        next_run = compute_next_run_at(
            cron=next_cron,
            schedule_timezone=next_zone,
            interval_seconds=next_interval,
            after=now,
        )
    else:
        next_run = record.next_run_at

    updated = replace(
        record,
        enabled=next_enabled,
        name=record.name if name is None else name.strip(),
        cron=next_cron,
        interval_seconds=next_interval,
        schedule_timezone=next_zone,
        next_run_at=next_run,
        updated_at=now,
    )
    return get_schedule_store().upsert(updated)


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
    if record.system:
        raise ScheduleSystemImmutable()
    _cancel_and_revoke_for_schedule(schedule_id)
    get_schedule_store().delete(schedule_id)


def withdraw_schedules_by_owner_ref(owner_ref: str) -> int:
    """Delete all non-system schedules with this opaque owner_ref; cancel unfinished Jobs."""
    if not owner_ref:
        return 0
    store = get_schedule_store()
    records = store.list_by_owner_ref(owner_ref)
    for record in records:
        _cancel_and_revoke_for_schedule(record.id)
        store.delete(record.id)
    return len(records)
