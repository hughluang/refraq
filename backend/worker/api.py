"""Published helpers for composition / upgrade assembly and Scheduled Task CRUD."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

from backend.core.time import utc_now
from backend.jobs.store import JobRecord
from backend.worker.cron import parse_cron_fields, validate_schedule_timezone
from backend.worker.errors import (
    ScheduleCadenceInvalid,
    ScheduleNotFound,
    ScheduleSystemImmutable,
)
from backend.worker.models import REAPER_SCHEDULE_KEY, REAPER_TASK_NAME
from backend.worker.schemas.schedules import ScheduleOut, ScheduleTargetOut
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store

__all__ = [
    "STRUCTURE_SCHEDULE_KEY_PREFIX",
    "ensure_system_schedules",
    "delete_schedule",
    "delete_structure_schedules_by_source_id",
    "get_schedule",
    "patch_schedule",
    "ScheduleNameStore",
    "schedule_names_for_jobs",
    "schedule_out",
    "validate_cadence",
]


class ScheduleNameStore(Protocol):
    def get_by_id(self, schedule_id: str) -> ScheduledTaskRecord | None: ...


STRUCTURE_SCHEDULE_KEY_PREFIX = "structure:"


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


def _work_from_record(
    record: ScheduledTaskRecord,
    *,
    source_key: str | None,
) -> tuple[str | None, ScheduleTargetOut | None]:
    if record.system:
        return None, None
    source_id = record.kwargs_json["source_id"]
    return "structure", ScheduleTargetOut(source_id=source_id, source_key=source_key)


def schedule_out(
    record: ScheduledTaskRecord,
    *,
    source_key: str | None = None,
) -> ScheduleOut:
    work_kind, target = _work_from_record(record, source_key=source_key)
    return ScheduleOut(
        id=record.id,
        key=record.key,
        name=record.name,
        enabled=record.enabled,
        work_kind=work_kind,
        target=target,
        interval_seconds=record.interval_seconds,
        cron=record.cron,
        schedule_timezone=record.schedule_timezone,
        last_run_at=record.last_run_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def get_schedule(schedule_id: str) -> ScheduledTaskRecord:
    record = get_schedule_store().get_by_id(schedule_id)
    if record is None:
        raise ScheduleNotFound()
    return record


def schedule_names_for_jobs(
    records: Sequence[JobRecord], store: ScheduleNameStore
) -> dict[str, str]:
    """Resolve Scheduled Task names for schedule-triggered Jobs."""
    names: dict[str, str] = {}
    ids = {
        record.trigger_ref
        for record in records
        if record.trigger_kind == "schedule" and record.trigger_ref
    }
    for schedule_id in ids:
        sched = store.get_by_id(schedule_id)
        if sched is None or not sched.name or not sched.name.strip():
            continue
        names[schedule_id] = sched.name.strip()
    return names


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
    updated = replace(
        record,
        enabled=record.enabled if enabled is None else enabled,
        name=record.name if name is None else name.strip(),
        cron=next_cron,
        interval_seconds=next_interval,
        schedule_timezone=next_zone,
        updated_at=now,
    )
    return get_schedule_store().upsert(updated)


def delete_schedule(schedule_id: str) -> None:
    record = get_schedule(schedule_id)
    if record.system:
        raise ScheduleSystemImmutable()
    get_schedule_store().delete(schedule_id)


def delete_structure_schedules_by_source_id(source_id: str) -> None:
    """Remove all structure schedules whose target is this Source (hard-delete cascade)."""
    store = get_schedule_store()
    for record in list(store.list(include_system=True)):
        if record.system:
            continue
        if record.kwargs_json.get("source_id") == source_id:
            store.delete(record.id)
