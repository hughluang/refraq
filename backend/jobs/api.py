"""Published Job helpers that hold cross-package seam policy.

Mechanism store ports and errors are imported from ``jobs.store`` /
``jobs.errors``. This module owns Celery delivery revoke (so callers never
import ``worker.app``) and JobRecord→JobOut presentation mapping.
"""

from __future__ import annotations

from celery import Celery

from backend.core.celery_broker import celery_broker_url
from backend.core.config import Settings
from backend.jobs.schemas.jobs import JobOut
from backend.jobs.store import JobRecord

__all__ = ["job_out", "revoke_queued_delivery"]


def job_out(record: JobRecord) -> JobOut:
    """Map a mechanism JobRecord to the shared HTTP/MCP response shape."""
    return JobOut(
        id=record.id,
        kind=record.kind,
        status=record.status,
        input=dict(record.input),
        created_by_user_id=record.created_by,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        error_code=record.error_code,
        error_message=record.error_summary,
    )


def revoke_queued_delivery(job_id: str, *, settings: Settings) -> None:
    """Best-effort revoke of a queued Celery delivery for a Job id.

    Uses a control-only Celery client. Callers must pass settings (broker
    resolved via ``celery_broker_url``) rather than importing ``worker.app``.
    """
    control_app = Celery("refraq-control")
    control_app.conf.broker_url = celery_broker_url(settings)
    control_app.control.revoke(job_id, terminate=False)
