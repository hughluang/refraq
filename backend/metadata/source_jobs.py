"""Domain facade for Source-scoped Jobs."""

from __future__ import annotations

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
)
from backend.metadata.sources.service import require_source
from backend.metadata.tasks import run_job


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
    actor_user_id: str,
    actor_token_id: str | None = None,
) -> JobRecord:
    """Validate Source, create structure Job, dispatch worker, audit success."""
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
        trigger_kind="user",
        trigger_ref=actor_user_id,
        log_body=queued_line,
    )
    dispatch_queued_job(job)
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
