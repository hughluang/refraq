"""Write-only capture configuration and daily dispatch-window rules."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_core import PydanticCustomError
from backend.core.secrets import encrypt_secret
from backend.metadata.connectors.specs import get_connector_spec, iter_secret_keys
from backend.metadata.errors import SourceCaptureScopeLocked
from backend.worker.api import current_schedule_timezone


class CaptureCredential(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
        frozen=True,
    )
    username: SecretStr = Field(min_length=1)
    password: SecretStr = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def safe_shape(cls, value):
        if isinstance(value, dict):
            value = {
                k: v.get_secret_value() if isinstance(v, SecretStr) else v
                for k, v in value.items()
            }
        if (
            not isinstance(value, dict)
            or set(value) != {"username", "password"}
            or any(
                not isinstance(value[k], str) or not value[k]
                for k in ("username", "password")
            )
        ):
            raise PydanticCustomError(
                "capture_invalid",
                "Capture credential requires non-empty username and password",
            )
        return value

    def seal(self) -> str:
        return encrypt_secret(
            json.dumps(
                {
                    "username": self.username.get_secret_value(),
                    "password": self.password.get_secret_value(),
                },
                separators=(",", ":"),
            )
        )


ClockMinute = Annotated[
    str, Field(strict=True, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
]


class SnapshotWindow(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        revalidate_instances="always",
        frozen=True,
    )
    start: ClockMinute
    end: ClockMinute

    @model_validator(mode="after")
    def distinct(self) -> SnapshotWindow:
        if self.start == self.end:
            raise ValueError("Snapshot window endpoints must differ")
        return self


def snapshot_dispatch_allowed(window: SnapshotWindow | None, instant: datetime) -> bool:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Snapshot dispatch requires an aware Instant")
    if window is None:
        return True
    local = instant.astimezone(ZoneInfo(current_schedule_timezone()))
    minute = f"{local.hour:02d}:{local.minute:02d}"
    if window.start < window.end:
        return window.start <= minute < window.end
    return minute >= window.start or minute < window.end


def guard_capture_scope(
    old_engine: str,
    new_engine: str,
    old_access: dict,
    new_access: dict,
) -> None:
    if old_engine != new_engine:
        raise SourceCaptureScopeLocked()
    mutable = {"username", *iter_secret_keys(get_connector_spec(old_engine))}
    if {k: v for k, v in old_access.items() if k not in mutable} != {
        k: v for k, v in new_access.items() if k not in mutable
    }:
        raise SourceCaptureScopeLocked()
