"""Celery tasks for metadata Job kind handlers."""

from __future__ import annotations

from backend.jobs.store import mark_failed
from backend.metadata.runner import run_structure_job
from backend.worker.app import celery_app


@celery_app.task(name="backend.metadata.tasks.run_job")
def run_job(job_id: str) -> dict[str, str]:
    """Dispatch Job kind handlers via domain runners."""
    from backend.jobs.store import get_job_store

    current = get_job_store().get(job_id)
    if current is None:
        return {"status": "missing"}
    if current.status == "cancelled":
        return {"status": "cancelled"}
    if current.kind == "structure":
        return run_structure_job(job_id)
    mark_failed(
        job_id,
        error_code="JOB_INPUT_INVALID",
        error_summary=f"No handler for job kind: {current.kind}",
    )
    return {"status": "failed", "error_code": "JOB_INPUT_INVALID"}
