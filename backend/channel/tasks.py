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
from backend.channel.inbound_dedup import get_inbound_dedup_store
from backend.channel.inbound_rejections import get_inbound_rejection_store
from backend.channel.parameters import (
    DEDUP_SCHEDULE_KEY,
    DEDUP_TASK_NAME,
    REJECTION_SCHEDULE_KEY,
    REJECTION_TASK_NAME,
    RUN_RECORD_SCHEDULE_KEY,
    RUN_RECORD_TASK_NAME,
    channel_run_record_retention_days,
    inbound_rejection_retention_days,
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
        _release_settled_inbound_dedup(job_id, result.get("status"))
        return result
    except Exception as exc:  # noqa: BLE001
        current = get_job_store().get(job_id)
        logger.exception("channel_run failed")
        if current is not None and current.status not in TERMINAL:
            summary = str(exc)[:400]
            mark_failed(job_id, error_code="JOB_EXECUTION_FAILED", error_summary=summary)
            seal_dataset_expiry(job_id)
            _release_settled_inbound_dedup(job_id, "failed")
            return {"status": "failed"}
        if current is not None and current.status in TERMINAL:
            seal_dataset_expiry(job_id)
            _release_settled_inbound_dedup(job_id, current.status)
        raise


def _release_settled_inbound_dedup(job_id: str, status: object) -> None:
    """Drop an unanswered event id once its run is terminal.

    A keeping policy may already have deleted the Job row. The dedup record
    still names that job, and an answered record is left in place.
    """
    if status in {"queued", "running"}:
        return
    get_inbound_dedup_store().release_unanswered(job_id)


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


def purge_expired_inbound_rejections() -> int:
    """Delete inbound rejections older than the retention parameter."""
    cutoff = utc_now() - timedelta(days=inbound_rejection_retention_days())
    return get_inbound_rejection_store().delete_received_before(cutoff)


@shared_task(name=REJECTION_TASK_NAME)
def purge_inbound_rejections() -> dict[str, int]:
    record = get_schedule_store().get_by_key(REJECTION_SCHEDULE_KEY)
    if record is not None:
        consume_due_tick(record.id)
    return {"deleted": purge_expired_inbound_rejections()}


@shared_task(name=DEDUP_TASK_NAME)
def purge_inbound_dedup() -> dict[str, int]:
    """Delete dedup records whose window has elapsed.

    The window is stored on the record. Run-keeping settings do not apply.
    """
    record = get_schedule_store().get_by_key(DEDUP_SCHEDULE_KEY)
    if record is not None:
        consume_due_tick(record.id)
    return {"deleted": get_inbound_dedup_store().delete_expired(utc_now())}
