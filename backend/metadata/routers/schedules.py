"""Source-scoped Scheduled Task facade HTTP adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.metadata.source_schedules import (
    delete_structure_schedule,
    get_structure_schedule,
    put_structure_schedule,
)
from backend.worker.schemas.schedules import ScheduleResponse

router = APIRouter(tags=["schedules-catalog"])


class PutStructureScheduleRequest(BaseModel):
    kind: str
    cron: str | None = None
    interval_seconds: int | None = None
    schedule_timezone: str = "UTC"
    enabled: bool = True
    name: str | None = None


@router.put("/sources/{source_id}/schedule")
def put_source_schedule(
    source_id: str,
    payload: PutStructureScheduleRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
) -> JSONResponse:
    schedule, created = put_structure_schedule(
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
        status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        content={"schedule": schedule.model_dump(mode="json")},
    )


@router.get("/sources/{source_id}/schedule", response_model=ScheduleResponse)
def get_source_schedule(
    source_id: str,
    _: UserRecord = Depends(require_permission("jobs:run")),
) -> ScheduleResponse:
    return ScheduleResponse(schedule=get_structure_schedule(source_id))


@router.delete("/sources/{source_id}/schedule", status_code=status.HTTP_204_NO_CONTENT)
def delete_source_schedule(
    source_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("jobs:run")),
) -> Response:
    delete_structure_schedule(
        source_id=source_id,
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
