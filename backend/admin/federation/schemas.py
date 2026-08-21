"""Federation HTTP schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.admin.schemas.user import UserSummary
from backend.core.pagination import OffsetPage
from backend.core.time import Instant

ProtocolName = Literal["oidc"]


class ProviderCreateIn(BaseModel):
    protocol: ProtocolName = "oidc"
    display_name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    issuer: str = Field(min_length=1, max_length=512)
    client_id: str = Field(min_length=1, max_length=256)
    client_secret: str = Field(min_length=1, max_length=4096)
    scopes: list[str] | None = None
    auto_provision: bool = False
    group_claim: str | None = None
    group_allowlist: list[str] | None = None
    default_role_id: str | None = None

    def config_payload(self) -> dict[str, object]:
        data: dict[str, object] = {
            "issuer": self.issuer,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "auto_provision": self.auto_provision,
        }
        if self.scopes is not None:
            data["scopes"] = self.scopes
        if self.group_claim is not None:
            data["group_claim"] = self.group_claim
        if self.group_allowlist is not None:
            data["group_allowlist"] = self.group_allowlist
        if self.default_role_id is not None:
            data["default_role_id"] = self.default_role_id
        return data


class ProviderPatchIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    issuer: str | None = Field(default=None, min_length=1, max_length=512)
    client_id: str | None = Field(default=None, min_length=1, max_length=256)
    client_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    scopes: list[str] | None = None
    auto_provision: bool | None = None
    group_claim: str | None = None
    group_allowlist: list[str] | None = None
    default_role_id: str | None = None

    def config_payload(self) -> dict[str, object]:
        data: dict[str, object] = {}
        mapping = {
            "issuer": self.issuer,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scopes": self.scopes,
            "auto_provision": self.auto_provision,
            "group_claim": self.group_claim,
            "group_allowlist": self.group_allowlist,
            "default_role_id": self.default_role_id,
        }
        for key, value in mapping.items():
            if value is not None:
                data[key] = value
        return data


class ProviderOut(BaseModel):
    id: str
    protocol: ProtocolName
    display_name: str
    issuer: str
    enabled: bool
    auto_provision: bool
    group_claim: str
    group_allowlist: list[str]
    default_role_id: str | None
    scopes: list[str]
    client_id: str
    client_secret_configured: bool
    bound_user_count: int = 0
    created_at: Instant | None = None
    updated_at: Instant | None = None


class ProviderResponse(BaseModel):
    provider: ProviderOut


class ProviderList(OffsetPage[ProviderOut]):
    pass


class ProviderSpecResponse(BaseModel):
    protocol: ProtocolName
    spec: dict[str, Any]


class ProviderTestResponse(BaseModel):
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    authorization_response_iss_parameter_supported: bool
    group_claim: str


class ProviderDeleteResponse(BaseModel):
    bound_user_count: int


class PublicProviderOut(BaseModel):
    id: str
    display_name: str
    protocol: ProtocolName = "oidc"


class PublicProviderList(BaseModel):
    items: list[PublicProviderOut]


class PendingOut(BaseModel):
    id: str
    issuer: str
    subject: str
    provider_id: str | None
    account_hint: str
    email: str | None
    display_name: str | None
    groups: list[str]
    admission_reason: str
    attempt_count: int
    first_seen_at: Instant
    last_attempt_at: Instant
    expires_at: Instant


class PendingList(OffsetPage[PendingOut]):
    pass


class CreateFederatedUserIn(BaseModel):
    account: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=256)
    role_id: str


class ClaimPendingIn(BaseModel):
    user_id: str | None = None
    create_user: CreateFederatedUserIn | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "ClaimPendingIn":
        if (self.user_id is None) == (self.create_user is None):
            raise ValueError("Exactly one of user_id or create_user is required")
        return self


class ClaimPendingResponse(BaseModel):
    user: UserSummary


class UnfederateIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class UnfederateResponse(BaseModel):
    user: UserSummary
