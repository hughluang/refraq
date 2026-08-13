"""User PAT router implementing docs/api-contracts-tokens.md."""

from __future__ import annotations

from backend.core.time import utc_now

from fastapi import APIRouter, Depends, Request, Response, status

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.errors import (
    TokenInvalidExpiresAt,
    TokenNotDeactivated,
    TokenNotFound,
)
from backend.admin.token_store import (
    TokenRecord,
    TokenStore,
    generate_token_secret,
    get_token_store,
)
from backend.admin.user_store import UserRecord
from backend.admin.schemas.tokens import (
    CreateTokenRequest,
    CreateTokenResponse,
    TokenListResponse,
    TokenMetadata,
    TokenResponse,
)

router = APIRouter(tags=["tokens"])


def _to_metadata(record: TokenRecord) -> TokenMetadata:
    return TokenMetadata(
        id=record.id,
        name=record.name,
        prefix=record.prefix,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
    )


def _owned_visible(record: TokenRecord | None, user_id: str) -> TokenRecord:
    if record is None or record.user_id != user_id or record.deleted_at is not None:
        raise TokenNotFound()
    return record


@router.get("/tokens", response_model=TokenListResponse)
def list_tokens(
    user: UserRecord = Depends(require_permission("tokens:read")),
    tokens: TokenStore = Depends(get_token_store),
) -> TokenListResponse:
    items = [_to_metadata(record) for record in tokens.list_for_user(user.id)]
    return TokenListResponse(items=items)


@router.post(
    "/tokens",
    response_model=CreateTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_token(
    payload: CreateTokenRequest,
    request: Request,
    user: UserRecord = Depends(require_permission("tokens:write")),
    tokens: TokenStore = Depends(get_token_store),
) -> CreateTokenResponse:
    now = utc_now()
    expires_at = payload.expires_at
    if expires_at <= now:
        raise TokenInvalidExpiresAt()
    secret, prefix, token_hash = generate_token_secret()
    record = tokens.create(
        user_id=user.id,
        name=payload.name,
        token_hash=token_hash,
        prefix=prefix,
        expires_at=expires_at,
    )
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="user_pat",
        resource_id=record.id,
        action="token.create",
        result="success",
        detail={"name": record.name, "prefix": record.prefix},
    )
    return CreateTokenResponse(token=_to_metadata(record), secret=secret)


@router.post("/tokens/{token_id}/deactivate", response_model=TokenResponse)
def deactivate_token(
    token_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("tokens:write")),
    tokens: TokenStore = Depends(get_token_store),
) -> TokenResponse:
    _owned_visible(tokens.get_by_id(token_id), user.id)
    record = tokens.deactivate(token_id, when=utc_now())
    assert record is not None
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="user_pat",
        resource_id=record.id,
        action="token.deactivate",
        result="success",
        detail={"name": record.name, "prefix": record.prefix},
    )
    return TokenResponse(token=_to_metadata(record))


@router.post("/tokens/{token_id}/restore", response_model=TokenResponse)
def restore_token(
    token_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("tokens:write")),
    tokens: TokenStore = Depends(get_token_store),
) -> TokenResponse:
    _owned_visible(tokens.get_by_id(token_id), user.id)
    record = tokens.restore(token_id)
    assert record is not None
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="user_pat",
        resource_id=record.id,
        action="token.restore",
        result="success",
        detail={"name": record.name, "prefix": record.prefix},
    )
    return TokenResponse(token=_to_metadata(record))


@router.delete(
    "/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_token(
    token_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("tokens:write")),
    tokens: TokenStore = Depends(get_token_store),
) -> Response:
    existing = _owned_visible(tokens.get_by_id(token_id), user.id)
    if existing.revoked_at is None:
        raise TokenNotDeactivated()
    record = tokens.soft_delete(token_id, when=utc_now())
    assert record is not None
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="user_pat",
        resource_id=record.id,
        action="token.delete",
        result="success",
        detail={"name": record.name, "prefix": record.prefix},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
