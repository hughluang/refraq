"""Job API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    input: dict[str, Any]
    created_by_user_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


class JobListResponse(BaseModel):
    items: list[JobOut]


class JobResponse(BaseModel):
    job: JobOut


class EnqueueStructureJobRequest(BaseModel):
    kind: Literal["structure"] = "structure"
    connection_id: str | None = None


class CatalogColumnOut(BaseModel):
    id: str
    name: str
    data_type: str
    nullable: bool
    business_name: str | None = None
    business_description: str | None = None
    ordinal: int = 0
    is_present: bool = True


class CatalogObjectOut(BaseModel):
    id: str
    source_id: str
    collected_from_connection_id: str | None
    object_type: str
    schema_name: str
    name: str
    business_name: str | None
    business_description: str | None
    columns: list[CatalogColumnOut] = Field(default_factory=list)
    ddl: str | None = None
    is_present: bool = True
    collected_at: datetime | None = None


class CatalogObjectListResponse(BaseModel):
    items: list[CatalogObjectOut]


class CatalogObjectResponse(BaseModel):
    object: CatalogObjectOut


class CatalogDdlResponse(BaseModel):
    id: str
    ddl: str | None
