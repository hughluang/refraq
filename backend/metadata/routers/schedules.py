"""Source-scoped Scheduled Task facade HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.jobs.api import actor_names_for_jobs, job_out
from backend.jobs.schemas.jobs import JobListResponse
from backend.jobs.store import JobStatus
from backend.metadata.source_jobs import run_structure_schedule
from backend.metadata.source_schedules import (
    create_structure_schedule,
    list_jobs_for_schedule,
    list_structure_schedules,
)
from backend.worker.api import schedule_names_for_jobs
from backend.worker.schedules import get_schedule_store
from backend.worker.schemas.schedules import ScheduleListResponse

router = APIRouter(tags=["schedules-catalog"])


class CreateStructureScheduleRequest(BaseModel):
    kind: str
    cron: str | None = None
    interval_seconds: int | None = None
    schedule_timezone: str = "UTC"
    enabled: bool = True
    name: str | None = None


@router.post("/sources/{source_id}/schedules", status_code=status.HTTP_201_CREATED)
def create_source_schedule(
    source_id: str,
    payload: CreateStructureScheduleRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
) -> JSONResponse:
    schedule = create_structure_schedule(
        source_id=source_id,
        kind=payload.kind,
        cron=payload.cron,
        interval_seconds=payload.interval_seconds,
        schedule_timezone=payload.schedule_timezone,
        enabled=payload.enabled,
        name=payload.name,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"schedule": schedule.model_dump(mode="json")},
    )


@router.get("/sources/{source_id}/schedules", response_model=ScheduleListResponse)
def list_source_schedules(
    source_id: str,
    _: UserRecord = Depends(require_permission("jobs:run")),
) -> ScheduleListResponse:
    return ScheduleListResponse(items=list_structure_schedules(source_id))


@router.post("/schedules/{schedule_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_source_schedule(
    schedule_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
    users: UserStore = Depends(get_user_store),
) -> JSONResponse:
    job = run_structure_schedule(
        schedule_id=schedule_id,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    names = actor_names_for_jobs([job], users)
    schedule_names = schedule_names_for_jobs([job], get_schedule_store())
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "job": job_out(
                job, actor_names=names, schedule_names=schedule_names
            ).model_dump(mode="json")
        },
    )


@router.get("/schedules/{schedule_id}/jobs", response_model=JobListResponse)
def list_schedule_jobs(
    schedule_id: str,
    kind: str | None = None,
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    _: UserRecord = Depends(require_permission("jobs:run")),
    users: UserStore = Depends(get_user_store),
) -> JobListResponse:
    records = list_jobs_for_schedule(
        schedule_id, kind=kind, status=status_filter
    )
    names = actor_names_for_jobs(records, users)
    schedule_names = schedule_names_for_jobs(records, get_schedule_store())
    return JobListResponse(
        items=[
            job_out(r, actor_names=names, schedule_names=schedule_names)
            for r in records
        ]
    )
