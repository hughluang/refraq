"""HTTP adapter for the host occupancy read."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from backend.admin.deps import require_permission
from backend.admin.host.schemas import HostReadOut
from backend.admin.host.series import read_host
from backend.admin.user_store import UserRecord

router = APIRouter(prefix="/host", tags=["host"])


@router.get("", response_model=HostReadOut)
def get_host(
    span: Annotated[Literal["hour", "day", "retained"], Query()] = "day",
    _user: UserRecord = Depends(require_permission("host:read")),
) -> HostReadOut:
    return read_host(span)
