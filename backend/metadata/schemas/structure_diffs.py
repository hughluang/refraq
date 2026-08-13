"""Structure Diff HTTP schemas."""

from __future__ import annotations

from typing import Any

from backend.core.time import Instant
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "StructureDiffListItemOut",
    "StructureDiffListResponse",
    "StructureDiffOut",
    "StructureDiffResponse",
]


class StructureDiffListItemOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source_id: str
    job_id: str
    class_: str = Field(alias="class", serialization_alias="class")
    counts: dict[str, int]
    created_at: Instant


class StructureDiffOut(StructureDiffListItemOut):
    changes: list[dict[str, Any]]


class StructureDiffListResponse(BaseModel):
    items: list[StructureDiffListItemOut]
    total: int = 0
    limit: int = 50
    offset: int = 0


class StructureDiffResponse(BaseModel):
    structure_diff: StructureDiffOut
