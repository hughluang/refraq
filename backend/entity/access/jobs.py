"""Enqueue entity_access_views jobs. A run compiles the latest policy revision."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from backend.entity.access.store import get_access_store
from backend.entity.jobs import IN_FLIGHT, dispatch_entity_job
from backend.entity.kinds import KIND_ACCESS_VIEWS
from backend.jobs.store import (
    JobRecord,
    create_queued_job,
    format_job_log_line,
    get_job_store,
)

__all__ = [
    "enqueue_view_job",
    "failed_recently",
    "latest_view_job",
    "view_generation_state",
]


def enqueue_view_job(
    entity_id: str,
    *,
    policy_revision: int,
    trigger_kind: str,
    trigger_ref: str | None,
    created_by: str | None,
    label: str,
) -> JobRecord:
    """Return the in-flight job when one already exists for this Entity."""
    inflight = _inflight(entity_id)
    if inflight is not None:
        return inflight
    job = create_queued_job(
        kind=KIND_ACCESS_VIEWS,
        input={"entity_id": entity_id, "policy_revision": policy_revision},
        created_by=created_by,
        summary=f"entity_access_views · {label}",
        trigger_kind=trigger_kind,
        trigger_ref=trigger_ref,
        log_body=format_job_log_line(
            level="info", message="queued profile view regeneration"
        ),
    )
    dispatch_entity_job(job)
    return job


def failed_recently(entity_id: str, *, now: datetime, within: timedelta) -> bool:
    """True when the latest run for this Entity failed less than ``within`` ago.

    A run compiles the latest revision, so its input revision may be stale.
    """
    job = latest_view_job(entity_id)
    if job is None or job.status != "failed":
        return False
    ended = job.finished_at or job.created_at
    return now - ended < within


def latest_view_job(entity_id: str) -> JobRecord | None:
    records, _total = get_job_store().list(kind=KIND_ACCESS_VIEWS)
    mine = [item for item in records if item.input.get("entity_id") == entity_id]
    if not mine:
        return None
    return max(mine, key=lambda item: item.created_at)


def view_generation_state(entity_id: str, *, policy_revision: int, has_head: bool) -> dict[str, Any]:
    """ready, pending, or failed. Failed still refuses data until a later run succeeds."""
    applied = get_access_store().views_revision(entity_id)
    job = latest_view_job(entity_id)
    inflight = job is not None and job.status in IN_FLIGHT
    if not has_head:
        state = "ready"
    elif job is not None and job.status == "failed" and applied != policy_revision:
        state = "failed"
    elif applied != policy_revision or inflight:
        state = "pending"
    else:
        state = "ready"
    return {
        "state": state,
        "applied_revision": applied,
        "latest_job_id": None if job is None else job.id,
    }


def _inflight(entity_id: str) -> JobRecord | None:
    records, _total = get_job_store().list(kind=KIND_ACCESS_VIEWS)
    for record in records:
        if record.status not in IN_FLIGHT:
            continue
        if record.input.get("entity_id") == entity_id:
            return record
    return None
