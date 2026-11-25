"""Pydantic schemas for Source APIs."""

from __future__ import annotations

from backend.core.pagination import OffsetPage
from backend.core.time import Instant
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.worker.schemas.schedules import ScheduleOut
from backend.metadata.capture.configuration import CaptureCredential, SnapshotWindow


class SourceOut(BaseModel):
    id: str
    key: str
    locator_key: str | None = None
    name: str
    kind: str
    status: str
    description: str | None = None
    engine: str | None
    access: dict[str, Any] | None = None
    can_write: bool | None = None
    has_access: bool | None = None
    access_updated_at: Instant | None = None
    capture_credential_set: bool | None = None
    capture_credential_updated_at: Instant | None = None
    capture_state: Literal["disabled", "configured"] | None = None
    snapshot_window: SnapshotWindow | None = None
    schedule_timezone: str | None = None


class SourceListResponse(OffsetPage[SourceOut]):
    pass


class SourceResponse(BaseModel):
    source: SourceOut


class PatchSourceResponse(BaseModel):
    source: SourceOut
    schedules: list[ScheduleOut] | None = None


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
    engine: Literal["postgresql", "mssql", "oracle", "mysql"]
    access: dict[str, Any]
    capture_credential: CaptureCredential | None = None
    snapshot_window: SnapshotWindow | None = None


class PatchSourceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    status: Literal["active", "disabled"] | None = None
    engine: Literal["postgresql", "mssql", "oracle", "mysql"] | None = None
    access: dict[str, Any] | None = None
    capture_credential: CaptureCredential | None = None
    snapshot_window: SnapshotWindow | None = None


class TestSourceDraftRequest(BaseModel):
    engine: Literal["postgresql", "mssql", "oracle", "mysql"]
    access: dict[str, Any]


class TestSourceRequest(BaseModel):
    engine: Literal["postgresql", "mssql", "oracle", "mysql"] | None = None
    access: dict[str, Any] | None = None


class SourceTestResponse(BaseModel):
    ok: bool
    code: str | None = None
    message: str | None = None


class CaptureCheckDraftRequest(BaseModel):
    engine: Literal["postgresql", "mssql", "oracle", "mysql"]
    access: dict[str, Any]
    capture_credential: CaptureCredential | None = None


class CaptureCheckRequest(BaseModel):
    engine: Literal["postgresql", "mssql", "oracle", "mysql"] | None = None
    access: dict[str, Any] | None = None
    capture_credential: CaptureCredential | None = None


class CaptureCheckItem(BaseModel):
    key: str
    result: Literal["pass", "fail", "unknown", "not_applicable"]
    expected: str | None = None
    observed: str | None = None
    action: str | None = None
    note: Literal["access_credential"] | None = None


class CaptureCheckTable(BaseModel):
    name: str
    result: Literal["pass", "fail", "unknown"]
    cause: Literal["schema", "permission"] | None = None
    observed: str | None = None
    note: Literal["access_credential"] | None = None


class CaptureCheckTables(BaseModel):
    total: int
    truncated: bool
    limit: int
    items: list[CaptureCheckTable]


class CaptureCheckResponse(BaseModel):
    ok: bool
    code: str | None = None
    message: str | None = None
    advisory: bool | None = None
    credential: Literal["request", "stored", "access"] | None = None
    engine: str | None = None
    items: list[CaptureCheckItem] | None = None
    tables: CaptureCheckTables | None = None
