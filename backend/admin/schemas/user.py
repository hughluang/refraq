"""User management schemas for the Management Foundation."""

from __future__ import annotations

from backend.core.pagination import OffsetPage
from backend.core.time import Instant
from typing import Literal

from pydantic import BaseModel, Field

UserStatus = Literal["active", "disabled"]
IdentitySource = Literal["local"]


class UserSummary(BaseModel):
    id: str
    account: str
    display_name: str
    email: str | None = None
    locale: str = "en-US"
    display_timezone: str | None = None
    role_id: str | None
    role_key: str | None
    role_name: str | None
    status: UserStatus
    identity_source: IdentitySource
    last_login_at: Instant | None = None


class UserListResponse(OffsetPage[UserSummary]):
    pass


class CreateUserRequest(BaseModel):
    account: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    role_id: str | None = None
    email: str | None = Field(default=None, max_length=256)
    locale: str | None = Field(default=None, max_length=16)


class CreateUserResponse(BaseModel):
    user: UserSummary


class UpdateStatusRequest(BaseModel):
    # Validated against active|disabled in the router for USER_INVALID_STATUS.
    status: str


class UpdateStatusResponse(BaseModel):
    user: UserSummary
