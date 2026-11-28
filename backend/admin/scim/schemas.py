"""Schemas for SCIM provisioning token administration."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.core.time import Instant


class ScimTokenCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class ScimTokenOut(BaseModel):
    id: str
    provider_id: str
    name: str
    prefix: str
    last_used_at: Instant | None = None
    created_at: Instant


class ScimTokenListResponse(BaseModel):
    items: list[ScimTokenOut]


class ScimTokenCreateResponse(BaseModel):
    scim_token: ScimTokenOut
    token: str
