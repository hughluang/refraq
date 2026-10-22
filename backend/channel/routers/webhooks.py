"""Webhook HTTP adapters."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.channel.webhooks import (
    create_webhook,
    delete_webhook,
    get_webhook,
    list_webhooks,
    present,
    test_webhook,
    update_webhook,
)
from backend.core.pagination import PageBounds, PageParams, page_params
from backend.core.time import Instant

router = APIRouter(tags=["webhooks"])

WEBHOOK_PAGE = PageBounds(default_limit=50, max_limit=200)


class WebhookOut(BaseModel):
    id: str
    name: str
    url: str
    secret_set: bool
    last_delivery_at: Instant | None
    last_delivery_ok: bool | None
    last_delivery_error: str | None
    created_at: Instant
    updated_at: Instant


class WebhookResponse(BaseModel):
    webhook: WebhookOut


class WebhookListResponse(BaseModel):
    items: list[WebhookOut]
    total: int
    limit: int
    offset: int


class WebhookCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2048)
    secret: str | None = Field(default=None, min_length=1, max_length=512)


class WebhookPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    secret: str | None = Field(default=None, min_length=1, max_length=512)


class WebhookTestResponse(BaseModel):
    webhook: WebhookOut
    status_code: int | None
    ok: bool
    error: str | None


@router.get("/webhooks", response_model=WebhookListResponse)
def http_list_webhooks(
    _actor: UserRecord = Depends(require_permission("webhook:read")),
    q: str | None = None,
    page: PageParams = Depends(page_params(WEBHOOK_PAGE)),
) -> dict[str, Any]:
    records, total = list_webhooks(q=q, limit=page.limit, offset=page.offset)
    return {
        "items": [present(record) for record in records],
        "total": total,
        "limit": page.limit,
        "offset": page.offset,
    }


@router.post("/webhooks", status_code=201, response_model=WebhookResponse)
def http_create_webhook(
    body: WebhookCreateRequest,
    actor: UserRecord = Depends(require_permission("webhook:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict[str, Any]:
    record = create_webhook(
        name=body.name,
        url=body.url,
        secret=body.secret,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return {"webhook": present(record)}


@router.get("/webhooks/{webhook_id}", response_model=WebhookResponse)
def http_get_webhook(
    webhook_id: str,
    _actor: UserRecord = Depends(require_permission("webhook:read")),
) -> dict[str, Any]:
    return {"webhook": present(get_webhook(webhook_id))}


@router.patch("/webhooks/{webhook_id}", response_model=WebhookResponse)
def http_patch_webhook(
    webhook_id: str,
    body: WebhookPatchRequest,
    actor: UserRecord = Depends(require_permission("webhook:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict[str, Any]:
    record = update_webhook(
        webhook_id=webhook_id,
        name=body.name,
        url=body.url,
        secret=body.secret,
        secret_set="secret" in body.model_fields_set,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return {"webhook": present(record)}


@router.delete("/webhooks/{webhook_id}", status_code=204)
def http_delete_webhook(
    webhook_id: str,
    actor: UserRecord = Depends(require_permission("webhook:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    delete_webhook(
        webhook_id=webhook_id,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/webhooks/{webhook_id}/test", response_model=WebhookTestResponse)
def http_test_webhook(
    webhook_id: str,
    actor: UserRecord = Depends(require_permission("webhook:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict[str, Any]:
    record, result = test_webhook(
        webhook_id=webhook_id,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return {
        "webhook": present(record),
        "status_code": result.status_code,
        "ok": result.ok,
        "error": result.error,
    }
