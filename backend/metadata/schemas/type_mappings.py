"""Type Mapping HTTP schemas."""

from __future__ import annotations

from typing import Literal

from backend.core.time import Instant
from pydantic import BaseModel, Field

__all__ = [
    "TypeMappingListResponse",
    "TypeMappingOut",
    "TypeMappingPatchRequest",
    "TypeMappingResponse",
]

TypeMappingOrigin = Literal["product", "job", "user"]
PatchableNormalizedType = Literal[
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


class TypeMappingOut(BaseModel):
    id: str
    engine: str
    native_type: str
    normalized_type: str
    origin: TypeMappingOrigin
    created_at: Instant
    updated_at: Instant


class TypeMappingListResponse(BaseModel):
    items: list[TypeMappingOut]
    total: int = 0
    limit: int = 100
    offset: int = 0


class TypeMappingResponse(BaseModel):
    mapping: TypeMappingOut


class TypeMappingPatchRequest(BaseModel):
    normalized_type: PatchableNormalizedType = Field(...)
