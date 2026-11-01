"""Inbound Credential HTTP adapters."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.channel.inbound_credentials import (
    create_inbound_credential,
    delete_inbound_credential,
    get_inbound_credential,
    list_inbound_credentials,
    present,
    update_inbound_credential,
)
from backend.core.pagination import PageBounds, PageParams, page_params
from backend.core.time import Instant

router = APIRouter(tags=["inbound-credentials"])

INBOUND_CREDENTIAL_PAGE = PageBounds(default_limit=50, max_limit=200)


class InboundCredentialOut(BaseModel):
    id: str
    name: str
    type: str
    config: dict[str, Any]
    created_at: Instant
    updated_at: Instant


class InboundCredentialResponse(BaseModel):
    inbound_credential: InboundCredentialOut


class InboundCredentialListResponse(BaseModel):
    items: list[InboundCredentialOut]
    total: int
    limit: int
    offset: int


class InboundCredentialCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    type: str
    secret: str = Field(min_length=1, max_length=4096)
    config: dict[str, Any]


class InboundCredentialPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: Literal["token", "hmac_sha256"] | None = None
    secret: str | None = Field(default=None, min_length=1, max_length=4096)
    config: dict[str, Any] | None = None


@router.get(
    "/inbound-credentials",
    response_model=InboundCredentialListResponse,
    response_model_exclude_none=True,
)
def http_list_inbound_credentials(
    _actor: UserRecord = Depends(require_permission("inbound_credential:read")),
    q: str | None = None,
    page: PageParams = Depends(page_params(INBOUND_CREDENTIAL_PAGE)),
) -> dict[str, Any]:
    records, total = list_inbound_credentials(q=q, limit=page.limit, offset=page.offset)
    return {
        "items": [present(record) for record in records],
        "total": total,
        "limit": page.limit,
        "offset": page.offset,
    }


@router.post(
    "/inbound-credentials",
    status_code=201,
    response_model=InboundCredentialResponse,
    response_model_exclude_none=True,
)
def http_create_inbound_credential(
    body: InboundCredentialCreateRequest,
    actor: UserRecord = Depends(require_permission("inbound_credential:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict[str, Any]:
    record = create_inbound_credential(
        name=body.name,
        credential_type=body.type,
        secret=body.secret,
        config=body.config,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return {"inbound_credential": present(record)}


@router.patch(
    "/inbound-credentials/{credential_id}",
    response_model=InboundCredentialResponse,
    response_model_exclude_none=True,
)
def http_patch_inbound_credential(
    credential_id: str,
    body: InboundCredentialPatchRequest,
    actor: UserRecord = Depends(require_permission("inbound_credential:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict[str, Any]:
    fields = body.model_fields_set
    record = update_inbound_credential(
        credential_id=credential_id,
        name=body.name,
        credential_type=body.type,
        type_set="type" in fields,
        secret=body.secret,
        secret_set="secret" in fields,
        config=body.config,
        config_set="config" in fields,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return {"inbound_credential": present(record)}


@router.get(
    "/inbound-credentials/{credential_id}",
    response_model=InboundCredentialResponse,
    response_model_exclude_none=True,
)
def http_get_inbound_credential(
    credential_id: str,
    _actor: UserRecord = Depends(require_permission("inbound_credential:read")),
) -> dict[str, Any]:
    return {"inbound_credential": present(get_inbound_credential(credential_id))}


@router.delete("/inbound-credentials/{credential_id}", status_code=204)
def http_delete_inbound_credential(
    credential_id: str,
    actor: UserRecord = Depends(require_permission("inbound_credential:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    delete_inbound_credential(
        credential_id=credential_id,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
