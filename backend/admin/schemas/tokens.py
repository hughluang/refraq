"""User PAT API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TokenMetadata(BaseModel):
    id: str
    name: str
    prefix: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None


class TokenListResponse(BaseModel):
    items: list[TokenMetadata]


class CreateTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    expires_at: datetime


class CreateTokenResponse(BaseModel):
    token: TokenMetadata
    secret: str


class TokenResponse(BaseModel):
    token: TokenMetadata
