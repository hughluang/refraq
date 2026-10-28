"""Celery shared task for Entity Job kinds."""

from __future__ import annotations

import logging

from datetime import timedelta

from celery import shared_task
from sqlalchemy import text

from backend.core.time import utc_now
from backend.entity.access.store import get_access_store
from backend.entity.align import run_entity_table_job
from backend.entity.change_log import (
    CHANGE_LOG_SCHEMA,
    ENTRY_TABLE,
    delete_entries_before,
    list_effectives,
)
from backend.entity.ddl import qualified_table
from backend.entity.parameters import access_log_retention_days
from backend.entity.entity_db import (
    get_entity_engine,
    open_entity_pool_when_persistent,
    reset_entity_engine,
)
from backend.jobs.store import TERMINAL, append_job_log, get_job_store, mark_failed
from backend.jobs.supervise import supervise

logger = logging.getLogger(__name__)

_SUMMARY_MAX = 400
ACCESS_LOG_SCHEDULE_KEY = "entity_access_log_retention"
ACCESS_LOG_TASK_NAME = "backend.worker.tasks.purge_access_logs"
CHANGE_LOG_SCHEDULE_KEY = "entity_change_log_retention"
CHANGE_LOG_TASK_NAME = "backend.worker.tasks.purge_change_logs"
CHANGE_LOG_INTERVAL_SECONDS = 86400


def purge_expired_access_logs() -> int:
    """Delete access-log rows older than the retention parameter."""
    cutoff = utc_now() - timedelta(days=access_log_retention_days())
    return get_access_store().delete_logs_before(cutoff)


def purge_expired_change_logs() -> int:
    """Delete expired change-log entries. Off and never-expire rows are skipped."""
    now = utc_now()
    deleted = 0
    entry = qualified_table(CHANGE_LOG_SCHEMA, ENTRY_TABLE)
    with get_entity_engine().begin() as conn:
        for record in list_effectives(conn):
            days = record.retention_days
            if not record.recording or days is None:
                continue
            cutoff = now - timedelta(days=days)
            count = conn.execute(
                text(
                    f"SELECT count(*) FROM {entry} "
                    "WHERE entity_id = :entity_id AND occurred_at < :cutoff"
                ),
                {"entity_id": record.entity_id, "cutoff": cutoff},
            ).scalar_one()
            delete_entries_before(conn, record.entity_id, cutoff)
            deleted += int(count)
    return deleted


def init_worker_entity_pool() -> None:
    """Probe-open the entity pool, then dispose so prefork starts clean.

    Raises on a persistent worker that cannot open the URL. The worker start
    gate turns that exception into process abort; this function does not exit.
    """
    open_entity_pool_when_persistent()
    reset_entity_engine()


@shared_task(name="backend.entity.tasks.run_job")
def run_job(job_id: str) -> dict[str, str]:
    try:
        return supervise(job_id, "backend.entity.align:run_entity_table_job")
    except Exception as exc:  # noqa: BLE001
        current = get_job_store().get(job_id)
        logger.exception("entity run_job aborted job_id=%s", job_id)
        if current is not None and current.status not in TERMINAL:
            summary = str(exc)
            if len(summary) > _SUMMARY_MAX:
                summary = summary[:_SUMMARY_MAX] + "…"
            append_job_log(
                job_id,
                level="error",
                message=f"failed: JOB_EXECUTION_FAILED — {summary}",
            )
            mark_failed(
                job_id,
                error_code="JOB_EXECUTION_FAILED",
                error_summary=summary,
            )
            return {"status": "failed", "error_code": "JOB_EXECUTION_FAILED"}
        raise
