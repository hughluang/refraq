"""Domain facade for Source-scoped Jobs."""

from __future__ import annotations

import logging

from celery import shared_task

from backend.admin.audit import persist_audit_event
from backend.jobs.store import (
    TERMINAL,
    JobRecord,
    JobStatus,
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
from backend.metadata.sources.service import require_source
from backend.metadata.source_schedules import STRUCTURE_ENQUEUE_TASK_NAME
from backend.metadata.tasks import run_job
from backend.worker.api import STRUCTURE_SCHEDULE_KEY_PREFIX
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
    status: JobStatus | None = None,
) -> list[JobRecord]:
    """List Jobs whose input.source_id matches; Source must exist."""
    require_source(source_id)
    return [
        job
        for job in get_job_store().list(kind=kind, status=status)
        if job.input.get("source_id") == source_id
    ]


def enqueue_structure_job(
    *,
    source_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None = None,
    trigger_kind: str = "user",
    trigger_ref: str | None = None,
) -> JobRecord:
    """Validate Source, create structure Job, dispatch worker, audit user enqueue."""
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
    resolved_ref = trigger_ref if trigger_ref is not None else actor_user_id
    job = create_queued_job(
        kind="structure",
        input={"source_id": source_id},
        created_by=actor_user_id,
        summary=summary,
        trigger_kind=trigger_kind,
        trigger_ref=resolved_ref,
        log_body=queued_line,
    )
    dispatch_queued_job(job)
    if trigger_kind == "user":
        persist_audit_event(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="job",
            resource_id=job.id,
            action="job.enqueue",
            result="success",
            detail={"kind": "structure", "source_id": source_id},
        )
    return job


def fire_scheduled_structure(source_id: str) -> dict[str, str]:
    """Beat tick: enqueue a structure Job or skip overlap / unusable Source."""
    record = get_schedule_store().get_by_key(
        f"{STRUCTURE_SCHEDULE_KEY_PREFIX}{source_id}"
    )
    trigger_ref = record.id if record is not None else None
    try:
        job = enqueue_structure_job(
            source_id=source_id,
            actor_user_id=None,
            trigger_kind="schedule",
            trigger_ref=trigger_ref,
        )
        return {"status": "queued", "job_id": job.id}
    except JobAlreadyActive:
        logger.info("scheduled structure skipped: already active source_id=%s", source_id)
        return {"status": "skipped", "reason": "already_active"}
    except (JobSourceDisabled, JobInputInvalid, SourceNotFound) as exc:
        logger.info(
            "scheduled structure skipped: source_unusable source_id=%s error=%s",
            source_id,
            exc.code,
        )
        return {"status": "skipped", "reason": "source_unusable"}


@shared_task(name=STRUCTURE_ENQUEUE_TASK_NAME)
def enqueue_scheduled_structure(source_id: str) -> dict[str, str]:
    """Lightweight Beat tick: enqueue a structure Job via the Source facade."""
    return fire_scheduled_structure(source_id)
