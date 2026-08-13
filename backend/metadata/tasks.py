"""Celery shared tasks for metadata Job kind handlers."""

from __future__ import annotations

from celery import shared_task

from backend.jobs.store import get_job_store, mark_failed
from backend.metadata.structure_jobs import service as structure_jobs


@shared_task(name="backend.metadata.tasks.run_job")
def run_job(job_id: str) -> dict[str, str]:
    """Dispatch Job kind handlers via domain runtime modules."""

    current = get_job_store().get(job_id)
    if current is None:
        return {"status": "missing"}
    if current.status == "cancelled":
        return {"status": "cancelled"}
    if current.kind == "structure":
        return structure_jobs.run_structure_job(job_id)
    mark_failed(
        job_id,
        error_code="JOB_INPUT_INVALID",
        error_summary=f"No handler for job kind: {current.kind}",
    )
    return {"status": "failed", "error_code": "JOB_INPUT_INVALID"}
