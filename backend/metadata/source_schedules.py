"""Domain facade for Source-scoped structure Scheduled Tasks."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.admin.audit import persist_audit_event, persist_audit_event_on
from backend.core.time import utc_now
from backend.jobs.store import JobRecord, JobStatus, get_job_store
from backend.metadata.errors import (
    JobInputInvalid,
    ScheduleKindInvalid,
    SourceNotFound,
)
from backend.metadata.sources.store import SourceRecord, get_source_store
from backend.worker.api import (
    STRUCTURE_SCHEDULE_KEY_PREFIX,
    get_schedule,
    schedule_out,
    validate_cadence,
)
from backend.worker.errors import ScheduleSystemImmutable
from backend.worker.schemas.schedules import ScheduleOut
from backend.worker.schedules import (
    ScheduledTaskRecord,
    SqlScheduleStore,
    get_schedule_store,
)

__all__ = [
    "DEFAULT_STRUCTURE_CRON",
    "DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE",
    "STRUCTURE_ENQUEUE_TASK_NAME",
    "create_structure_schedule",
    "ensure_default_structure_schedule_if_none",
    "ensure_default_structure_schedule_if_none_on",
    "list_jobs_for_schedule",
    "list_structure_schedules",
    "public_schedule",
    "require_runnable_schedule",
    "seed_default_structure_schedule",
    "seed_default_structure_schedule_on",
    "structure_schedule_label",
    "structure_schedule_label_for_record",
    "structure_schedule_key",
]

STRUCTURE_ENQUEUE_TASK_NAME = "backend.metadata.tasks.enqueue_scheduled_structure"
DEFAULT_STRUCTURE_CRON = "0 2 * * *"
DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE = "UTC"


def structure_schedule_key(source_id: str, schedule_id: str) -> str:
    return f"{STRUCTURE_SCHEDULE_KEY_PREFIX}{source_id}:{schedule_id}"


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


def public_schedule(record: ScheduledTaskRecord) -> ScheduleOut:
    """Project a Scheduled Task for HTTP, resolving structure target source_key when possible."""
    source_key: str | None = None
    if not record.system:
        source_id = record.kwargs_json.get("source_id")
        if isinstance(source_id, str) and source_id:
            source = get_source_store().get_source(source_id)
            if source is not None:
                source_key = source.key
    return schedule_out(record, source_key=source_key)


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
) -> ScheduledTaskRecord:
    cron_value = cron.strip() if cron else None
    now = utc_now()
    schedule_id = f"sched_{uuid.uuid4().hex[:12]}"
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
        last_run_at=now,
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
    record = _new_structure_schedule_record(
        source,
        cron=cron,
        interval_seconds=interval_seconds,
        schedule_timezone=schedule_timezone,
        enabled=enabled,
        name=name,
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
    return schedule_out(stored, source_key=source.key)


def seed_default_structure_schedule(
    source_id: str,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> ScheduleOut:
    return create_structure_schedule(
        source_id=source_id,
        kind="structure",
        cron=DEFAULT_STRUCTURE_CRON,
        interval_seconds=None,
        schedule_timezone=DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE,
        enabled=True,
        name=None,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )


def seed_default_structure_schedule_on(
    source: SourceRecord,
    *,
    session: Session,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> ScheduleOut:
    validate_cadence(
        cron=DEFAULT_STRUCTURE_CRON,
        interval_seconds=None,
        schedule_timezone=DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE,
    )
    record = _default_structure_schedule_record(source)
    stored = SqlScheduleStore().upsert_on(session, record)
    persist_audit_event_on(
        session,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="schedule",
        resource_id=stored.id,
        action="schedule.create",
        result="success",
        detail=_schedule_create_detail(source.id),
    )
    return schedule_out(stored, source_key=source.key)


def _has_structure_schedule(source_id: str, records: list[ScheduledTaskRecord]) -> bool:
    return any(record.kwargs_json.get("source_id") == source_id for record in records)


def ensure_default_structure_schedule_if_none(
    source: SourceRecord,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> ScheduleOut | None:
    """Insert the product-default structure schedule when this database Source has none."""
    if source.kind != "database":
        return None
    existing = get_schedule_store().list(include_system=False)
    if _has_structure_schedule(source.id, existing):
        return None
    return seed_default_structure_schedule(
        source.id,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )


def ensure_default_structure_schedule_if_none_on(
    source: SourceRecord,
    *,
    session: Session,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> ScheduleOut | None:
    if source.kind != "database":
        return None
    existing = SqlScheduleStore().list_on(session, include_system=False)
    if _has_structure_schedule(source.id, existing):
        return None
    return seed_default_structure_schedule_on(
        source,
        session=session,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )


def list_structure_schedules(source_id: str) -> list[ScheduleOut]:
    source = get_source_store().get_source(source_id)
    if source is None:
        raise SourceNotFound()
    items: list[ScheduleOut] = []
    for record in get_schedule_store().list(include_system=False):
        if record.kwargs_json.get("source_id") == source_id:
            items.append(schedule_out(record, source_key=source.key))
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
