"""Domain Job / Catalog API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "CatalogColumnOut",
    "CatalogDdlResponse",
    "CatalogObjectListResponse",
    "CatalogObjectOut",
    "CatalogObjectResponse",
    "EnqueueStructureJobRequest",
]


class EnqueueStructureJobRequest(BaseModel):
    kind: Literal["structure"] = "structure"


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
