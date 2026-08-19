"""Source-scoped Scheduled Task facade HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.core.pagination import PageParams, page_params
from backend.jobs.api import get_schedule_name_store, present_jobs
from backend.jobs.schemas.jobs import JobListResponse
from backend.jobs.store import JobStatus
from backend.metadata.source_jobs import run_structure_schedule
from backend.metadata.source_schedules import (
    create_structure_schedule,
    list_jobs_for_schedule,
    list_structure_schedules,
)
from backend.worker.schemas.schedules import ScheduleListResponse

router = APIRouter(tags=["schedules-catalog"])


class CreateStructureScheduleRequest(BaseModel):
    kind: str
    cron: str | None = None
    interval_seconds: int | None = None
    schedule_timezone: str = "UTC"
    enabled: bool = True
    name: str | None = None
    running_timeout_sec: int | None = None


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
        running_timeout_sec=payload.running_timeout_sec,
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
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> ScheduleListResponse:
    items, total = list_structure_schedules(
        source_id, limit=page.limit, offset=page.offset
    )
    return ScheduleListResponse(
        items=items, total=total, limit=page.limit, offset=page.offset
    )


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
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "job": present_jobs(
                [job], users=users, schedules=get_schedule_name_store()
            )[0].model_dump(mode="json")
        },
    )


@router.get("/schedules/{schedule_id}/jobs", response_model=JobListResponse)
def list_schedule_jobs(
    schedule_id: str,
    kind: str | None = None,
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
    _: UserRecord = Depends(require_permission("jobs:run")),
    users: UserStore = Depends(get_user_store),
) -> JobListResponse:
    records, total = list_jobs_for_schedule(
        schedule_id,
        kind=kind,
        status=status_filter,
        limit=page.limit,
        offset=page.offset,
    )
    return JobListResponse(
        items=present_jobs(
            records, users=users, schedules=get_schedule_name_store()
        ),
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
