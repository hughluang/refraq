"""Celery task for channel_run Jobs."""

from __future__ import annotations

import logging

from celery import shared_task

from backend.jobs.store import mark_failed

logger = logging.getLogger(__name__)


@shared_task(name="backend.channel.tasks.run_job")
def run_job(job_id: str) -> dict[str, str]:
    try:
        from backend.channel.runner import run_channel_job

        return run_channel_job(job_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("channel_run failed")
        summary = str(exc)[:400]
        mark_failed(job_id, error_code="JOB_EXECUTION_FAILED", error_summary=summary)
        return {"status": "failed"}
