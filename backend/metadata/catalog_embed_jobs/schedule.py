"""Site-wide catalog embedding Scheduled Task.

The scheduler does not interpret Model Service state. This module only mints
``catalog_embed`` Jobs. The runner decides whether to write vectors.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from celery import shared_task

from backend.admin.audit import persist_audit_event
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import ensure_aware_utc, parse_instant, utc_now
from backend.jobs.store import (
    JobRecord,
    UniqueScheduledForError,
    create_queued_job,
    format_job_log_line,
    get_job_store,
    mark_cancelled,
)
from backend.metadata.catalog_embed_jobs.jobs import CATALOG_EMBED_KIND
from backend.metadata.source_jobs import dispatch_queued_job
from backend.worker.api import current_schedule_timezone, initial_next_run_at
from backend.worker.due import commit_due_mint, consume_due_tick
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store

logger = logging.getLogger(__name__)

CATALOG_EMBED_SCHEDULE_KEY = "catalog_embed:site"
CATALOG_EMBED_OWNER_REF = "admin:model_services:embedding"
CATALOG_EMBED_ENQUEUE_TASK_NAME = (
    "backend.metadata.catalog_embed_jobs.schedule.fire_scheduled_catalog_embed"
)
DEFAULT_CATALOG_EMBED_CRON = "0 3 * * *"
DEFAULT_CATALOG_EMBED_NAME = "catalog embed"


def ensure_catalog_embed_schedule() -> ScheduledTaskRecord:
    """Idempotent seed for the site catalog-embed cadence. Does not rewrite cadence."""
    store = get_schedule_store()
    existing = store.get_by_key(CATALOG_EMBED_SCHEDULE_KEY)
    if existing is not None:
        return existing
    now = utc_now()
    schedule_id = f"sched_{uuid.uuid4().hex[:12]}"
    zone = current_schedule_timezone()
    next_run = initial_next_run_at(
        cron=DEFAULT_CATALOG_EMBED_CRON,
        interval_seconds=None,
        enabled=True,
        after=now,
        schedule_timezone=zone,
    )
    return store.upsert(
        ScheduledTaskRecord(
            id=schedule_id,
            key=CATALOG_EMBED_SCHEDULE_KEY,
            name=DEFAULT_CATALOG_EMBED_NAME,
            enabled=True,
            interval_seconds=None,
            cron=DEFAULT_CATALOG_EMBED_CRON,
            commitment_timezone=zone,
            task_name=CATALOG_EMBED_ENQUEUE_TASK_NAME,
            args_json=[],
            kwargs_json={"schedule_id": schedule_id},
            hidden=False,
            locked=False,
            undeletable=True,
            store_only=False,
            owner_ref=CATALOG_EMBED_OWNER_REF,
            last_run_at=now,
            next_run_at=next_run,
            created_at=now,
            updated_at=now,
        )
    )


def is_catalog_embed_schedule(record: ScheduledTaskRecord) -> bool:
    return record.key == CATALOG_EMBED_SCHEDULE_KEY


def run_catalog_embed_schedule_now(
    *,
    actor_user_id: str,
    actor_token_id: str | None,
) -> JobRecord:
    """Operator run-now. Does not move last_run_at or next_run_at."""
    record = ensure_catalog_embed_schedule()
    job = _create_job(
        schedule_id=record.id,
        actor_user_id=actor_user_id,
        scheduled_for=None,
        running_timeout_sec=record.running_timeout_sec,
        message="queued catalog embed",
    )
    dispatch_queued_job(job)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="schedule",
        resource_id=record.id,
        action="schedule.run",
        result="success",
        detail={"kind": CATALOG_EMBED_KIND, "job_id": job.id},
    )
    return job


def _create_job(
    *,
    schedule_id: str,
    actor_user_id: str | None,
    scheduled_for: datetime | None,
    running_timeout_sec: int | None,
    message: str,
    session: Any = None,
    created_at: datetime | None = None,
) -> JobRecord:
    queued_line = format_job_log_line(level="info", message=message, at=created_at)
    return create_queued_job(
        kind=CATALOG_EMBED_KIND,
        input={},
        created_by=actor_user_id,
        summary="catalog_embed",
        trigger_kind="schedule",
        trigger_ref=schedule_id,
        log_body=queued_line,
        scheduled_for=scheduled_for,
        running_timeout_sec=running_timeout_sec,
        session=session,
        created_at=created_at,
    )


def _resolve_due_at(due_at: str | datetime | None) -> datetime | None:
    if due_at is None:
        return None
    if isinstance(due_at, datetime):
        return ensure_aware_utc(due_at)
    if isinstance(due_at, str) and due_at.strip():
        return parse_instant(due_at)
    return None


def _mint_due(
    *,
    schedule_id: str,
    scheduled_for: datetime,
    now: datetime,
    cancel_immediately: bool,
    cadence: ScheduledTaskRecord | None,
    session: Any,
) -> dict[str, Any]:
    already = False
    try:
        job = _create_job(
            schedule_id=schedule_id,
            actor_user_id=None,
            scheduled_for=scheduled_for,
            running_timeout_sec=(
                cadence.running_timeout_sec if cadence is not None else None
            ),
            message="queued catalog embed",
            session=session,
            created_at=now,
        )
    except UniqueScheduledForError as exc:
        already = True
        existing_id = exc.existing_job_id or ""
        job = get_job_store().get(existing_id, session=session)
        if job is None:
            return {"status": "already_minted", "job_id": existing_id}

    mint_at = job.created_at if already else now
    if cadence is not None:
        commit_due_mint(cadence, now=now, session=session, mint_at=mint_at)

    if cancel_immediately and job.status not in ("succeeded", "failed", "cancelled"):
        cancelled = mark_cancelled(job.id, session=session)
        job = cancelled or job
        return {"status": "cancelled", "job_id": job.id, "job": job}
    if already:
        return {"status": "already_minted", "job_id": job.id, "job": job}
    return {"status": "queued", "job_id": job.id, "job": job}


@shared_task(name=CATALOG_EMBED_ENQUEUE_TASK_NAME)
def fire_scheduled_catalog_embed(
    schedule_id: str | None = None,
    due_at: str | datetime | None = None,
) -> dict[str, str]:
    """Beat tick: mint one catalog_embed Job for the delivered commitment."""
    if not schedule_id:
        logger.info("scheduled catalog_embed skipped: missing_schedule_id")
        return {"status": "skipped", "reason": "missing_schedule_id"}
    due = _resolve_due_at(due_at)
    if due is None:
        return {"status": "missing_due_at"}

    def _decide(session: Any) -> dict[str, Any]:
        outcome = consume_due_tick(schedule_id, due_at=due, session=session)
        if outcome.get("status") != "mint":
            return {"status": str(outcome.get("status"))}
        record = outcome.get("record")
        return _mint_due(
            schedule_id=schedule_id,
            scheduled_for=outcome["scheduled_for"],
            now=outcome["now"],
            cancel_immediately=bool(outcome.get("cancel_immediately")),
            cadence=record,
            session=session,
        )

    settings = get_settings()
    if settings.store_backend == "memory":
        minted = _decide(None)
    else:
        with session_scope() as session:
            minted = _decide(session)

    minted_status = minted.get("status")
    job = minted.get("job")
    if minted_status == "cancelled":
        return {"status": "cancelled", "job_id": str(minted["job_id"])}
    if minted_status == "already_minted":
        if isinstance(job, JobRecord) and job.status == "queued":
            fresh = get_schedule_store().get_by_id(schedule_id)
            if fresh is not None and fresh.enabled:
                dispatch_queued_job(job)
        return {"status": "already_minted", "job_id": str(minted.get("job_id") or "")}
    if minted_status != "queued":
        return {"status": str(minted_status)}
    dispatch_queued_job(job)
    return {"status": "queued", "job_id": job.id}
