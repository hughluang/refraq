"""Enqueue Ingestion Jobs onto Celery after the Job row is durable."""

from __future__ import annotations

from backend.metadata.jobs import IngestionJobRecord, get_job_store
from backend.metadata.tasks import run_ingestion_job


def enqueue_ingestion_job(job: IngestionJobRecord) -> str:
    """Dispatch Celery task for an already-persisted queued Job.

    Callers that create the Job inside a DB transaction must invoke this only
    after commit (or use an on_commit hook). Companion base HTTP enqueue is Slice A.
    """
    async_result = run_ingestion_job.apply_async(
        args=[job.id],
        task_id=job.id,
    )
    store = get_job_store()
    record = store.get(job.id)
    if record is not None:
        record.celery_task_id = async_result.id
        store.save(record)
    return async_result.id
