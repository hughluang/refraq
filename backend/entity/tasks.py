"""Celery shared task for Entity Job kinds."""

from __future__ import annotations

import logging

from celery import shared_task

from backend.entity.align import run_entity_table_job
from backend.entity.entity_db import open_entity_pool_when_persistent, reset_entity_engine
from backend.jobs.store import TERMINAL, append_job_log, get_job_store, mark_failed

logger = logging.getLogger(__name__)

_SUMMARY_MAX = 400


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
        return run_entity_table_job(job_id)
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
