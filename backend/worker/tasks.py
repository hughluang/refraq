"""Platform Celery tasks (system schedules)."""

from __future__ import annotations

from backend.worker.app import celery_app


@celery_app.task(name="backend.worker.tasks.reap_stuck_ingestion_jobs")
def reap_stuck_ingestion_jobs() -> dict[str, int]:
    from backend.metadata.jobs import reap_stuck_running_jobs

    count = reap_stuck_running_jobs()
    return {"reaped": count}
