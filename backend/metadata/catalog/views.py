"""Catalog transport-neutral view models and mappers (internal)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from backend.metadata.business_domains.store import get_business_domain_store
from backend.metadata.catalog.store import (
    CatalogColumnRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    get_catalog_store,
)


@dataclass(frozen=True)
class DomainRefView:
    id: str
    code: str
    name: str


@dataclass(frozen=True)
class ColumnView:
    id: str
    locator_key: str
    name: str
    data_type: str
    nullable: bool
    default_value: str | None
    comment: str | None
    business_name: str | None
    business_description: str | None
    column_semantics: dict[str, Any] | None
    enum_catalog: list[dict[str, Any]] | None
    semantic_source: str | None
    field_kind: str
    ordinal: int
    is_present: bool
    normalized_type: str | None = None


@dataclass(frozen=True)
class ForeignKeyView:
    name: str
    columns: list[str]
    ref_schema: str
    ref_table: str
    ref_columns: list[str]
    is_present: bool


@dataclass(frozen=True)
class IndexView:
    name: str
    columns: list[str]
    is_unique: bool
    is_present: bool


@dataclass
class ObjectView:
    id: str
    locator_key: str
    source_id: str
    object_type: str
    schema_name: str
    name: str
    comment: str | None
    primary_key: list[str] | None
    business_name: str | None
    business_description: str | None
    object_category: str | None
    grain_description: str | None
    business_primary_key: list[str] | None
    business_domain: DomainRefView | None
    evidence_summary: list[str] | None
    open_questions: list[str] | None
    semantic_source: str | None
    business_semantics_ready: bool
    semantics_updated_at: datetime | None
    is_present: bool
    collected_at: datetime | None
    columns: list[ColumnView] = field(default_factory=list)
    foreign_keys: list[ForeignKeyView] = field(default_factory=list)
    indexes: list[IndexView] = field(default_factory=list)
    ddl: str | None = None


@dataclass(frozen=True)
class ObjectSemanticsView:
    locator_key: str
    business_name: str | None
    business_description: str | None
    object_category: str | None
    grain_description: str | None
    business_primary_key: list[str] | None
    business_domain: DomainRefView | None
    evidence_summary: list[str] | None
    open_questions: list[str] | None
    semantic_source: str | None
    business_semantics_ready: bool


@dataclass(frozen=True)
class ObjectDdlView:
    id: str
    locator_key: str
    ddl: str | None


@dataclass(frozen=True)
class JoinView:
    id: str
    from_column_id: str
    to_column_id: str
    from_column_locator_key: str | None
    to_column_locator_key: str | None
    evidence: str
    join_kind: str
    join_expression: str | None
    created_by_user_id: str | None
    created_at: datetime
    is_rejected: bool = False
    rejected_at: datetime | None = None
    rejected_by_user_id: str | None = None


@dataclass(frozen=True)
class JoinPathHopView:
    from_column_id: str
    to_column_id: str
    from_column_locator_key: str | None
    to_column_locator_key: str | None
    join_id: str
    join_kind: str
    join_expression: str | None
    evidence: str


@dataclass(frozen=True)
class JoinPathView:
    target_object_id: str | None
    target_column_id: str | None
    hops: list[JoinPathHopView]
    path_summary: str


@dataclass(frozen=True)
class JoinPathLookup:
    paths_found: int
    paths: list[JoinPathView]
    direct_joins: list[JoinView]
    reason: str | None


def domain_ref_view(domain_id: str | None) -> DomainRefView | None:
    if not domain_id:
        return None

    record = get_business_domain_store().get(domain_id)
    if record is None:
        return None
    return DomainRefView(id=record.id, code=record.code, name=record.name)


def column_view(record: CatalogColumnRecord) -> ColumnView:
    return ColumnView(
        id=record.id,
        locator_key=record.locator_key,
        name=record.name,
        data_type=record.data_type,
        nullable=record.nullable,
        default_value=record.default_value,
        comment=record.comment,
        business_name=record.business_name,
        business_description=record.business_description,
        column_semantics=record.column_semantics,
        enum_catalog=record.enum_catalog,
        semantic_source=record.semantic_source,
        field_kind=record.field_kind,
        ordinal=record.ordinal,
        is_present=record.is_present,
        normalized_type=record.normalized_type,
    )


def object_view(
    record: CatalogObjectRecord, *, include_columns: bool
) -> ObjectView:
    columns: list[ColumnView] = []
    foreign_keys: list[ForeignKeyView] = []
    indexes: list[IndexView] = []
    ddl: str | None = None
    if include_columns:
        columns = [column_view(c) for c in record.columns]
        foreign_keys = [
            ForeignKeyView(
                name=fk.name,
                columns=list(fk.columns),
                ref_schema=fk.ref_schema,
                ref_table=fk.ref_table,
                ref_columns=list(fk.ref_columns),
                is_present=fk.is_present,
            )
            for fk in record.foreign_keys
        ]
        indexes = [
            IndexView(
                name=idx.name,
                columns=list(idx.columns),
                is_unique=idx.is_unique,
                is_present=idx.is_present,
            )
            for idx in record.indexes
        ]
        ddl = record.ddl
    return ObjectView(
        id=record.id,
        locator_key=record.locator_key,
        source_id=record.source_id,
        object_type=record.object_type,
        schema_name=record.schema_name,
        name=record.name,
        comment=record.comment,
        primary_key=record.primary_key,
        business_name=record.business_name,
        business_description=record.business_description,
        object_category=record.object_category,
        grain_description=record.grain_description,
        business_primary_key=record.business_primary_key,
        business_domain=domain_ref_view(record.business_domain_id),
        evidence_summary=record.evidence_summary,
        open_questions=record.open_questions,
        semantic_source=record.semantic_source,
        business_semantics_ready=record.business_semantics_ready,
        semantics_updated_at=record.semantics_updated_at,
        is_present=record.is_present,
        collected_at=record.collected_at,
        columns=columns,
        foreign_keys=foreign_keys,
        indexes=indexes,
        ddl=ddl,
    )


def join_view(record: CatalogJoinRecord) -> JoinView:
    store = get_catalog_store()
    from_col = store.get_column(record.from_column_id)
    to_col = store.get_column(record.to_column_id)
    return JoinView(
        id=record.id,
        from_column_id=record.from_column_id,
        to_column_id=record.to_column_id,
        from_column_locator_key=from_col.locator_key if from_col else None,
        to_column_locator_key=to_col.locator_key if to_col else None,
        evidence=record.evidence,
        join_kind=record.join_kind,
        join_expression=record.join_expression,
        created_by_user_id=record.created_by_user_id,
        created_at=record.created_at,
        is_rejected=record.is_rejected,
        rejected_at=record.rejected_at,
        rejected_by_user_id=record.rejected_by_user_id,
    )


def object_view_as_dict(view: ObjectView, *, include_columns: bool) -> dict[str, Any]:
    """MCP-shaped object payload (no foreign_keys/indexes; columns/ddl when detailed)."""
    payload: dict[str, Any] = {
        "id": view.id,
        "locator_key": view.locator_key,
        "source_id": view.source_id,
        "object_type": view.object_type,
        "schema_name": view.schema_name,
        "name": view.name,
        "comment": view.comment,
        "primary_key": view.primary_key,
        "business_name": view.business_name,
        "business_description": view.business_description,
        "object_category": view.object_category,
        "grain_description": view.grain_description,
        "business_primary_key": view.business_primary_key,
        "business_domain": asdict(view.business_domain) if view.business_domain else None,
        "evidence_summary": view.evidence_summary,
        "open_questions": view.open_questions,
        "semantic_source": view.semantic_source,
        "business_semantics_ready": view.business_semantics_ready,
        "semantics_updated_at": view.semantics_updated_at,
        "is_present": view.is_present,
        "collected_at": view.collected_at,
    }
    if include_columns:
        payload["ddl"] = view.ddl
        payload["columns"] = [_mcp_column_dict(c) for c in view.columns]
    return payload


def column_view_as_dict(view: ColumnView) -> dict[str, Any]:
    return _mcp_column_dict(view)


def _mcp_column_dict(view: ColumnView) -> dict[str, Any]:
    payload = asdict(view)
    payload.pop("normalized_type", None)
    return payload


def join_view_as_dict(view: JoinView) -> dict[str, Any]:
    return asdict(view)
