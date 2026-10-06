"""Source-scoped Scheduled Task facade HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord, UserStore, get_user_store
from backend.core.pagination import PageParams, page_params
from backend.core.time import Instant
from backend.jobs.api import get_schedule_name_store, present_jobs
from backend.jobs.schemas.jobs import JobListResponse
from backend.jobs.store import JobStatus
from backend.metadata.catalog_embed_jobs.schedule import (
    is_catalog_embed_schedule,
    run_catalog_embed_schedule_now,
)
from backend.metadata.source_jobs import run_source_schedule as enqueue_run_now
from backend.metadata.source_schedules import (
    create_source_schedule as insert_source_schedule,
    list_jobs_for_schedule,
    list_source_schedules as list_source_schedule_rows,
    require_runnable_schedule,
)
from backend.worker.api import current_schedule_timezone
from backend.worker.schemas.schedules import ScheduleListResponse

router = APIRouter(tags=["schedules-catalog"])


class CreateSourceScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    cron: str | None = None
    interval_seconds: int | None = None
    enabled: bool = True
    name: str | None = None
    running_timeout_sec: int | None = None
    start_at: Instant | None = None


@router.post("/sources/{source_id}/schedules", status_code=status.HTTP_201_CREATED)
def create_source_schedule(
    source_id: str,
    payload: CreateSourceScheduleRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
) -> JSONResponse:
    schedule = insert_source_schedule(
        source_id=source_id,
        kind=payload.kind,
        cron=payload.cron,
        interval_seconds=payload.interval_seconds,
        enabled=payload.enabled,
        name=payload.name,
        running_timeout_sec=payload.running_timeout_sec,
        start_at=payload.start_at,
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
    items, total = list_source_schedule_rows(
        source_id, limit=page.limit, offset=page.offset
    )
    return ScheduleListResponse(
        items=items,
        total=total,
        limit=page.limit,
        offset=page.offset,
        cron_timezone=current_schedule_timezone(),
    )


@router.post("/schedules/{schedule_id}/run", status_code=status.HTTP_202_ACCEPTED)
def run_source_schedule(
    schedule_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
    users: UserStore = Depends(get_user_store),
) -> JSONResponse:
    record = require_runnable_schedule(schedule_id)
    actor_token_id = get_actor_token_id(request)
    if is_catalog_embed_schedule(record):
        job = run_catalog_embed_schedule_now(
            actor_user_id=user.id,
            actor_token_id=actor_token_id,
        )
    else:
        job = enqueue_run_now(
            schedule_id=schedule_id,
            actor_user_id=user.id,
            actor_token_id=actor_token_id,
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
        items=present_jobs(records, users=users, schedules=get_schedule_name_store()),
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
