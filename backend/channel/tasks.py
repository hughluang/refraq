"""Celery task for channel_run Jobs."""

from __future__ import annotations

import logging

from celery import shared_task

from backend.jobs.store import TERMINAL, get_job_store, mark_failed

logger = logging.getLogger(__name__)


@shared_task(name="backend.channel.tasks.run_job")
def run_job(job_id: str) -> dict[str, str]:
    try:
        from backend.channel.runner import note_killed_run
        from backend.jobs.supervise import supervise

        result = supervise(job_id, "backend.channel.runner:run_channel_job")
        if result.get("status") == "cancelled":
            note_killed_run(job_id)
        return result
    except Exception as exc:  # noqa: BLE001
        current = get_job_store().get(job_id)
        logger.exception("channel_run failed")
        if current is not None and current.status not in TERMINAL:
            summary = str(exc)[:400]
            mark_failed(job_id, error_code="JOB_EXECUTION_FAILED", error_summary=summary)
            return {"status": "failed"}
        raise
