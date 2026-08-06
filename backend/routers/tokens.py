"""User PAT router implementing docs/api-contracts-tokens.md."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, status

from backend.admin.audit import persist_audit_event
from backend.admin.deps import get_actor_token_id, require_permission
from backend.admin.errors import TokenInvalidExpiresAt, TokenNotFound
from backend.repositories.token_store import (
    TokenRecord,
    TokenStore,
    generate_token_secret,
    get_token_store,
)
from backend.repositories.user_store import UserRecord
from backend.schemas.tokens import (
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
    now = datetime.utcnow()
    expires_at = payload.expires_at
    if expires_at.tzinfo is not None:
        expires_at = expires_at.replace(tzinfo=None)
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


@router.post("/tokens/{token_id}/revoke", response_model=TokenResponse)
def revoke_token(
    token_id: str,
    request: Request,
    user: UserRecord = Depends(require_permission("tokens:write")),
    tokens: TokenStore = Depends(get_token_store),
) -> TokenResponse:
    existing = tokens.get_by_id(token_id)
    if existing is None or existing.user_id != user.id:
        raise TokenNotFound()
    record = tokens.revoke(token_id, when=datetime.utcnow())
    assert record is not None
    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=get_actor_token_id(request),
        resource_type="user_pat",
        resource_id=record.id,
        action="token.revoke",
        result="success",
        detail={"name": record.name, "prefix": record.prefix},
    )
    return TokenResponse(token=_to_metadata(record))
