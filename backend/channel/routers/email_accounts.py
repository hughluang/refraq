"""Email Account HTTP adapters."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.user_store import UserRecord
from backend.channel.email_accounts import (
    create_email_account,
    delete_email_account,
    get_email_account,
    list_email_accounts,
    present,
    test_email_account,
    update_email_account,
)
from backend.core.pagination import PageBounds, PageParams, page_params
from backend.core.time import Instant

router = APIRouter(tags=["email-accounts"])

EMAIL_ACCOUNT_PAGE = PageBounds(default_limit=50, max_limit=200)


class EmailAccountOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    host: str
    port: int
    encryption: str
    username: str | None
    password_set: bool
    from_address: str = Field(alias="from")
    tls_skip_verify: bool
    last_delivery_at: Instant | None
    last_delivery_ok: bool | None
    last_delivery_error: str | None
    created_at: Instant
    updated_at: Instant


class EmailAccountResponse(BaseModel):
    email_account: EmailAccountOut


class EmailAccountListResponse(BaseModel):
    items: list[EmailAccountOut]
    total: int
    limit: int
    offset: int


class EmailAccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=200)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    encryption: Literal["none", "starttls", "implicit_tls"]
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, min_length=1, max_length=512)
    from_address: str = Field(alias="from", min_length=1, max_length=254)
    tls_skip_verify: bool = False


class EmailAccountPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    encryption: Literal["none", "starttls", "implicit_tls"] | None = None
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, min_length=1, max_length=512)
    from_address: str | None = Field(default=None, alias="from", max_length=254)
    tls_skip_verify: bool | None = None


class EmailAccountTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str = Field(min_length=1, max_length=254)


class EmailAccountTestResponse(BaseModel):
    email_account: EmailAccountOut
    ok: bool
    error: str | None


@router.get("/email-accounts", response_model=EmailAccountListResponse)
def http_list_email_accounts(
    _actor: UserRecord = Depends(require_permission("email_account:read")),
    q: str | None = None,
    page: PageParams = Depends(page_params(EMAIL_ACCOUNT_PAGE)),
) -> dict[str, Any]:
    records, total = list_email_accounts(q=q, limit=page.limit, offset=page.offset)
    return {
        "items": [present(record) for record in records],
        "total": total,
        "limit": page.limit,
        "offset": page.offset,
    }


@router.post("/email-accounts", status_code=201, response_model=EmailAccountResponse)
def http_create_email_account(
    body: EmailAccountCreateRequest,
    actor: UserRecord = Depends(require_permission("email_account:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict[str, Any]:
    record = create_email_account(
        name=body.name,
        host=body.host,
        port=body.port,
        encryption=body.encryption,
        username=body.username,
        password=body.password,
        from_address=body.from_address,
        tls_skip_verify=body.tls_skip_verify,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return {"email_account": present(record)}


@router.get("/email-accounts/{account_id}", response_model=EmailAccountResponse)
def http_get_email_account(
    account_id: str,
    _actor: UserRecord = Depends(require_permission("email_account:read")),
) -> dict[str, Any]:
    return {"email_account": present(get_email_account(account_id))}


@router.patch("/email-accounts/{account_id}", response_model=EmailAccountResponse)
def http_patch_email_account(
    account_id: str,
    body: EmailAccountPatchRequest,
    actor: UserRecord = Depends(require_permission("email_account:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict[str, Any]:
    record = update_email_account(
        account_id=account_id,
        name=body.name,
        host=body.host,
        port=body.port,
        encryption=body.encryption,
        username=body.username,
        username_set="username" in body.model_fields_set,
        password=body.password,
        password_set="password" in body.model_fields_set,
        from_address=body.from_address,
        tls_skip_verify=body.tls_skip_verify,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return {"email_account": present(record)}


@router.delete("/email-accounts/{account_id}", status_code=204)
def http_delete_email_account(
    account_id: str,
    actor: UserRecord = Depends(require_permission("email_account:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> Response:
    delete_email_account(
        account_id=account_id,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/email-accounts/{account_id}/test", response_model=EmailAccountTestResponse)
def http_test_email_account(
    account_id: str,
    body: EmailAccountTestRequest,
    actor: UserRecord = Depends(require_permission("email_account:write")),
    actor_token_id: str | None = Depends(get_actor_token_id),
) -> dict[str, Any]:
    record, result = test_email_account(
        account_id=account_id,
        to=body.to,
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
    )
    return {
        "email_account": present(record),
        "ok": result.ok,
        "error": result.error,
    }
