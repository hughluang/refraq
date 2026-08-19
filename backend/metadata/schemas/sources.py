"""Pydantic schemas for Source APIs."""

from __future__ import annotations

from backend.core.pagination import OffsetPage
from backend.core.time import Instant
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.worker.schemas.schedules import ScheduleOut


class SourceOut(BaseModel):
    id: str
    key: str
    locator_key: str
    name: str
    kind: str
    status: str
    description: str | None
    engine: str | None
    access: dict[str, Any] | None
    has_access: bool
    access_updated_at: Instant | None


class SourceListResponse(OffsetPage[SourceOut]):
    pass


class SourceResponse(BaseModel):
    source: SourceOut


class PatchSourceResponse(BaseModel):
    source: SourceOut
    schedule: ScheduleOut | None = None


class SourceAccessResponse(BaseModel):
    access: dict[str, Any]


class AccessSchemaResponse(BaseModel):
    engine: str
    schema: dict[str, Any]


class CreateSourceRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    kind: Literal["database"] = "database"
    description: str | None = None
    engine: Literal["postgresql", "mssql", "oracle"]
    access: dict[str, Any]


class PatchSourceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    status: Literal["active", "disabled"] | None = None
    engine: Literal["postgresql", "mssql", "oracle"] | None = None
    access: dict[str, Any] | None = None


class TestSourceDraftRequest(BaseModel):
    engine: Literal["postgresql", "mssql", "oracle"]
    access: dict[str, Any]


class TestSourceRequest(BaseModel):
    engine: Literal["postgresql", "mssql", "oracle"] | None = None
    access: dict[str, Any] | None = None


class SourceTestResponse(BaseModel):
    ok: bool
    code: str | None = None
    message: str | None = None
