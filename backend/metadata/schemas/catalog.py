"""Catalog browse, semantics, and join API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "CatalogColumnOut",
    "CatalogColumnResponse",
    "CatalogColumnSearchResponse",
    "CatalogDdlResponse",
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
    "RelationSummaryModel",
    "SemanticSource",
    "StatusSemanticsModel",
    "TimeSemanticsModel",
]

ObjectCategory = Literal[
    "transaction_fact",
    "master_data",
    "dimension",
    "reference",
    "event",
]
SemanticSource = Literal["mcp", "user_input"]


class TimeSemanticsModel(BaseModel):
    primary_time_field: str | None = None
    time_role: str | None = None


class StatusSemanticsModel(BaseModel):
    primary_status_field: str | None = None
    status_meaning: str | None = None


class RelationSummaryModel(BaseModel):
    input_role_hint: str | None = None
    main_upstream_or_dimension_objects: list[str] | None = None
    likely_child_objects: list[str] | None = None


class ColumnSemanticsModel(BaseModel):
    semantic_type: str | None = None
    value_pattern: str | None = None
    unit: str | None = None


class EnumCatalogEntry(BaseModel):
    code: str
    label: str
    description: str | None = None


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
    time_semantics: TimeSemanticsModel | None = None
    status_semantics: StatusSemanticsModel | None = None
    relation_summary: RelationSummaryModel | None = None
    business_domain: str | None = None
    evidence_summary: list[str] | None = None
    confidence: float | None = None
    open_questions: list[str] | None = None
    semantic_source: SemanticSource | str | None = None
    business_semantics_ready: bool = False
    semantics_updated_at: datetime | None = None
    columns: list[CatalogColumnOut] = Field(default_factory=list)
    ddl: str | None = None
    is_present: bool = True
    collected_at: datetime | None = None


class CatalogObjectListResponse(BaseModel):
    items: list[CatalogObjectOut]
    total: int = 0
    limit: int = 100
    offset: int = 0


class CatalogObjectSearchResponse(BaseModel):
    items: list[CatalogObjectOut]
    total: int
    limit: int
    offset: int


class CatalogColumnSearchResponse(BaseModel):
    items: list[CatalogColumnOut]
    total: int
    limit: int
    offset: int


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
    time_semantics: TimeSemanticsModel | None = None
    status_semantics: StatusSemanticsModel | None = None
    relation_summary: RelationSummaryModel | None = None
    business_domain: str | None = None
    evidence_summary: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    open_questions: list[str] | None = None


class ColumnSemanticsPatchRequest(BaseModel):
    business_name: str | None = None
    business_description: str | None = None
    column_semantics: ColumnSemanticsModel | None = None
    enum_catalog: list[EnumCatalogEntry] | None = None


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
    created_at: datetime


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
