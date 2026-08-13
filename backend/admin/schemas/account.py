"""Account Center self-service schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.admin.schemas.auth import CurrentUser


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    email: str | None = Field(default=None, max_length=256)
    locale: str | None = Field(default=None, max_length=16)
    display_timezone: str | None = Field(default=None, max_length=64)


class UpdateProfileResponse(BaseModel):
    user: CurrentUser


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class ChangePasswordResponse(BaseModel):
    success: bool = True
