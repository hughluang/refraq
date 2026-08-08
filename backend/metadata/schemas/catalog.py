"""Catalog browse, semantics, and join API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "CatalogColumnOut",
    "CatalogColumnResponse",
    "CatalogDdlResponse",
    "CatalogObjectListResponse",
    "CatalogObjectOut",
    "CatalogObjectResponse",
    "JoinListResponse",
    "JoinOut",
    "JoinResponse",
    "JoinUpsertRequest",
    "SemanticsPatchRequest",
]


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


class CatalogColumnResponse(BaseModel):
    column: CatalogColumnOut


class CatalogDdlResponse(BaseModel):
    id: str
    ddl: str | None


class SemanticsPatchRequest(BaseModel):
    business_name: str | None = None
    business_description: str | None = None


class JoinUpsertRequest(BaseModel):
    from_column_id: str
    to_column_id: str
    evidence: str


class JoinOut(BaseModel):
    id: str
    from_column_id: str
    to_column_id: str
    evidence: str
    created_by_user_id: str | None
    created_at: datetime


class JoinListResponse(BaseModel):
    items: list[JoinOut]


class JoinResponse(BaseModel):
    join: JoinOut
