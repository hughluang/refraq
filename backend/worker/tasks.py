"""Platform Celery tasks (system schedules)."""

from __future__ import annotations

from celery import shared_task

from backend.channel.tasks import seal_dataset_expiry
from backend.entity.tasks import (
    ACCESS_LOG_SCHEDULE_KEY,
    CHANGE_LOG_SCHEDULE_KEY,
    CHANGE_LOG_TASK_NAME,
    purge_expired_access_logs,
    purge_expired_change_logs,
)
from backend.jobs.store import get_job_store, reap_stuck_running_jobs
from backend.worker.due import consume_due_tick
from backend.worker.models import REAPER_SCHEDULE_KEY
from backend.worker.schedules import get_schedule_store


@shared_task(name="backend.worker.tasks.reap_stuck_jobs")
def reap_stuck_jobs() -> dict[str, int]:
    record = get_schedule_store().get_by_key(REAPER_SCHEDULE_KEY)
    if record is not None:
        consume_due_tick(record.id)
    running_ids = [item.id for item in get_job_store().list(status="running")[0]]
    count = reap_stuck_running_jobs()
    for job_id in running_ids:
        seal_dataset_expiry(job_id)
    return {"reaped": count}


@shared_task(name="backend.worker.tasks.purge_access_logs")
def purge_access_logs() -> dict[str, int]:
    record = get_schedule_store().get_by_key(ACCESS_LOG_SCHEDULE_KEY)
    if record is not None:
        consume_due_tick(record.id)
    return {"deleted": purge_expired_access_logs()}


@shared_task(name=CHANGE_LOG_TASK_NAME)
def purge_change_logs() -> dict[str, int]:
    record = get_schedule_store().get_by_key(CHANGE_LOG_SCHEDULE_KEY)
    if record is not None:
        consume_due_tick(record.id)
    return {"deleted": purge_expired_change_logs()}
