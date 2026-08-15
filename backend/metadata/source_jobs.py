"""Domain facade for structure Jobs minted via Scheduled Task."""

from __future__ import annotations

import logging

from celery import shared_task

from backend.admin.audit import persist_audit_event
from backend.jobs.store import (
    TERMINAL,
    JobRecord,
    create_queued_job,
    format_job_log_line,
    get_job_store,
)
from backend.metadata.errors import (
    JobAlreadyActive,
    JobInputInvalid,
    JobSourceDisabled,
    SourceNotFound,
)
from backend.metadata.source_schedules import (
    STRUCTURE_ENQUEUE_TASK_NAME,
    require_runnable_schedule,
)
from backend.metadata.sources.service import require_source
from backend.metadata.tasks import run_job
from backend.worker.schedules import get_schedule_store

logger = logging.getLogger(__name__)


def dispatch_queued_job(job: JobRecord) -> str:
    """Dispatch Celery task for an already-persisted queued Job.

    Callers that create the Job inside a DB transaction must invoke this only
    after commit (or use an on_commit hook).
    """
    async_result = run_job.apply_async(
        args=[job.id],
        task_id=job.id,
    )
    # Re-load: eager Celery may have mutated Job status before we return.
    stored = get_job_store().get(job.id)
    assert stored is not None, f"Job {job.id} missing after dispatch"
    stored.celery_task_id = async_result.id
    get_job_store().save(stored)
    return async_result.id


def list_jobs_for_source(
    source_id: str,
    *,
    kind: str | None = None,
) -> list[JobRecord]:
    """List Jobs whose input.source_id matches; used for structure single-flight."""
    require_source(source_id)
    return [
        job
        for job in get_job_store().list(kind=kind)
        if job.input.get("source_id") == source_id
    ]


def enqueue_structure_job(
    *,
    source_id: str,
    actor_user_id: str | None,
    trigger_ref: str,
) -> JobRecord:
    """Validate Source, create a schedule-triggered structure Job, dispatch worker."""
    source = require_source(source_id)
    if source.status != "active":
        raise JobSourceDisabled()
    if source.kind != "database":
        raise JobInputInvalid("structure jobs require a database Source")
    if not source.engine or not source.access_ciphertext:
        raise JobInputInvalid("Source has no access configuration")

    active = [
        job
        for job in list_jobs_for_source(source_id, kind="structure")
        if job.status not in TERMINAL
    ]
    if active:
        raise JobAlreadyActive()

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
    )
    dispatch_queued_job(job)
    return job


def run_structure_schedule(
    *,
    schedule_id: str,
    actor_user_id: str,
    actor_token_id: str | None,
) -> JobRecord:
    """Operator run-now: mint a Job without moving last_run_at."""
    record = require_runnable_schedule(schedule_id)
    source_id = record.kwargs_json.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        raise JobInputInvalid("structure schedule is missing source_id")
    job = enqueue_structure_job(
        source_id=source_id,
        actor_user_id=actor_user_id,
        trigger_ref=record.id,
    )
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="schedule",
        resource_id=record.id,
        action="schedule.run",
        result="success",
        detail={"kind": "structure", "source_id": source_id, "job_id": job.id},
    )
    return job


@shared_task(name=STRUCTURE_ENQUEUE_TASK_NAME)
def fire_scheduled_structure(
    schedule_id: str | None = None,
    source_id: str | None = None,  # noqa: ARG001 — Beat forwards kwargs_json
) -> dict[str, str]:
    """Beat tick: enqueue a structure Job or skip overlap / unusable Source."""
    if not schedule_id:
        logger.info("scheduled structure skipped: missing_target")
        return {"status": "skipped", "reason": "missing_target"}
    record = get_schedule_store().get_by_id(schedule_id)
    raw = record.kwargs_json.get("source_id") if record is not None else None
    if record is None or not isinstance(raw, str) or not raw:
        logger.info(
            "scheduled structure skipped: missing_target schedule_id=%s",
            schedule_id,
        )
        return {"status": "skipped", "reason": "missing_target"}
    try:
        job = enqueue_structure_job(
            source_id=raw,
            actor_user_id=None,
            trigger_ref=record.id,
        )
        return {"status": "queued", "job_id": job.id}
    except JobAlreadyActive:
        logger.info(
            "scheduled structure skipped: already active source_id=%s",
            raw,
        )
        return {"status": "skipped", "reason": "already_active"}
    except (JobSourceDisabled, JobInputInvalid, SourceNotFound) as exc:
        logger.info(
            "scheduled structure skipped: source_unusable source_id=%s error=%s",
            raw,
            exc.code,
        )
        return {"status": "skipped", "reason": "source_unusable"}
