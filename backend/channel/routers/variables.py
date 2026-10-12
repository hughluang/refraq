"""Global Variable list and manual delete."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.channel.errors import ChannelVariableNameInvalid, ChannelVariableNotFound
from backend.channel.variables import get_variable_store, valid_name
from backend.core.pagination import OffsetPage, PageParams, page_params
from backend.core.time import Instant

router = APIRouter(tags=["channels"])


class ChannelVariableOut(BaseModel):
    name: str
    value: Any
    expires_at: Instant | None
    updated_at: Instant


class ChannelVariableListResponse(OffsetPage[ChannelVariableOut]):
    pass


@router.get("/channel-variables", response_model=ChannelVariableListResponse)
def list_variables(
    _actor: UserRecord = Depends(require_permission("channel:read")),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> ChannelVariableListResponse:
    rows, total = get_variable_store().list_live(limit=page.limit, offset=page.offset)
    return ChannelVariableListResponse(
        items=[
            ChannelVariableOut(
                name=row.name,
                value=row.value,
                expires_at=row.expires_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.delete("/channel-variables/{name}", status_code=204)
def delete_variable(
    name: str,
    actor: UserRecord = Depends(require_permission("channel:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    if not valid_name(name):
        raise ChannelVariableNameInvalid()
    if not get_variable_store().delete(name):
        raise ChannelVariableNotFound()
    persist_audit_event(
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
        resource_type="channel_variable",
        resource_id=name,
        action="channel.variable_delete",
        result="success",
        detail={"name": name},
    )
    return Response(status_code=204)
