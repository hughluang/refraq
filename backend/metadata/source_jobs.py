"""Domain facade for structure Jobs minted via Scheduled Task."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from celery import shared_task

from backend.admin.audit import persist_audit_event
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import ensure_aware_utc, parse_instant
from backend.jobs.store import (
    JobRecord,
    UniqueScheduledForError,
    create_queued_job,
    format_job_log_line,
    get_job_store,
    mark_cancelled,
    set_celery_task_id,
)
from backend.metadata.errors import (
    JobInputInvalid,
)
from backend.metadata.source_schedules import (
    STRUCTURE_ENQUEUE_TASK_NAME,
    require_runnable_schedule,
)
from backend.metadata.sources.service import require_source
from backend.metadata.sources.store import get_source_store
from backend.metadata.tasks import run_job
from backend.worker.due import (
    commit_due_mint,
    consume_due_tick,
)
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store

logger = logging.getLogger(__name__)


def dispatch_queued_job(job: JobRecord) -> str:
    """Dispatch Celery task for an already-persisted queued Job.

    Callers that create the Job inside a DB transaction must invoke this only
    after commit (or use an on_commit hook). Only patches celery_task_id —
    never rewrites status / claim fields after apply_async.
    """
    async_result = run_job.apply_async(
        args=[job.id],
        task_id=job.id,
    )
    set_celery_task_id(job.id, async_result.id)
    return async_result.id


def enqueue_structure_job(
    *,
    source_id: str,
    actor_user_id: str | None,
    trigger_ref: str,
    scheduled_for: datetime | None = None,
    running_timeout_sec: int | None = None,
) -> JobRecord:
    """Create a schedule-triggered structure Job and dispatch the worker.

    Does not enforce Source single-flight or Source usability — those are checked
    when the structure Job executes.
    """
    source = require_source(source_id)
    if source.kind != "database":
        raise JobInputInvalid("structure jobs require a database Source")
    if not source.engine or not source.access_ciphertext:
        raise JobInputInvalid("Source has no access configuration")

    summary = f"structure · {source.key}"
    queued_line = format_job_log_line(
        level="info",
        message=f"queued for source {source.key}",
    )
    job = create_queued_job(
        kind="structure",
        input={"source_id": source_id},
        created_by=actor_user_id,
        summary=summary,
        trigger_kind="schedule",
        trigger_ref=trigger_ref,
        log_body=queued_line,
        scheduled_for=scheduled_for,
        running_timeout_sec=running_timeout_sec,
    )
    dispatch_queued_job(job)
    return get_job_store().get(job.id) or job


def run_structure_schedule(
    *,
    schedule_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> JobRecord:
    """Operator run-now: mint immediately without moving last_run_at / next_run_at."""
    record = require_runnable_schedule(schedule_id)
    raw = record.kwargs_json.get("source_id")
    if not isinstance(raw, str) or not raw:
        raise JobInputInvalid("structure schedule is missing source_id")
    job = enqueue_structure_job(
        source_id=raw,
        actor_user_id=actor_user_id,
        trigger_ref=record.id,
        scheduled_for=None,
        running_timeout_sec=record.running_timeout_sec,
    )
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="schedule",
        resource_id=record.id,
        action="schedule.run",
        result="success",
        detail={"kind": "structure", "source_id": raw, "job_id": job.id},
    )
    return job


def _mint_on_session(
    *,
    schedule_id: str,
    source_id: str | None,
    scheduled_for: datetime,
    now: datetime,
    cancel_immediately: bool,
    cadence: ScheduledTaskRecord | None,
    session: Any = None,
) -> dict[str, Any]:
    if source_id:
        source = get_source_store().get_source(source_id)
        source_key = source.key if source is not None else source_id
        job_input: dict[str, Any] = {"source_id": source_id}
    else:
        source_key = "(missing target)"
        job_input = {}
    summary = f"structure · {source_key}"
    queued_line = format_job_log_line(
        level="info",
        message=f"queued for source {source_key}",
        at=now,
    )

    already = False
    try:
        job = create_queued_job(
            kind="structure",
            input=job_input,
            created_by=None,
            summary=summary,
            trigger_kind="schedule",
            trigger_ref=schedule_id,
            log_body=queued_line,
            scheduled_for=scheduled_for,
            running_timeout_sec=(
                cadence.running_timeout_sec if cadence is not None else None
            ),
            session=session,
            created_at=now,
        )
    except UniqueScheduledForError as exc:
        already = True
        existing_id = exc.existing_job_id or ""
        job = get_job_store().get(existing_id, session=session)
        if job is None:
            return {"status": "already_minted", "job_id": existing_id}

    # UNIQUE collision still consumes the tick; use the existing Job's mint Instant.
    mint_at = job.created_at if already else now
    if cadence is not None:
        commit_due_mint(
            cadence,
            now=now,
            session=session,
            mint_at=mint_at,
        )

    should_cancel = cancel_immediately or cadence is None or not source_id
    if should_cancel and job.status not in ("succeeded", "failed", "cancelled"):
        cancelled = mark_cancelled(job.id, session=session)
        job = cancelled or job
        return {"status": "cancelled", "job_id": job.id, "job": job}

    if already:
        return {"status": "already_minted", "job_id": job.id, "job": job}
    return {"status": "queued", "job_id": job.id, "job": job}


def mint_structure_due_job(
    *,
    schedule_id: str,
    source_id: str | None,
    scheduled_for: datetime,
    now: datetime,
    cancel_immediately: bool = False,
    cadence: ScheduledTaskRecord | None = None,
    session: Any = None,
) -> dict[str, Any]:
    """Insert structure Job for a due tick (idempotent on scheduled_for).

    INSERT Job and consume the due cursor in one transaction. UNIQUE collision
    still advances next. A missing schedule row or missing target still inserts
    then cancels. When ``session`` is provided, the caller owns the transaction.
    """
    if cadence is None and session is None:
        cadence = get_schedule_store().get_by_id(schedule_id)
    if session is not None:
        return _mint_on_session(
            schedule_id=schedule_id,
            source_id=source_id,
            scheduled_for=scheduled_for,
            now=now,
            cancel_immediately=cancel_immediately,
            cadence=cadence,
            session=session,
        )
    settings = get_settings()
    if settings.store_backend == "memory":
        return _mint_on_session(
            schedule_id=schedule_id,
            source_id=source_id,
            scheduled_for=scheduled_for,
            now=now,
            cancel_immediately=cancel_immediately,
            cadence=cadence,
            session=None,
        )
    with session_scope() as owned:
        return _mint_on_session(
            schedule_id=schedule_id,
            source_id=source_id,
            scheduled_for=scheduled_for,
            now=now,
            cancel_immediately=cancel_immediately,
            cadence=cadence,
            session=owned,
        )


def _resolve_due_at(due_at: str | datetime | None) -> datetime | None:
    if due_at is None:
        return None
    if isinstance(due_at, datetime):
        return ensure_aware_utc(due_at)
    if isinstance(due_at, str) and due_at.strip():
        return parse_instant(due_at)
    return None


def _target_source_id(
    task_source_id: str | None,
    record: ScheduledTaskRecord | None,
) -> str | None:
    if isinstance(task_source_id, str) and task_source_id:
        return task_source_id
    if record is None:
        return None
    raw = record.kwargs_json.get("source_id")
    return raw if isinstance(raw, str) and raw else None


@shared_task(name=STRUCTURE_ENQUEUE_TASK_NAME)
def fire_scheduled_structure(
    schedule_id: str | None = None,
    source_id: str | None = None,
    due_at: str | datetime | None = None,
) -> dict[str, str]:
    """Beat tick: honor the delivered commitment Instant and mint a structure Job."""
    if not schedule_id:
        logger.info("scheduled structure skipped: missing_schedule_id")
        return {"status": "skipped", "reason": "missing_schedule_id"}

    due = _resolve_due_at(due_at)
    if due is None:
        # Domain deliveries must carry the Beat commitment Instant; no store fallback.
        return {"status": "missing_due_at"}

    def _decide_and_mint(session: Any) -> dict[str, Any]:
        outcome = consume_due_tick(schedule_id, due_at=due, session=session)
        status = outcome.get("status")
        if status != "mint":
            return {"status": str(status)}

        record = outcome.get("record")
        if record is not None and not isinstance(record, ScheduledTaskRecord):
            record = None
        target_id = _target_source_id(source_id, record)
        cancel_immediately = bool(outcome.get("cancel_immediately")) or target_id is None

        return mint_structure_due_job(
            schedule_id=schedule_id,
            source_id=target_id,
            scheduled_for=outcome["scheduled_for"],
            now=outcome["now"],
            cancel_immediately=cancel_immediately,
            cadence=record,
            session=session,
        )

    settings = get_settings()
    if settings.store_backend == "memory":
        minted = _decide_and_mint(None)
    else:
        with session_scope() as session:
            minted = _decide_and_mint(session)

    minted_status = minted.get("status")
    job = minted.get("job")
    if minted_status == "cancelled":
        return {"status": "cancelled", "job_id": str(minted["job_id"])}
    if minted_status == "already_minted":
        # Repair: Job existed but may never have been dispatched.
        if isinstance(job, JobRecord) and job.status == "queued":
            fresh_after = get_schedule_store().get_by_id(schedule_id)
            if fresh_after is not None and fresh_after.enabled:
                dispatch_queued_job(job)
        return {"status": "already_minted", "job_id": str(minted.get("job_id") or "")}
    if minted_status != "queued":
        return {"status": str(minted_status)}
    if not isinstance(job, JobRecord):
        raise RuntimeError("due mint queued without a Job record")
    dispatch_queued_job(job)
    return {"status": "queued", "job_id": job.id}
