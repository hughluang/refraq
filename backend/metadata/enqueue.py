"""Enqueue Jobs onto Celery after the Job row is durable."""

from __future__ import annotations

from backend.jobs.store import JobRecord, get_job_store
from backend.metadata.tasks import run_job


def enqueue_job(job: JobRecord) -> str:
    """Dispatch Celery task for an already-persisted queued Job.

    Callers that create the Job inside a DB transaction must invoke this only
    after commit (or use an on_commit hook). Companion base HTTP enqueue is Slice A.
    """
    async_result = run_job.apply_async(
        args=[job.id],
        task_id=job.id,
    )
    job.celery_task_id = async_result.id
    get_job_store().save(job)
    return async_result.id
