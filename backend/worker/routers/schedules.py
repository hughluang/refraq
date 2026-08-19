"""Mechanism Scheduled Task HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.core.pagination import PageParams, page_params

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.metadata.source_schedules import (
    public_schedule,
    structure_schedule_label_for_record,
)
from backend.worker.api import (
    delete_schedule,
    get_schedule,
    patch_schedule,
)
from backend.worker.schemas.schedules import (
    ScheduleListResponse,
    SchedulePatchRequest,
    ScheduleResponse,
)
from backend.worker.schedules import get_schedule_store

router = APIRouter(tags=["schedules"])


@router.get("/schedules", response_model=ScheduleListResponse)
def list_platform_schedules(
    _: UserRecord = Depends(require_permission("jobs:run")),
    system: bool = Query(default=False),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> ScheduleListResponse:
    records, total = get_schedule_store().list(
        include_system=system, limit=page.limit, offset=page.offset
    )
    return ScheduleListResponse(
        items=[public_schedule(record) for record in records],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/schedules/{schedule_id}", response_model=ScheduleResponse)
def get_platform_schedule(
    schedule_id: str,
    _: UserRecord = Depends(require_permission("jobs:run")),
) -> ScheduleResponse:
    return ScheduleResponse(schedule=public_schedule(get_schedule(schedule_id)))


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
        name=structure_schedule_label_for_record(record, payload.name),
        cron=payload.cron,
        interval_seconds=payload.interval_seconds,
        schedule_timezone=payload.schedule_timezone,
        running_timeout_sec=payload.running_timeout_sec,
        cron_set="cron" in fields,
        interval_set="interval_seconds" in fields,
        timezone_set="schedule_timezone" in fields,
        timeout_set="running_timeout_sec" in fields,
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
    return ScheduleResponse(schedule=public_schedule(updated))


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
