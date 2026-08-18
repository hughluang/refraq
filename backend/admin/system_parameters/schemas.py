"""HTTP shapes for the System Parameter catalog."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.core.time import Instant

ParameterSource = Literal["seed", "user"]
ParameterJsonValue = int | float | str | bool | None


class SystemParameterOut(BaseModel):
    key: str
    value: ParameterJsonValue
    seed: ParameterJsonValue
    source: ParameterSource
    constraint: dict[str, object]
    group: str
    operator_action_required: bool
    label_key: str
    help_key: str
    apply_note_key: str
    updated_at: Instant | None
    updated_by_user_id: str | None
    updated_by_account: str | None


class PlatformSettingsResponse(BaseModel):
    parameters: list[SystemParameterOut]


class PlatformSettingsPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, int | float | str | bool] = Field(min_length=1)


class PlatformSettingsResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keys: list[str] | None = None
