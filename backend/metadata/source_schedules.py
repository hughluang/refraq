"""Domain facade for Source-scoped structure Scheduled Tasks."""

from __future__ import annotations

import uuid

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.metadata.errors import (
    JobInputInvalid,
    ScheduleKindInvalid,
)
from backend.metadata.sources.service import require_source
from backend.metadata.sources.store import get_source_store
from backend.worker.api import (
    STRUCTURE_SCHEDULE_KEY_PREFIX,
    delete_schedule,
    delete_structure_schedule_by_source_id,
    schedule_out,
    validate_cadence,
)
from backend.worker.errors import ScheduleNotFound
from backend.worker.schemas.schedules import ScheduleOut
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store

__all__ = [
    "STRUCTURE_ENQUEUE_TASK_NAME",
    "delete_structure_schedule",
    "delete_structure_schedule_for_source",
    "get_structure_schedule",
    "public_schedule",
    "put_structure_schedule",
    "structure_schedule_key",
]

STRUCTURE_ENQUEUE_TASK_NAME = "backend.metadata.tasks.enqueue_scheduled_structure"


def structure_schedule_key(source_id: str) -> str:
    return f"{STRUCTURE_SCHEDULE_KEY_PREFIX}{source_id}"


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


def delete_structure_schedule_for_source(source_id: str) -> None:
    """Best-effort remove of this Source's structure clock (e.g. hard-delete cascade)."""
    delete_structure_schedule_by_source_id(source_id)


def put_structure_schedule(
    *,
    source_id: str,
    kind: str,
    cron: str | None,
    interval_seconds: int | None,
    schedule_timezone: str,
    enabled: bool,
    name: str | None,
    actor_user_id: str,
    actor_token_id: str | None,
) -> tuple[ScheduleOut, bool]:
    if kind != "structure":
        raise ScheduleKindInvalid()
    source = require_source(source_id)
    if source.kind != "database":
        raise JobInputInvalid("structure schedules require a database Source")
    if not source.engine or not source.access_ciphertext:
        raise JobInputInvalid("Source has no access configuration")
    cron_value = cron.strip() if cron else None
    validate_cadence(
        cron=cron_value,
        interval_seconds=interval_seconds,
        schedule_timezone=schedule_timezone,
    )
    key = structure_schedule_key(source_id)
    existing = get_schedule_store().get_by_key(key)
    now = utc_now()
    created = existing is None
    label = name.strip() if name and name.strip() else f"structure · {source.key}"
    record = ScheduledTaskRecord(
        id=existing.id if existing is not None else f"sched_{uuid.uuid4().hex[:12]}",
        key=key,
        name=label,
        enabled=enabled,
        interval_seconds=interval_seconds if not cron_value else None,
        cron=cron_value,
        task_name=STRUCTURE_ENQUEUE_TASK_NAME,
        args_json=[],
        kwargs_json={"source_id": source_id},
        system=False,
        schedule_timezone=schedule_timezone,
        last_run_at=now if created else existing.last_run_at,
        created_at=now if created else existing.created_at,
        updated_at=now,
    )
    stored = get_schedule_store().upsert(record)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="schedule",
        resource_id=stored.id,
        action="schedule.create" if created else "schedule.patch",
        result="success",
        detail={"kind": "structure", "source_id": source_id},
    )
    return schedule_out(stored, source_key=source.key), created


def get_structure_schedule(source_id: str) -> ScheduleOut:
    source = require_source(source_id)
    record = get_schedule_store().get_by_key(structure_schedule_key(source_id))
    if record is None:
        raise ScheduleNotFound()
    return schedule_out(record, source_key=source.key)


def delete_structure_schedule(
    *,
    source_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> None:
    require_source(source_id)
    record = get_schedule_store().get_by_key(structure_schedule_key(source_id))
    if record is None:
        raise ScheduleNotFound()
    delete_schedule(record.id)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="schedule",
        resource_id=record.id,
        action="schedule.delete",
        result="success",
        detail={"kind": "structure", "source_id": source_id},
    )
