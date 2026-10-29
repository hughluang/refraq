"""HTTP Account HTTP adapters."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.channel.http_accounts import (
    create_http_account,
    delete_http_account,
    get_http_account,
    list_http_accounts,
    present,
    update_http_account,
)
from backend.core.pagination import PageBounds, PageParams, page_params
from backend.core.time import Instant

router = APIRouter(tags=["http-accounts"])

HTTP_ACCOUNT_PAGE = PageBounds(default_limit=50, max_limit=200)


class HttpAccountAuthOut(BaseModel):
    type: str
    username: str | None = None


class HttpAccountNameOut(BaseModel):
    name: str


class HttpAccountOut(BaseModel):
    id: str
    name: str
    auth: HttpAccountAuthOut
    headers: list[HttpAccountNameOut]
    query: list[HttpAccountNameOut]
    allowed_origins: list[str]
    created_at: Instant
    updated_at: Instant


class HttpAccountResponse(BaseModel):
    http_account: HttpAccountOut


class HttpAccountListResponse(BaseModel):
    items: list[HttpAccountOut]
    total: int
    limit: int
    offset: int


class HttpAccountAuthIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "bearer", "basic"]
    token: str | None = Field(default=None, min_length=1, max_length=4096)
    username: str | None = Field(default=None, min_length=1, max_length=256)
    password: str | None = Field(default=None, min_length=1, max_length=1024)


class HttpAccountHeaderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=4096)


class HttpAccountQueryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=2048)
    value: str = Field(min_length=1, max_length=2048)


class HttpAccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    auth: HttpAccountAuthIn | None = None
    headers: list[HttpAccountHeaderIn] | None = Field(default=None, max_length=32)
    query: list[HttpAccountQueryIn] | None = Field(default=None, max_length=32)
    allowed_origins: list[str] | None = Field(default=None, max_length=32)


class HttpAccountPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    auth: HttpAccountAuthIn | None = None
    headers: list[HttpAccountHeaderIn] | None = Field(default=None, max_length=32)
    query: list[HttpAccountQueryIn] | None = Field(default=None, max_length=32)
    allowed_origins: list[str] | None = Field(default=None, max_length=32)


def _auth_payload(auth: HttpAccountAuthIn | None) -> dict[str, Any] | None:
    if auth is None:
        return None
    return auth.model_dump(exclude_unset=True)


def _pairs(items: list[HttpAccountHeaderIn] | list[HttpAccountQueryIn] | None) -> list[dict[str, Any]] | None:
    if items is None:
        return None
    return [item.model_dump() for item in items]


@router.get(
    "/http-accounts",
    response_model=HttpAccountListResponse,
    response_model_exclude_none=True,
)
def http_list_http_accounts(
    _actor: UserRecord = Depends(require_permission("http_account:read")),
    q: str | None = None,
    page: PageParams = Depends(page_params(HTTP_ACCOUNT_PAGE)),
) -> dict[str, Any]:
    records, total = list_http_accounts(q=q, limit=page.limit, offset=page.offset)
    return {
        "items": [present(record) for record in records],
        "total": total,
        "limit": page.limit,
        "offset": page.offset,
    }


@router.post(
    "/http-accounts",
    status_code=201,
    response_model=HttpAccountResponse,
    response_model_exclude_none=True,
)
def http_create_http_account(
    body: HttpAccountCreateRequest,
    actor: UserRecord = Depends(require_permission("http_account:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict[str, Any]:
    record = create_http_account(
        name=body.name,
        auth=_auth_payload(body.auth),
        headers=_pairs(body.headers),
        query=_pairs(body.query),
        allowed_origins=body.allowed_origins,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return {"http_account": present(record)}


@router.get(
    "/http-accounts/{account_id}",
    response_model=HttpAccountResponse,
    response_model_exclude_none=True,
)
def http_get_http_account(
    account_id: str,
    _actor: UserRecord = Depends(require_permission("http_account:read")),
) -> dict[str, Any]:
    return {"http_account": present(get_http_account(account_id))}


@router.patch(
    "/http-accounts/{account_id}",
    response_model=HttpAccountResponse,
    response_model_exclude_none=True,
)
def http_patch_http_account(
    account_id: str,
    body: HttpAccountPatchRequest,
    actor: UserRecord = Depends(require_permission("http_account:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict[str, Any]:
    record = update_http_account(
        account_id=account_id,
        name=body.name,
        auth=_auth_payload(body.auth),
        auth_set="auth" in body.model_fields_set,
        headers=_pairs(body.headers),
        headers_set="headers" in body.model_fields_set,
        query=_pairs(body.query),
        query_set="query" in body.model_fields_set,
        allowed_origins=body.allowed_origins,
        origins_set="allowed_origins" in body.model_fields_set,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return {"http_account": present(record)}


@router.delete("/http-accounts/{account_id}", status_code=204)
def http_delete_http_account(
    account_id: str,
    actor: UserRecord = Depends(require_permission("http_account:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    delete_http_account(
        account_id=account_id,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
