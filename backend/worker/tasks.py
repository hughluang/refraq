"""Platform Celery tasks (system schedules)."""

from __future__ import annotations

from celery import shared_task

from backend.jobs.store import reap_stuck_running_jobs
from backend.worker.due import consume_due_tick
from backend.worker.models import REAPER_SCHEDULE_KEY
from backend.worker.schedules import get_schedule_store


@shared_task(name="backend.worker.tasks.reap_stuck_jobs")
def reap_stuck_jobs() -> dict[str, int]:
    record = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
    if record is not None:
        consume_due_tick(record.id)
    count = reap_stuck_running_jobs()
    return {"reaped": count}
