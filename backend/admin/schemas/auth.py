"""Auth request and response schemas for refraq backend."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.admin.schemas.user import IdentitySource


class LoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class CurrentUser(BaseModel):
    id: str
    account: str
    display_name: str
    email: str | None = None
    locale: str = "en-US"
    display_timezone: str | None = None
    role_id: str | None
    role_key: str | None
    role_name: str | None
    permissions: list[str]
    identity_source: IdentitySource = "local"


class LoginResponse(BaseModel):
    user: CurrentUser


class LogoutResponse(BaseModel):
    success: bool = True
