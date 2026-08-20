"""Domain facade for Source-scoped structure and join-detection Scheduled Tasks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

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
    "DEFAULT_JOIN_DETECTION_CRON",
    "DEFAULT_JOIN_DETECTION_SCHEDULE_TIMEZONE",
    "DEFAULT_STRUCTURE_CRON",
    "DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE",
    "JOIN_DETECTION_ENQUEUE_TASK_NAME",
    "SOURCE_WORK_KINDS",
    "STRUCTURE_ENQUEUE_TASK_NAME",
    "create_source_schedule",
    "delete_source_schedules_by_source_id",
    "ensure_default_source_schedules_if_none",
    "list_jobs_for_schedule",
    "list_source_schedules",
    "public_schedule",
    "require_runnable_schedule",
    "schedule_label_for_record",
    "seed_default_source_schedules",
    "source_owner_ref",
    "work_kind_for_record",
]


STRUCTURE_ENQUEUE_TASK_NAME = "backend.metadata.source_jobs.fire_scheduled_structure"
JOIN_DETECTION_ENQUEUE_TASK_NAME = (
    "backend.metadata.source_jobs.fire_scheduled_join_detection"
)
DEFAULT_STRUCTURE_CRON = "0 2 * * *"
DEFAULT_JOIN_DETECTION_CRON = "0 4 * * *"
DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE = "UTC"
DEFAULT_JOIN_DETECTION_SCHEDULE_TIMEZONE = "UTC"


@dataclass(frozen=True)
class SourceWorkKindSpec:
    kind: str
    task_name: str
    key_prefix: str
    default_cron: str
    default_timezone: str


SOURCE_WORK_KINDS: dict[str, SourceWorkKindSpec] = {
    "structure": SourceWorkKindSpec(
        kind="structure",
        task_name=STRUCTURE_ENQUEUE_TASK_NAME,
        key_prefix="structure:",
        default_cron=DEFAULT_STRUCTURE_CRON,
        default_timezone=DEFAULT_STRUCTURE_SCHEDULE_TIMEZONE,
    ),
    "join_detection": SourceWorkKindSpec(
        kind="join_detection",
        task_name=JOIN_DETECTION_ENQUEUE_TASK_NAME,
        key_prefix="join_detection:",
        default_cron=DEFAULT_JOIN_DETECTION_CRON,
        default_timezone=DEFAULT_JOIN_DETECTION_SCHEDULE_TIMEZONE,
    ),
}

_TASK_NAME_TO_KIND = {spec.task_name: spec.kind for spec in SOURCE_WORK_KINDS.values()}


def source_owner_ref(source_id: str) -> str:
    return f"metadata:source:{source_id}"


def work_kind_for_record(record: ScheduledTaskRecord) -> str | None:
    kind = _TASK_NAME_TO_KIND.get(record.task_name)
    if kind is not None:
        return kind
    for spec in SOURCE_WORK_KINDS.values():
        if record.key.startswith(spec.key_prefix):
            return spec.kind
    return None


def _spec_for_kind(kind: str) -> SourceWorkKindSpec:
    spec = SOURCE_WORK_KINDS.get(kind)
    if spec is None:
        raise ScheduleKindInvalid()
    return spec


def _spec_for_record(record: ScheduledTaskRecord) -> SourceWorkKindSpec | None:
    kind = work_kind_for_record(record)
    if kind is None:
        return None
    return SOURCE_WORK_KINDS[kind]


def _schedule_key(spec: SourceWorkKindSpec, source_id: str, schedule_id: str) -> str:
    return f"{spec.key_prefix}{source_id}:{schedule_id}"


def _schedule_label(spec: SourceWorkKindSpec, name: str | None, source_key: str) -> str:
    stripped = name.strip() if name else ""
    return stripped or f"{spec.kind} · {source_key}"


def schedule_label_for_record(
    record: ScheduledTaskRecord, name: str | None
) -> str | None:
    """None means omit (leave stored name). Empty/whitespace restores the default when Source is resolvable; otherwise omit."""
    if name is None:
        return None
    stripped = name.strip()
    if stripped:
        return stripped
    spec = _spec_for_record(record)
    source_id = record.kwargs_json.get("source_id")
    if spec is None or not isinstance(source_id, str) or not source_id:
        return None
    source = get_source_store().get_source(source_id)
    if source is None:
        return None
    return _schedule_label(spec, "", source.key)


def public_schedule(
    record: ScheduledTaskRecord, *, source_key: str | None = None
) -> ScheduleOut:
    """Project a mechanism record as an operator Scheduled Task.

    Source shape lives here: system rows stay mechanism-null; a string
    ``source_id`` in kwargs becomes ``work_kind`` plus target.
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
    kind = work_kind_for_record(record)
    return projected.model_copy(
        update={
            "work_kind": kind,
            "target": ScheduleTargetOut(
                source_id=source_id, source_key=resolved_key
            ),
        }
    )


def _last_job_for_schedule(schedule_id: str) -> ScheduleLastJobOut | None:
    jobs, _ = get_job_store().list(
        trigger_kind="schedule",
        trigger_ref=schedule_id,
        limit=1,
    )
    if not jobs:
        return None
    latest = jobs[0]
    return ScheduleLastJobOut(
        id=latest.id,
        status=latest.status,
        finished_at=latest.finished_at,
        created_at=latest.created_at,
        error_code=latest.error_code,
    )


def delete_source_schedules_by_source_id(source_id: str) -> None:
    """Withdraw Source schedules via opaque owner_ref (all work kinds)."""
    withdraw_schedules_by_owner_ref(source_owner_ref(source_id))


def _require_database_source(source_id: str):
    source = get_source_store().get_source(source_id)
    if source is None:
        raise SourceNotFound()
    if source.kind != "database":
        raise JobInputInvalid("Source schedules require a database Source")
    if not source.engine or not source.access_ciphertext:
        raise JobInputInvalid("Source has no access configuration")
    return source


def _new_schedule_record(
    source: SourceRecord,
    spec: SourceWorkKindSpec,
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
        key=_schedule_key(spec, source.id, schedule_id),
        name=_schedule_label(spec, name, source.key),
        enabled=enabled,
        interval_seconds=interval_seconds if not cron_value else None,
        cron=cron_value,
        task_name=spec.task_name,
        args_json=[],
        kwargs_json={"source_id": source.id, "schedule_id": schedule_id},
        system=False,
        schedule_timezone=schedule_timezone,
        owner_ref=source_owner_ref(source.id),
        last_run_at=now,
        next_run_at=next_run,
        running_timeout_sec=running_timeout_sec,
        created_at=now,
        updated_at=now,
    )


def _default_schedule_record(
    source: SourceRecord, spec: SourceWorkKindSpec
) -> ScheduledTaskRecord:
    return _new_schedule_record(
        source,
        spec,
        cron=spec.default_cron,
        interval_seconds=None,
        schedule_timezone=spec.default_timezone,
        enabled=True,
        name=None,
    )


def _schedule_create_detail(source_id: str, kind: str) -> dict[str, str]:
    return {"kind": kind, "source_id": source_id}


def _kind_records_for_source(
    source_id: str,
    spec: SourceWorkKindSpec,
    *,
    session: Session | None = None,
) -> list[ScheduledTaskRecord]:
    records, _ = get_schedule_store().list_by_owner_ref(
        source_owner_ref(source_id), session=session
    )
    return [
        record
        for record in records
        if record.task_name == spec.task_name
        or record.key.startswith(spec.key_prefix)
    ]


def create_source_schedule(
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
    spec = _spec_for_kind(kind)
    source = _require_database_source(source_id)
    validate_cadence(
        cron=cron.strip() if cron else None,
        interval_seconds=interval_seconds,
        schedule_timezone=schedule_timezone,
    )
    timeout = validate_running_timeout(running_timeout_sec)
    record = _new_schedule_record(
        source,
        spec,
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
        detail=_schedule_create_detail(source_id, spec.kind),
    )
    return public_schedule(stored, source_key=source.key)


def _seed_default_schedule(
    source: SourceRecord,
    spec: SourceWorkKindSpec,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> ScheduleOut:
    validate_cadence(
        cron=spec.default_cron,
        interval_seconds=None,
        schedule_timezone=spec.default_timezone,
    )
    record = _default_schedule_record(source, spec)
    stored = get_schedule_store().upsert(record, session=session)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="schedule",
        resource_id=stored.id,
        action="schedule.create",
        result="success",
        detail=_schedule_create_detail(source.id, spec.kind),
        session=session,
    )
    return public_schedule(stored, source_key=source.key)


def seed_default_source_schedules(
    source: SourceRecord,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> list[ScheduleOut]:
    return [
        _seed_default_schedule(
            source,
            spec,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            session=session,
        )
        for spec in SOURCE_WORK_KINDS.values()
    ]


def _ensure_default_schedule_if_none(
    source: SourceRecord,
    spec: SourceWorkKindSpec,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> ScheduleOut | None:
    if source.kind != "database":
        return None
    existing = _kind_records_for_source(source.id, spec, session=session)
    if existing:
        return None
    return _seed_default_schedule(
        source,
        spec,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        session=session,
    )


def ensure_default_source_schedules_if_none(
    source: SourceRecord,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    session: Session | None = None,
) -> list[ScheduleOut]:
    inserted: list[ScheduleOut] = []
    for spec in SOURCE_WORK_KINDS.values():
        seeded = _ensure_default_schedule_if_none(
            source,
            spec,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            session=session,
        )
        if seeded is not None:
            inserted.append(seeded)
    return inserted


def list_source_schedules(
    source_id: str, *, limit: int | None = None, offset: int = 0
) -> tuple[list[ScheduleOut], int]:
    source = get_source_store().get_source(source_id)
    if source is None:
        raise SourceNotFound()
    records, total = get_schedule_store().list_by_owner_ref(
        source_owner_ref(source_id), limit=limit, offset=offset
    )
    return [public_schedule(record, source_key=source.key) for record in records], total


def list_jobs_for_schedule(
    schedule_id: str,
    *,
    kind: str | None = None,
    status: JobStatus | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[JobRecord], int]:
    get_schedule(schedule_id)
    return get_job_store().list(
        kind=kind,
        status=status,
        trigger_kind="schedule",
        trigger_ref=schedule_id,
        limit=limit,
        offset=offset,
    )


def require_runnable_schedule(schedule_id: str) -> ScheduledTaskRecord:
    record = get_schedule(schedule_id)
    if record.system:
        raise ScheduleSystemImmutable()
    return record
