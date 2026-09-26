"""HTTP request and response shapes for Business Entity."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.core.pagination import OffsetPage
from backend.core.time import Instant
from backend.jobs.schemas.jobs import JobOut

NormalizedType = Literal[
    "string",
    "integer",
    "number",
    "boolean",
    "date",
    "timestamp",
    "time",
    "interval",
    "binary",
    "json",
    "array",
    "unknown",
]


class AttributeIn(BaseModel):
    name: str = Field(min_length=1, max_length=63)
    normalized_type: NormalizedType
    nullable: bool
    unique: bool = False
    indexed: bool = False
    description: str | None = None


class AttributeOut(BaseModel):
    name: str
    normalized_type: str
    nullable: bool
    unique: bool = False
    indexed: bool = False
    description: str | None = None


class AlignmentOut(BaseModel):
    table_present: bool
    definition_ahead: bool
    latest_job_id: str | None = None
    latest_job_status: str | None = None


class CurrentVersionOut(BaseModel):
    id: str
    version: int
    publish_status: str
    table_name: str | None
    alignment: AlignmentOut


class BusinessEntityOut(BaseModel):
    id: str
    table_name: str
    name: str
    description: str
    deprecated_at: Instant | None = None
    ever_published: bool = False
    current_version: CurrentVersionOut | None = None
    created_at: Instant
    updated_at: Instant


class EntityVersionOut(BaseModel):
    id: str
    entity_id: str
    version: int
    publish_status: str
    attributes: list[AttributeOut] | None = None
    attribute_count: int | None = None
    table_name: str | None
    alignment: AlignmentOut
    created_at: Instant
    updated_at: Instant


class ShapeChangeOut(BaseModel):
    field: str
    old_value: Any = None
    new_value: Any = None
    change_class: str = Field(alias="class")

    model_config = ConfigDict(populate_by_name=True)


class ClassificationOut(BaseModel):
    change_class: str = Field(alias="class")
    changes: list[ShapeChangeOut]

    model_config = ConfigDict(populate_by_name=True)


class BusinessEntityListResponse(OffsetPage[BusinessEntityOut]):
    pass


class BusinessEntityResponse(BaseModel):
    entity: BusinessEntityOut


class EntityVersionListResponse(OffsetPage[EntityVersionOut]):
    pass


class EntityVersionResponse(BaseModel):
    version: EntityVersionOut


class EntityCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_name: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1)
    attributes: list[AttributeIn]


class EntityPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, min_length=1)
    attributes: list[AttributeIn] | None = None


class ShapeWriteRequest(BaseModel):
    attributes: list[AttributeIn] | None = None


class EntityJobEnqueueResponse(BaseModel):
    job: JobOut | None = None
    version: EntityVersionOut | None = None
