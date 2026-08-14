"""Published Job helpers that hold cross-package seam policy.

Mechanism store ports and errors are imported from ``jobs.store`` /
``jobs.errors``. This module owns Celery delivery revoke (so callers never
import ``worker.app``) and JobRecord→JobOut presentation mapping.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from celery import Celery

from backend.admin.user_store import UserStore
from backend.core.celery_broker import celery_broker_url
from backend.core.config import Settings
from backend.jobs.schemas.jobs import JobOut
from backend.jobs.store import JobRecord

__all__ = ["actor_names_for_jobs", "job_out", "revoke_queued_delivery"]


def actor_names_for_jobs(
    records: Sequence[JobRecord], users: UserStore
) -> dict[str, str]:
    """Resolve display names for unique user trigger_ref values."""
    user_ids = {
        record.trigger_ref
        for record in records
        if record.trigger_kind == "user" and record.trigger_ref
    }
    names: dict[str, str] = {}
    for user_id in user_ids:
        user = users.get_by_id(user_id)
        if user is not None:
            names[user_id] = user.display_name
    return names


def job_out(
    record: JobRecord,
    *,
    actor_names: Mapping[str, str],
    schedule_names: Mapping[str, str],
) -> JobOut:
    """Map a mechanism JobRecord to the shared HTTP/MCP response shape."""
    trigger_actor_name: str | None = None
    if record.trigger_kind == "user" and record.trigger_ref:
        trigger_actor_name = actor_names.get(record.trigger_ref)
    trigger_schedule_name: str | None = None
    if record.trigger_kind == "schedule" and record.trigger_ref:
        trigger_schedule_name = schedule_names.get(record.trigger_ref)
    return JobOut(
        id=record.id,
        kind=record.kind,
        status=record.status,
        input=dict(record.input),
        result=record.result,
        summary=record.summary,
        trigger_kind=record.trigger_kind,
        trigger_ref=record.trigger_ref,
        trigger_actor_name=trigger_actor_name,
        trigger_schedule_name=trigger_schedule_name,
        created_by_user_id=record.created_by,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        error_code=record.error_code,
        error_message=record.error_summary,
        log_updated_at=record.log_updated_at,
    )


def revoke_queued_delivery(job_id: str, *, settings: Settings) -> None:
    """Best-effort revoke of a queued Celery delivery for a Job id.

    Uses a control-only Celery client. Callers must pass settings (broker
    resolved via ``celery_broker_url``) rather than importing ``worker.app``.
    """
    control_app = Celery("refraq-control")
    control_app.conf.broker_url = celery_broker_url(settings)
    control_app.control.revoke(job_id, terminate=False)
