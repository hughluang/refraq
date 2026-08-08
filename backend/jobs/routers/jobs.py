"""Mechanism Job HTTP adapters (by Job id)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.core.config import get_settings
from backend.jobs.api import job_out, revoke_queued_delivery
from backend.jobs.errors import JobNotCancellable, JobNotFound
from backend.jobs.schemas.jobs import JobResponse
from backend.jobs.store import TERMINAL, get_job_store, mark_cancelled

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    _: UserRecord = Depends(require_permission("jobs:run")),
) -> JobResponse:
    record = get_job_store().get(job_id)
    if record is None:
        raise JobNotFound()
    return JobResponse(job=job_out(record))


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
) -> JobResponse:
    record = get_job_store().get(job_id)
    if record is None:
        raise JobNotFound()
    if record.status in TERMINAL:
        raise JobNotCancellable()
    was_queued = record.status == "queued"
    updated = mark_cancelled(job_id)
    assert updated is not None
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
    return JobResponse(job=job_out(updated))
