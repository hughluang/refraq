"""Platform settings request/response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.admin.settings_override import TTL_HOURS_MAX, TTL_HOURS_MIN

SettingsSource = Literal["env", "override"]


class PlatformSettingsResponse(BaseModel):
    refraq_env: str
    admin_session_ttl_hours: int
    admin_session_ttl_hours_source: SettingsSource
    admin_session_ttl_hours_default: int


class PlatformSettingsPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admin_session_ttl_hours: int = Field(ge=TTL_HOURS_MIN, le=TTL_HOURS_MAX)
