"""Auth request and response schemas for refraq backend."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IdentitySource = Literal["local"]


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


class ErrorResponse(BaseModel):
    code: str
    message: str


class LogoutResponse(BaseModel):
    success: bool = True
