"""Celery tasks for metadata ingestion."""

from __future__ import annotations

from backend.metadata.jobs import (
    ERROR_HANDLER_UNAVAILABLE,
    mark_failed,
    mark_running,
)
from backend.worker.app import celery_app


@celery_app.task(name="backend.metadata.tasks.run_ingestion_job")
def run_ingestion_job(job_id: str) -> dict[str, str]:
    """Stub handler until connectors exist: mark failed with a stable error code."""
    current = mark_running(job_id, celery_task_id=job_id)
    if current is None:
        return {"status": "missing"}
    if current.status != "running":
        return {"status": current.status}
    mark_failed(
        job_id,
        error_code=ERROR_HANDLER_UNAVAILABLE,
        error_summary="Ingestion connector handler is not available yet",
    )
    return {"status": "failed", "error_code": ERROR_HANDLER_UNAVAILABLE}
