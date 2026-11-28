"""HTTP schemas for OAuth Client administration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.core.pagination import OffsetPage
from backend.core.time import Instant

AuthMethod = Literal["private_key_jwt", "client_secret_basic", "client_secret_post"]


class OAuthClientCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    provider_id: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    token_endpoint_auth_method: AuthMethod = "private_key_jwt"
    jwks: dict[str, Any] | None = None
    jwks_uri: str | None = Field(default=None, max_length=512)
    allowed_grant_types: list[str] = Field(
        default_factory=lambda: ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    )
    allowed_subject_audiences: list[str] = Field(default_factory=list)
    allowed_surfaces: list[str] = Field(default_factory=lambda: ["entity_mcp"])
    allowed_scopes: list[str] = Field(default_factory=lambda: ["entity:data_read"])
    token_ttl_sec: int | None = Field(default=None, ge=60, le=3600)


class OAuthClientPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool | None = None
    token_endpoint_auth_method: AuthMethod | None = None
    jwks: dict[str, Any] | None = None
    jwks_uri: str | None = Field(default=None, max_length=512)
    allowed_grant_types: list[str] | None = None
    allowed_subject_audiences: list[str] | None = None
    allowed_surfaces: list[str] | None = None
    allowed_scopes: list[str] | None = None
    token_ttl_sec: int | None = Field(default=None, ge=60, le=3600)


class OAuthClientOut(BaseModel):
    id: str
    client_id: str
    name: str
    description: str | None
    provider_id: str
    enabled: bool
    token_endpoint_auth_method: AuthMethod
    jwks: dict[str, Any] | None
    jwks_uri: str | None
    secret_prefix: str | None
    client_secret_configured: bool
    allowed_grant_types: list[str]
    allowed_subject_audiences: list[str]
    allowed_surfaces: list[str]
    allowed_scopes: list[str]
    token_ttl_sec: int | None
    created_at: Instant
    updated_at: Instant
    last_used_at: Instant | None = None


class OAuthClientResponse(BaseModel):
    oauth_client: OAuthClientOut


class OAuthClientSecretResponse(BaseModel):
    oauth_client: OAuthClientOut
    client_secret: str | None = None


class OAuthClientList(OffsetPage[OAuthClientOut]):
    pass
