"""Mechanism Job HTTP adapters (by Job id / platform list)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.core.pagination import PageParams, page_params
from backend.core.config import get_settings
from backend.jobs.api import (
    get_schedule_name_store,
    present_jobs,
    revoke_queued_delivery,
)
from backend.jobs.errors import JobNotCancellable, JobNotFound
from backend.jobs.schemas.jobs import JobListResponse, JobLogsResponse, JobResponse
from backend.jobs.store import (
    TERMINAL,
    JobStatus,
    append_job_log,
    get_job_store,
    mark_cancelled,
)

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    _: UserRecord = Depends(require_permission("jobs:run")),
    users: UserStore = Depends(get_user_store),
    kind: str | None = Query(default=None),
    status: JobStatus | None = Query(default=None),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> JobListResponse:
    items, total = get_job_store().list(
        kind=kind, status=status, limit=page.limit, offset=page.offset
    )
    return JobListResponse(
        items=present_jobs(items, users=users, schedules=get_schedule_name_store()),
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    _: UserRecord = Depends(require_permission("jobs:run")),
    users: UserStore = Depends(get_user_store),
) -> JobResponse:
    record = get_job_store().get(job_id)
    if record is None:
        raise JobNotFound()
    return JobResponse(
        job=present_jobs([record], users=users, schedules=get_schedule_name_store())[0]
    )


@router.get("/jobs/{job_id}/logs", response_model=JobLogsResponse)
def get_job_logs(
    job_id: str,
    _: UserRecord = Depends(require_permission("jobs:run")),
) -> JobLogsResponse:
    record = get_job_store().get(job_id)
    if record is None:
        raise JobNotFound()
    return JobLogsResponse(
        job_id=record.id,
        body=record.log_body,
        updated_at=record.log_updated_at,
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
    users: UserStore = Depends(get_user_store),
) -> JobResponse:
    record = get_job_store().get(job_id)
    if record is None:
        raise JobNotFound()
    if record.status in TERMINAL:
        raise JobNotCancellable()
    was_queued = record.status == "queued"
    updated = mark_cancelled(job_id)
    if updated is None or updated.status != "cancelled":
        # Race: another writer already terminalized the row.
        raise JobNotCancellable()
    logged = append_job_log(job_id, level="warn", message="cancelled")
    assert logged is not None
    if was_queued:
        revoke_queued_delivery(job_id, settings=get_settings())
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="job",
        resource_id=job_id,
        action="job.cancel",
        result="success",
        detail={},
    )
    return JobResponse(
        job=present_jobs([logged], users=users, schedules=get_schedule_name_store())[0]
    )
