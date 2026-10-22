"""Celery tasks for channel_run Jobs and Data Channel system schedules."""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task

from backend.channel.dataset_registry import (
    drop_datasets_for_due_runs,
    drop_expired_datasets,
    drop_orphan_dataset_tables,
    seal_dataset_expiry,
    seal_unsealed_terminal_datasets,
)
from backend.channel.parameters import (
    RUN_RECORD_SCHEDULE_KEY,
    RUN_RECORD_TASK_NAME,
    channel_run_record_retention_days,
)
from backend.channel.run_store import get_run_store, note_killed_run
from backend.core.time import utc_now
from backend.jobs.store import TERMINAL, get_job_store, mark_failed
from backend.jobs.supervise import supervise
from backend.worker.due import consume_due_tick
from backend.worker.schedules import get_schedule_store

logger = logging.getLogger(__name__)


@shared_task(name="backend.channel.tasks.run_job")
def run_job(job_id: str) -> dict[str, str]:
    try:
        result = supervise(job_id, "backend.channel.runner:run_channel_job")
        seal_dataset_expiry(job_id)
        if result.get("status") == "cancelled":
            note_killed_run(job_id)
        return result
    except Exception as exc:  # noqa: BLE001
        current = get_job_store().get(job_id)
        logger.exception("channel_run failed")
        if current is not None and current.status not in TERMINAL:
            summary = str(exc)[:400]
            mark_failed(job_id, error_code="JOB_EXECUTION_FAILED", error_summary=summary)
            seal_dataset_expiry(job_id)
            return {"status": "failed"}
        if current is not None and current.status in TERMINAL:
            seal_dataset_expiry(job_id)
        raise


def purge_expired_run_records() -> int:
    """Delete terminal channel run records older than the retention parameter.

    First seal any still-null dataset whose job is terminal, drop dataset
    tables that are due, and drop tables owned by runs about to be deleted.
    Node executions go with the run. Jobs stay. ``ds_*`` tables with no
    loading or ready registry row are dropped after the run records.
    """
    seal_unsealed_terminal_datasets()
    now = utc_now()
    drop_expired_datasets(now)
    cutoff = now - timedelta(days=channel_run_record_retention_days())
    drop_datasets_for_due_runs(cutoff)
    deleted = get_run_store().delete_expired_terminal_runs(cutoff)
    drop_orphan_dataset_tables()
    return deleted


@shared_task(name=RUN_RECORD_TASK_NAME)
def purge_run_records() -> dict[str, int]:
    record = get_schedule_store().get_by_key(RUN_RECORD_SCHEDULE_KEY)
    if record is not None:
        consume_due_tick(record.id)
    return {"deleted": purge_expired_run_records()}
