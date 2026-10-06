"""Mechanism Scheduled Task HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.core.pagination import PageParams, page_params

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.metadata.source_schedules import (
    public_schedule,
    public_schedules,
    recent_jobs_by_schedule,
    schedule_label_for_record,
)
from backend.worker.api import (
    current_schedule_timezone,
    delete_schedule,
    get_schedule,
    patch_schedule,
    preview_cron_runs,
)
from backend.worker.schemas.schedules import (
    CronPreviewRequest,
    CronPreviewResponse,
    ScheduleListResponse,
    SchedulePatchRequest,
    ScheduleResponse,
)
from backend.worker.schedules import ScheduledTaskRecord, get_schedule_store

router = APIRouter(tags=["schedules"])


def _schedule_response(record: ScheduledTaskRecord) -> ScheduleResponse:
    return ScheduleResponse(
        schedule=public_schedule(
            record, recent_jobs=recent_jobs_by_schedule([record.id])[record.id]
        )
    )


@router.get("/schedules", response_model=ScheduleListResponse)
def list_platform_schedules(
    _: UserRecord = Depends(require_permission("jobs:run")),
    hidden: bool = Query(default=False),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> ScheduleListResponse:
    records, total = get_schedule_store().list(
        include_hidden=hidden, limit=page.limit, offset=page.offset
    )
    return ScheduleListResponse(
        items=public_schedules(records),
        total=total,
        limit=page.limit,
        offset=page.offset,
        cron_timezone=current_schedule_timezone(),
    )


@router.post("/schedules/cron-preview", response_model=CronPreviewResponse)
def preview_platform_cron(
    payload: CronPreviewRequest,
    _: UserRecord = Depends(require_permission("jobs:run")),
) -> CronPreviewResponse:
    zone, instants = preview_cron_runs(payload.cron, start_at=payload.start_at)
    return CronPreviewResponse(cron_timezone=zone, next_run_ats=instants)


@router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
def get_platform_schedule(
    schedule_id: str,
    _: UserRecord = Depends(require_permission("jobs:run")),
) -> ScheduleResponse:
    return _schedule_response(get_schedule(schedule_id))


@router.patch("/schedules/{schedule_id}", response_model=ScheduleResponse)
def patch_platform_schedule(
    schedule_id: str,
    payload: SchedulePatchRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
) -> ScheduleResponse:
    fields = payload.model_fields_set
    record = get_schedule(schedule_id)
    updated = patch_schedule(
        schedule_id,
        enabled=payload.enabled,
        name=schedule_label_for_record(record, payload.name),
        cron=payload.cron,
        interval_seconds=payload.interval_seconds,
        running_timeout_sec=payload.running_timeout_sec,
        start_at=payload.start_at,
        cron_set="cron" in fields,
        interval_set="interval_seconds" in fields,
        timeout_set="running_timeout_sec" in fields,
        start_at_set="start_at" in fields,
    )
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="schedule",
        resource_id=schedule_id,
        action="schedule.patch",
        result="success",
        detail={},
    )
    return _schedule_response(updated)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_platform_schedule(
    schedule_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
) -> Response:
    delete_schedule(schedule_id)
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="schedule",
        resource_id=schedule_id,
        action="schedule.delete",
        result="success",
        detail={},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
