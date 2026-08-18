"""Catalog browse, semantics, and join API schemas."""

from __future__ import annotations

from backend.core.pagination import OffsetPage
from backend.core.time import Instant
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "BusinessDomainRef",
    "CatalogColumnOut",
    "CatalogColumnResponse",
    "CatalogColumnSearchResponse",
    "CatalogColumnsSemanticsBatchRequest",
    "CatalogColumnsSemanticsBatchResponse",
    "CatalogColumnSemanticsBatchItem",
    "CatalogDdlResponse",
    "CatalogForeignKeyOut",
    "CatalogIndexOut",
    "CatalogObjectListResponse",
    "CatalogObjectOut",
    "CatalogObjectResponse",
    "CatalogObjectSearchResponse",
    "ColumnSemanticsModel",
    "ColumnSemanticsPatchRequest",
    "EnumCatalogEntry",
    "JoinBatchResponse",
    "JoinBatchUpsertRequest",
    "JoinListResponse",
    "JoinOut",
    "JoinPathHopOut",
    "JoinPathOut",
    "JoinPathResponse",
    "JoinResponse",
    "JoinUpsertRequest",
    "ObjectCategory",
    "ObjectSemanticsPatchRequest",
    "SemanticSource",
]

ObjectCategory = Literal[
    "transaction_fact",
    "master_data",
    "dimension",
    "reference",
    "event",
]
SemanticSource = Literal["mcp", "user_input"]


class ColumnSemanticsModel(BaseModel):
    semantic_type: str | None = None
    value_pattern: str | None = None
    unit: str | None = None


class EnumCatalogEntry(BaseModel):
    code: str
    label: str
    description: str | None = None


class BusinessDomainRef(BaseModel):
    id: str
    code: str
    name: str


class CatalogColumnOut(BaseModel):
    id: str
    locator_key: str
    name: str
    data_type: str
    nullable: bool
    default_value: str | None = None
    comment: str | None = None
    business_name: str | None = None
    business_description: str | None = None
    column_semantics: ColumnSemanticsModel | None = None
    enum_catalog: list[EnumCatalogEntry] | None = None
    semantic_source: SemanticSource | str | None = None
    field_kind: str = "column"
    ordinal: int = 0
    is_present: bool = True
    normalized_type: str | None = None


class CatalogForeignKeyOut(BaseModel):
    name: str
    columns: list[str]
    ref_schema: str
    ref_table: str
    ref_columns: list[str]
    is_present: bool = True


class CatalogIndexOut(BaseModel):
    name: str
    columns: list[str]
    is_unique: bool
    is_present: bool = True


class CatalogObjectOut(BaseModel):
    id: str
    locator_key: str
    source_id: str
    object_type: str
    schema_name: str
    name: str
    comment: str | None = None
    primary_key: list[str] | None = None
    business_name: str | None = None
    business_description: str | None = None
    object_category: ObjectCategory | str | None = None
    grain_description: str | None = None
    business_primary_key: list[str] | None = None
    business_domain: BusinessDomainRef | None = None
    evidence_summary: list[str] | None = None
    open_questions: list[str] | None = None
    semantic_source: SemanticSource | str | None = None
    business_semantics_ready: bool = False
    semantics_updated_at: Instant | None = None
    columns: list[CatalogColumnOut] = Field(default_factory=list)
    foreign_keys: list[CatalogForeignKeyOut] = Field(default_factory=list)
    indexes: list[CatalogIndexOut] = Field(default_factory=list)
    ddl: str | None = None
    is_present: bool = True
    collected_at: Instant | None = None


class CatalogObjectListResponse(OffsetPage[CatalogObjectOut]):
    pass


class CatalogObjectSearchResponse(OffsetPage[CatalogObjectOut]):
    pass


class CatalogColumnSearchResponse(OffsetPage[CatalogColumnOut]):
    pass


class CatalogObjectResponse(BaseModel):
    object: CatalogObjectOut


class CatalogColumnResponse(BaseModel):
    column: CatalogColumnOut


class CatalogDdlResponse(BaseModel):
    id: str
    ddl: str | None


class ObjectSemanticsPatchRequest(BaseModel):
    business_name: str | None = None
    business_description: str | None = None
    object_category: ObjectCategory | None = None
    grain_description: str | None = None
    business_primary_key: list[str] | None = None
    business_domain_code: str | None = None
    evidence_summary: list[str] | None = None
    open_questions: list[str] | None = None


class ColumnSemanticsPatchRequest(BaseModel):
    business_name: str | None = None
    business_description: str | None = None
    column_semantics: ColumnSemanticsModel | None = None
    enum_catalog: list[EnumCatalogEntry] | None = None


class CatalogColumnSemanticsBatchItem(BaseModel):
    column_name: str
    business_name: str | None = None
    business_description: str | None = None
    column_semantics: ColumnSemanticsModel | None = None
    enum_catalog: list[EnumCatalogEntry] | None = None


class CatalogColumnsSemanticsBatchRequest(BaseModel):
    columns: list[CatalogColumnSemanticsBatchItem]


class CatalogColumnsSemanticsBatchResponse(BaseModel):
    object: CatalogObjectOut
    updated_count: int
    requested_count: int
    skipped_columns: list[dict] = Field(default_factory=list)


class JoinUpsertRequest(BaseModel):
    from_column_id: str
    to_column_id: str
    evidence: str
    join_kind: str | None = "INNER"
    join_expression: str | None = None


class JoinBatchUpsertRequest(BaseModel):
    joins: list[JoinUpsertRequest]


class JoinOut(BaseModel):
    id: str
    from_column_id: str
    to_column_id: str
    from_column_locator_key: str | None = None
    to_column_locator_key: str | None = None
    evidence: str
    join_kind: str = "INNER"
    join_expression: str | None = None
    origin: str = "human"
    created_by_user_id: str | None = None
    created_at: Instant


class JoinListResponse(BaseModel):
    items: list[JoinOut]


class JoinResponse(BaseModel):
    join: JoinOut


class JoinBatchResponse(BaseModel):
    created_count: int
    already_known_count: int
    items: list[JoinOut]


class JoinPathHopOut(BaseModel):
    from_column_id: str
    to_column_id: str
    from_column_locator_key: str | None = None
    to_column_locator_key: str | None = None
    join_id: str
    join_kind: str
    join_expression: str | None = None
    evidence: str
    origin: str


class JoinPathOut(BaseModel):
    target_object_id: str | None = None
    target_column_id: str | None = None
    hops: list[JoinPathHopOut]
    path_summary: str


class JoinPathResponse(BaseModel):
    paths_found: int
    paths: list[JoinPathOut]
    direct_joins: list[JoinOut] = Field(default_factory=list)
    reason: str | None = None
