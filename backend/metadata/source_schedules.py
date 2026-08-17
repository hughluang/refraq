"""Domain facade for Source-scoped structure Scheduled Tasks."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.jobs.store import JobRecord, JobStatus, get_job_store
from backend.metadata.errors import (
    JobInputInvalid,
    ScheduleKindInvalid,
    SourceNotFound,
)
from backend.metadata.sources.store import SourceRecord, get_source_store
from backend.worker.api import (
    get_schedule,
    initial_next_run_at,
    schedule_out,
    validate_cadence,
    validate_running_timeout,
    withdraw_schedules_by_owner_ref,
)
from backend.worker.errors import ScheduleSystemImmutable
from backend.worker.schemas.schedules import (
    ScheduleLastJobOut,
    ScheduleOut,
    ScheduleTargetOut,
)
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store

__all__ = [
    "DEFAULT_STRUCTURE_CRON",
    "DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE",
    "STRUCTURE_ENQUEUE_TASK_NAME",
    "create_structure_schedule",
    "delete_structure_schedules_by_source_id",
    "ensure_default_structure_schedule_if_none",
    "list_jobs_for_schedule",
    "list_structure_schedules",
    "public_schedule",
    "require_runnable_schedule",
    "seed_default_structure_schedule",
    "structure_owner_ref",
    "structure_schedule_label",
    "structure_schedule_label_for_record",
    "structure_schedule_key",
]

STRUCTURE_ENQUEUE_TASK_NAME = "backend.metadata.source_jobs.fire_scheduled_structure"
_STRUCTURE_SCHEDULE_KEY_PREFIX = "structure:"
DEFAULT_STRUCTURE_CRON = "0 2 * * *"
DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE = "UTC"


def structure_owner_ref(source_id: str) -> str:
    return f"metadata:source:{source_id}"


def structure_schedule_key(source_id: str, schedule_id: str) -> str:
    return f"{_STRUCTURE_SCHEDULE_KEY_PREFIX}{source_id}:{schedule_id}"


def structure_schedule_label(name: str | None, source_key: str) -> str:
    stripped = name.strip() if name else ""
    return stripped or f"structure · {source_key}"


def structure_schedule_label_for_record(
    record: ScheduledTaskRecord, name: str | None
) -> str | None:
    """None means omit (leave stored name). Empty/whitespace restores the default when Source is resolvable; otherwise omit."""
    if name is None:
        return None
    stripped = name.strip()
    if stripped:
        return stripped
    source_id = record.kwargs_json.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        return None
    source = get_source_store().get_source(source_id)
    if source is None:
        return None
    return structure_schedule_label("", source.key)


def public_schedule(
    record: ScheduledTaskRecord, *, source_key: str | None = None
) -> ScheduleOut:
    """Project a mechanism record as an operator Scheduled Task.

    Structure / Source shape lives here: system rows stay mechanism-null;
    a string ``source_id`` in kwargs becomes ``work_kind=structure`` plus target.
    Missing ``source_id`` is not an error (next kind only changes this facade).
    Pass ``source_key`` when the caller already has the Source to skip a lookup.
    """
    last_job = _last_job_for_schedule(record.id)
    projected = schedule_out(record, last_job=last_job)
    if record.system:
        return projected
    source_id = record.kwargs_json.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        return projected
    resolved_key = source_key
    if resolved_key is None:
        source = get_source_store().get_source(source_id)
        if source is not None:
            resolved_key = source.key
    return projected.model_copy(
        update={
            "work_kind": "structure",
            "target": ScheduleTargetOut(
                source_id=source_id, source_key=resolved_key
            ),
        }
    )


def _last_job_for_schedule(schedule_id: str) -> ScheduleLastJobOut | None:
    jobs = [
        job
        for job in get_job_store().list()
        if job.trigger_kind == "schedule" and job.trigger_ref == schedule_id
    ]
    if not jobs:
        return None
    latest = max(jobs, key=lambda j: j.created_at)
    return ScheduleLastJobOut(
        id=latest.id,
        status=latest.status,
        finished_at=latest.finished_at,
        created_at=latest.created_at,
        error_code=latest.error_code,
    )


def delete_structure_schedules_by_source_id(source_id: str) -> None:
    """Withdraw structure schedules for this Source via opaque owner_ref."""
    withdraw_schedules_by_owner_ref(structure_owner_ref(source_id))


def _require_database_source(source_id: str):
    source = get_source_store().get_source(source_id)
    if source is None:
        raise SourceNotFound()
    if source.kind != "database":
        raise JobInputInvalid("structure schedules require a database Source")
    if not source.engine or not source.access_ciphertext:
        raise JobInputInvalid("Source has no access configuration")
    return source


def _new_structure_schedule_record(
    source: SourceRecord,
    *,
    cron: str | None,
    interval_seconds: int | None,
    schedule_timezone: str,
    enabled: bool,
    name: str | None,
    running_timeout_sec: int | None = None,
) -> ScheduledTaskRecord:
    cron_value = cron.strip() if cron else None
    now = utc_now()
    schedule_id = f"sched_{uuid.uuid4().hex[:12]}"
    next_run = initial_next_run_at(
        cron=cron_value,
        schedule_timezone=schedule_timezone,
        interval_seconds=interval_seconds if not cron_value else None,
        enabled=enabled,
        after=now,
    )
    return ScheduledTaskRecord(
        id=schedule_id,
        key=structure_schedule_key(source.id, schedule_id),
        name=structure_schedule_label(name, source.key),
        enabled=enabled,
        interval_seconds=interval_seconds if not cron_value else None,
        cron=cron_value,
        task_name=STRUCTURE_ENQUEUE_TASK_NAME,
        args_json=[],
        kwargs_json={"source_id": source.id, "schedule_id": schedule_id},
        system=False,
        schedule_timezone=schedule_timezone,
        owner_ref=structure_owner_ref(source.id),
        last_run_at=now,
        next_run_at=next_run,
        running_timeout_sec=running_timeout_sec,
        created_at=now,
        updated_at=now,
    )


def _default_structure_schedule_record(source: SourceRecord) -> ScheduledTaskRecord:
    return _new_structure_schedule_record(
        source,
        cron=DEFAULT_STRUCTURE_CRON,
        interval_seconds=None,
        schedule_timezone=DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE,
        enabled=True,
        name=None,
    )


def _schedule_create_detail(source_id: str) -> dict[str, str]:
    return {"kind": "structure", "source_id": source_id}


def create_structure_schedule(
    *,
    source_id: str,
    kind: str,
    cron: str | None,
    interval_seconds: int | None,
    schedule_timezone: str,
    enabled: bool,
    name: str | None,
    running_timeout_sec: int | None = None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> ScheduleOut:
    if kind != "structure":
        raise ScheduleKindInvalid()
    source = _require_database_source(source_id)
    validate_cadence(
        cron=cron.strip() if cron else None,
        interval_seconds=interval_seconds,
        schedule_timezone=schedule_timezone,
    )
    timeout = validate_running_timeout(running_timeout_sec)
    record = _new_structure_schedule_record(
        source,
        cron=cron,
        interval_seconds=interval_seconds,
        schedule_timezone=schedule_timezone,
        enabled=enabled,
        name=name,
        running_timeout_sec=timeout,
    )
    stored = get_schedule_store().upsert(record)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="schedule",
        resource_id=stored.id,
        action="schedule.create",
        result="success",
        detail=_schedule_create_detail(source_id),
    )
    return public_schedule(stored, source_key=source.key)


def seed_default_structure_schedule(
    source: SourceRecord,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> ScheduleOut:
    validate_cadence(
        cron=DEFAULT_STRUCTURE_CRON,
        interval_seconds=None,
        schedule_timezone=DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE,
    )
    record = _default_structure_schedule_record(source)
    stored = get_schedule_store().upsert(record, session=session)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="schedule",
        resource_id=stored.id,
        action="schedule.create",
        result="success",
        detail=_schedule_create_detail(source.id),
        session=session,
    )
    return public_schedule(stored, source_key=source.key)


def _has_structure_schedule(source_id: str, records: list[ScheduledTaskRecord]) -> bool:
    return any(record.kwargs_json.get("source_id") == source_id for record in records)


def ensure_default_structure_schedule_if_none(
    source: SourceRecord,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> ScheduleOut | None:
    """Insert the product-default structure schedule when this database Source has none."""
    if source.kind != "database":
        return None
    existing = get_schedule_store().list(include_system=False, session=session)
    if _has_structure_schedule(source.id, existing):
        return None
    return seed_default_structure_schedule(
        source,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        session=session,
    )


def list_structure_schedules(source_id: str) -> list[ScheduleOut]:
    source = get_source_store().get_source(source_id)
    if source is None:
        raise SourceNotFound()
    items: list[ScheduleOut] = []
    for record in get_schedule_store().list(include_system=False):
        if record.kwargs_json.get("source_id") == source_id:
            items.append(public_schedule(record, source_key=source.key))
    return items


def list_jobs_for_schedule(
    schedule_id: str,
    *,
    kind: str | None = None,
    status: JobStatus | None = None,
) -> list[JobRecord]:
    get_schedule(schedule_id)
    return [
        job
        for job in get_job_store().list(kind=kind, status=status)
        if job.trigger_kind == "schedule" and job.trigger_ref == schedule_id
    ]


def require_runnable_schedule(schedule_id: str) -> ScheduledTaskRecord:
    record = get_schedule(schedule_id)
    if record.system:
        raise ScheduleSystemImmutable()
    return record
