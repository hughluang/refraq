"""User PAT API schemas."""

from __future__ import annotations


from backend.core.time import Instant
from pydantic import BaseModel, Field


class TokenMetadata(BaseModel):
    id: str
    name: str
    prefix: str
    expires_at: Instant
    revoked_at: Instant | None
    created_at: Instant
    last_used_at: Instant | None


class TokenListResponse(BaseModel):
    items: list[TokenMetadata]


class CreateTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    expires_at: Instant


class CreateTokenResponse(BaseModel):
    token: TokenMetadata
    secret: str


class TokenResponse(BaseModel):
    token: TokenMetadata
