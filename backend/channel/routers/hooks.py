"""Public inbound hook and the channel rejection list."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from starlette.requests import Request
from starlette.responses import Response

from backend.admin.deps import require_permission
from backend.admin.user_store import UserRecord
from backend.channel.errors import ChannelNotFound
from backend.channel.inbound_dedup import get_inbound_dedup_store
from backend.channel.inbound_http import receive_inbound
from backend.channel.inbound_rejections import get_inbound_rejection_store
from backend.channel.store import get_channel_store
from backend.core.pagination import PageParams, page_params
from backend.core.time import Instant

router = APIRouter(tags=["inbound-hooks"])

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class InboundRejectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    channel_id: str
    node_id: str
    path: str
    received_at: Instant
    reason: str
    method: str
    headers: dict[str, str]
    query: dict[str, str]
    body: str | None


class InboundRejectionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[InboundRejectionOut]
    total: int
    limit: int
    offset: int
    hit_count: int


@router.api_route("/hooks/{hook_path}", methods=_METHODS)
async def http_receive_inbound(hook_path: str, request: Request) -> Response:
    return await receive_inbound(request, hook_path)


@router.get(
    "/channels/{channel_id}/inbound-rejections",
    response_model=InboundRejectionListResponse,
)
def http_list_inbound_rejections(
    channel_id: str,
    _actor: UserRecord = Depends(require_permission("channel:read")),
    page: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
) -> dict[str, Any]:
    if get_channel_store().get(channel_id) is None:
        raise ChannelNotFound()
    records, total = get_inbound_rejection_store().list_for_channel(
        channel_id, limit=page.limit, offset=page.offset
    )
    return {
        "items": [
            {
                "id": item.id,
                "channel_id": item.channel_id,
                "node_id": item.node_id,
                "path": item.path,
                "received_at": item.received_at,
                "reason": item.reason,
                "method": item.method,
                "headers": item.headers,
                "query": item.query,
                "body": item.body,
            }
            for item in records
        ],
        "total": total,
        "limit": page.limit,
        "offset": page.offset,
        "hit_count": get_inbound_dedup_store().hit_count(channel_id),
    }
