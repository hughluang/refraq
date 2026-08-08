"""Platform Celery tasks (system schedules)."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="backend.worker.tasks.reap_stuck_jobs")
def reap_stuck_jobs() -> dict[str, int]:
    from backend.jobs.store import reap_stuck_running_jobs

    count = reap_stuck_running_jobs()
    return {"reaped": count}
