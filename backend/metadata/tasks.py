"""Celery shared tasks for metadata Job kind handlers."""

from __future__ import annotations

import logging

from celery import shared_task

from backend.jobs.store import TERMINAL, append_job_log, get_job_store, mark_failed
from backend.metadata.join_detection_jobs.service import run_join_detection_job
from backend.metadata.structure_jobs.service import run_structure_job

logger = logging.getLogger(__name__)

_SUMMARY_MAX = 400


@shared_task(name="backend.metadata.tasks.run_job")
def run_job(job_id: str) -> dict[str, str]:
    """Dispatch Job kind handlers via domain runners."""

    try:
        return _dispatch_job(job_id)
    except Exception as exc:  # noqa: BLE001
        current = get_job_store().get(job_id)
        logger.exception("run_job aborted job_id=%s", job_id)
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


def _dispatch_job(job_id: str) -> dict[str, str]:
    current = get_job_store().get(job_id)
    if current is None:
        return {"status": "missing"}
    if current.status in TERMINAL:
        return {"status": current.status}
    if current.kind == "structure":
        return run_structure_job(job_id)
    if current.kind == "join_detection":
        return run_join_detection_job(job_id)
    mark_failed(
        job_id,
        error_code="JOB_INPUT_INVALID",
        error_summary=f"No handler for job kind: {current.kind}",
    )
    return {"status": "failed", "error_code": "JOB_INPUT_INVALID"}
