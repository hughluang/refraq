"""Source-scoped Job facade HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.jobs.api import actor_names_for_jobs, job_out
from backend.jobs.schemas.jobs import JobListResponse
from backend.jobs.store import JobStatus
from backend.metadata.source_jobs import enqueue_structure_job, list_jobs_for_source
from backend.metadata.schemas.jobs import EnqueueStructureJobRequest

router = APIRouter(tags=["jobs-catalog"])


@router.post("/sources/{source_id}/jobs", status_code=status.HTTP_202_ACCEPTED)
def enqueue_source_job(
    source_id: str,
    payload: EnqueueStructureJobRequest,  # noqa: ARG001 — OpenAPI body; kind fixed by schema
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
    users: UserStore = Depends(get_user_store),
) -> JSONResponse:
    job = enqueue_structure_job(
        source_id=source_id,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    names = actor_names_for_jobs([job], users)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"job": job_out(job, actor_names=names).model_dump(mode="json")},
    )


@router.get("/sources/{source_id}/jobs", response_model=JobListResponse)
def list_source_jobs(
    source_id: str,
    kind: str | None = None,
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    _: UserRecord = Depends(require_permission("jobs:run")),
    users: UserStore = Depends(get_user_store),
) -> JobListResponse:
    records = list_jobs_for_source(source_id, kind=kind, status=status_filter)
    names = actor_names_for_jobs(records, users)
    return JobListResponse(items=[job_out(r, actor_names=names) for r in records])
