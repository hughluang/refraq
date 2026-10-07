"""HTTP shapes for Entity access management."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.core.time import Instant
from backend.entity.data.capabilities import OFFSET_MAX, PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX


class SubjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["user", "role", "group"]
    id: str = Field(min_length=1, max_length=64)


class NarrowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["user", "role", "group"]
    id: str | None = None


class LevelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    mode: Any


class LadderPut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    levels: list[LevelIn]


class ColumnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_id: str
    level: str


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None
    columns: list[ColumnIn]


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    columns: list[ColumnIn] | None = None


class ProfileCopy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_entity_id: str
    source_profile_id: str
    key: str
    name: str = Field(min_length=1, max_length=256)


class AppliesToIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "only", "except"]
    subjects: list[SubjectIn] = Field(default_factory=list)


class CeilingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_id: str
    level: str


class GrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: SubjectIn
    profile_id: str
    row_rule: dict[str, Any] | None = None
    actions: list[str]
    status: Literal["active", "disabled"] = "active"
    valid_until: Instant | None = None


class GrantPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str | None = None
    row_rule: dict[str, Any] | None = None
    actions: list[str] | None = None
    status: Literal["active", "disabled"] | None = None
    valid_until: Instant | None = None


class RestrictionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applies_to: AppliesToIn
    row_rule: dict[str, Any] | None = None
    deny_columns: list[str] = Field(default_factory=list)
    ceilings: list[CeilingIn] = Field(default_factory=list)
    actions: list[str] | None = None


class RestrictionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applies_to: AppliesToIn | None = None
    row_rule: dict[str, Any] | None = None
    deny_columns: list[str] | None = None
    ceilings: list[CeilingIn] | None = None
    actions: list[str] | None = None


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: SubjectIn
    narrow: NarrowIn | None = None
    include_rows: bool = False
    filters: dict[str, Any] | None = None
    limit: int = Field(default=PAGE_LIMIT_DEFAULT, ge=1, le=PAGE_LIMIT_MAX)
    offset: int = Field(default=0, ge=0, le=OFFSET_MAX)
