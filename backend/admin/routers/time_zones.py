"""Shared IANA zone catalog for Console pickers."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.admin.deps import require_permission
from backend.admin.user_store import UserRecord
from backend.core.time_zones import iana_zone_ids, zone_aliases

router = APIRouter(tags=["time-zones"])


class TimeZoneOut(BaseModel):
    id: str
    aliases: list[str]


class TimeZoneListResponse(BaseModel):
    items: list[TimeZoneOut]


@router.get("/time-zones", response_model=TimeZoneListResponse)
def list_time_zones(
    _: UserRecord = Depends(require_permission("console:access")),
) -> TimeZoneListResponse:
    aliases = zone_aliases()
    return TimeZoneListResponse(
        items=[
            TimeZoneOut(id=zone_id, aliases=list(aliases.get(zone_id, ())))
            for zone_id in iana_zone_ids()
        ]
    )
