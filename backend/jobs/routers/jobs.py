"""Mechanism Job HTTP adapters (by Job id / platform list)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.core.config import get_settings
from backend.jobs.api import actor_names_for_jobs, job_out, revoke_queued_delivery
from backend.jobs.errors import JobNotCancellable, JobNotFound
from backend.jobs.schemas.jobs import JobListResponse, JobLogsResponse, JobResponse
from backend.jobs.store import (
    TERMINAL,
    JobStatus,
    append_job_log,
    get_job_store,
    mark_cancelled,
)
from backend.worker.api import schedule_names_for_jobs
from backend.worker.schedules import get_schedule_store

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    _: UserRecord = Depends(require_permission("jobs:run")),
    users: UserStore = Depends(get_user_store),
    kind: str | None = Query(default=None),
    status: JobStatus | None = Query(default=None),
) -> JobListResponse:
    items = get_job_store().list(kind=kind, status=status)
    names = actor_names_for_jobs(items, users)
    schedule_names = schedule_names_for_jobs(items, get_schedule_store())
    return JobListResponse(
        items=[
            job_out(r, actor_names=names, schedule_names=schedule_names)
            for r in items
        ]
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
    names = actor_names_for_jobs([record], users)
    schedule_names = schedule_names_for_jobs([record], get_schedule_store())
    return JobResponse(
        job=job_out(record, actor_names=names, schedule_names=schedule_names)
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
    assert updated is not None
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
    names = actor_names_for_jobs([logged], users)
    schedule_names = schedule_names_for_jobs([logged], get_schedule_store())
    return JobResponse(
        job=job_out(logged, actor_names=names, schedule_names=schedule_names)
    )
