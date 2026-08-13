"""Catalog domain service — browse/search/join-path + semantics/join writes (HTTP + MCP)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.metadata.business_domains.service import require_domain_by_code
from backend.metadata.business_domains.store import get_business_domain_store
from backend.metadata.catalog.join_origin import resolve_join_write
from backend.metadata.catalog.store import (
    CatalogColumnRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    UNSET,
    get_catalog_store,
    require_object,
)
from backend.metadata.errors import (
    CatalogColumnNotFound,
    CatalogJoinNotFound,
    CatalogObjectNotFound,
    CatalogSearchQueryRequired,
    JoinCrossSource,
    JoinEvidenceRequired,
    JoinInvalid,
    JoinPathUnavailable,
    SemanticColumnUnknown,
    SourceNotFound,
)
from backend.metadata.joins.graph import find_join_paths
from backend.metadata.sources.service import require_source
from backend.metadata.sources.store import SourceRecord, get_source_store


_EVIDENCE_AUDIT_MAX = 500

# --- Shared read models (transport-neutral) ---

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
    origin: str
    created_by_user_id: str | None
    created_at: datetime

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
    origin: str

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
        origin=record.origin,
        created_by_user_id=record.created_by_user_id,
        created_at=record.created_at,
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

def _resolve_path_endpoint(
    ref: str,
) -> tuple[str | None, str | None]:
    """Resolve locator/id to (object_id, column_id); column preferred."""
    try:
        col = resolve_column_ref(ref)
        return None, col.id
    except CatalogColumnNotFound:
        pass
    obj = resolve_object_ref(ref)
    return obj.id, None

# --- Browse / search / get / join-path use cases ---

def list_objects_for_source(
    source_id: str,
    *,
    q: str | None = None,
    object_type: str | None = None,
    include_absent: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ObjectView], int]:
    require_source(source_id)
    items, total = get_catalog_store().list_objects(
        source_id,
        name_search=q,
        include_absent=include_absent,
        object_type=object_type,
        limit=limit,
        offset=offset,
    )
    return [object_view(o, include_columns=False) for o in items], total

def search_objects(
    query: str,
    *,
    source_id: str | None = None,
    object_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ObjectView], int]:
    cleaned = (query or "").strip()
    if not cleaned:
        raise CatalogSearchQueryRequired()
    items, total = get_catalog_store().search_objects(
        cleaned,
        source_id=source_id,
        object_type=object_type,
        limit=limit,
        offset=offset,
    )
    return [object_view(o, include_columns=False) for o in items], total

def search_columns(
    query: str,
    *,
    source_id: str | None = None,
    object_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ColumnView], int]:
    cleaned = (query or "").strip()
    if not cleaned:
        raise CatalogSearchQueryRequired()
    items, total = get_catalog_store().search_columns(
        cleaned,
        source_id=source_id,
        object_type=object_type,
        limit=limit,
        offset=offset,
    )
    return [column_view(c) for c in items], total

def get_object(object_ref: str) -> ObjectView:
    record = resolve_object_ref(object_ref)
    return object_view(record, include_columns=True)

def get_object_ddl(object_ref: str) -> ObjectDdlView:
    record = resolve_object_ref(object_ref)
    return ObjectDdlView(id=record.id, locator_key=record.locator_key, ddl=record.ddl)

def get_object_semantics(object_ref: str) -> ObjectSemanticsView:
    record = resolve_object_ref(object_ref)
    return ObjectSemanticsView(
        locator_key=record.locator_key,
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
    )

def inspect_object(object_ref: str) -> ObjectView:
    return get_object(object_ref)

def lookup_join_paths(
    start_ref: str,
    target_ref: str | None = None,
    *,
    max_hops: int = 1,
    top_targets: int = 3,
) -> JoinPathLookup:
    start_object_id, start_column_id = _resolve_path_endpoint(start_ref)
    target_object_id: str | None = None
    target_column_id: str | None = None
    if target_ref:
        target_object_id, target_column_id = _resolve_path_endpoint(target_ref)

    store = get_catalog_store()
    result = find_join_paths(
        store=store,
        start_object_id=start_object_id,
        start_column_id=start_column_id,
        target_object_id=target_object_id,
        target_column_id=target_column_id,
        max_hops=max_hops,
        top_targets=top_targets,
    )
    if result.reason == "NO_START_COLUMNS":
        raise JoinPathUnavailable()

    paths: list[JoinPathView] = []
    for path in result.paths:
        hops: list[JoinPathHopView] = []
        for hop in path.hops:
            from_col = store.get_column(hop.from_column_id)
            to_col = store.get_column(hop.to_column_id)
            hops.append(
                JoinPathHopView(
                    from_column_id=hop.from_column_id,
                    to_column_id=hop.to_column_id,
                    from_column_locator_key=from_col.locator_key if from_col else None,
                    to_column_locator_key=to_col.locator_key if to_col else None,
                    join_id=hop.join.id,
                    join_kind=hop.join.join_kind,
                    join_expression=hop.join.join_expression,
                    evidence=hop.join.evidence,
                    origin=hop.join.origin,
                )
            )
        paths.append(
            JoinPathView(
                target_object_id=path.target_object_id,
                target_column_id=path.target_column_id,
                hops=hops,
                path_summary=path.path_summary,
            )
        )
    return JoinPathLookup(
        paths_found=len(paths),
        paths=paths,
        direct_joins=[join_view(j) for j in result.direct_joins],
        reason=result.reason,
    )

_OBJECT_SEMANTIC_FIELDS = (
    "business_name",
    "business_description",
    "object_category",
    "grain_description",
    "business_primary_key",
    "business_domain_id",
    "evidence_summary",
    "open_questions",
)

_COLUMN_SEMANTIC_FIELDS = (
    "business_name",
    "business_description",
    "column_semantics",
    "enum_catalog",
)

def _field_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True

def compute_business_semantics_ready(
    *,
    business_name: str | None,
    business_description: str | None,
    open_questions: list[str] | None,
) -> bool:
    if not _field_nonempty(business_name) or not _field_nonempty(business_description):
        return False
    if open_questions:
        return False
    return True

def _normalize_semantic_value(value: Any) -> Any:
    """Normalize a present PATCH value; blank/empty becomes None (clear)."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    if isinstance(value, (list, dict)):
        return value if len(value) > 0 else None
    return value

def _build_semantic_kwargs(
    *,
    data: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """Build store kwargs from request data.

    Omitted keys are unchanged. Present keys apply: JSON null, blank strings,
    and empty list/dict clear the field (store NULL). Non-empty strings are trimmed.
    """
    kwargs: dict[str, Any] = {}
    for key in fields:
        if key not in data:
            continue
        kwargs[key] = _normalize_semantic_value(data[key])
    return kwargs

def require_column(column_id: str) -> CatalogColumnRecord:
    record = get_catalog_store().get_column(column_id)
    if record is None:
        raise CatalogColumnNotFound()
    return record

def require_join(join_id: str) -> CatalogJoinRecord:
    record = get_catalog_store().get_join(join_id)
    if record is None:
        raise CatalogJoinNotFound()
    return record

def resolve_source_ref(ref: str) -> SourceRecord:
    """Resolve Source by id or locator_key."""
    store = get_source_store()
    record = store.get_source(ref) or store.get_source_by_locator(ref)
    if record is None:

        raise SourceNotFound()
    return record

def resolve_object_ref(ref: str) -> CatalogObjectRecord:
    store = get_catalog_store()
    record = store.get_object(ref) or store.get_object_by_locator(ref)
    if record is None:
        raise CatalogObjectNotFound()
    return record

def resolve_column_ref(ref: str) -> CatalogColumnRecord:
    store = get_catalog_store()
    record = store.get_column(ref) or store.get_column_by_locator(ref)
    if record is None:
        raise CatalogColumnNotFound()
    return record

def _validate_business_primary_key(
    existing: CatalogObjectRecord, names: list[str]
) -> None:
    known = {c.name for c in existing.columns}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise SemanticColumnUnknown(
            f"Unknown column(s) in business_primary_key: {', '.join(unknown)}"
        )

def patch_object_semantics(
    *,
    object_id: str,
    data: dict[str, Any],
    actor_user_id: str | None,
    actor_token_id: str | None,
    semantic_source: str = "user_input",
) -> CatalogObjectRecord:
    existing = require_object(object_id)
    # Resolve business_domain_code → business_domain_id before field extraction.
    resolved = dict(data)
    if "business_domain_code" in resolved:
        code = _normalize_semantic_value(resolved["business_domain_code"])
        if code is None:
            resolved["business_domain_id"] = None
        else:
            domain = require_domain_by_code(str(code))
            resolved["business_domain_id"] = domain.id
    kwargs = _build_semantic_kwargs(data=resolved, fields=_OBJECT_SEMANTIC_FIELDS)
    if not kwargs:
        return existing
    if "business_primary_key" in kwargs and kwargs["business_primary_key"] is not None:
        names = kwargs["business_primary_key"]
        if not isinstance(names, list):
            raise SemanticColumnUnknown("business_primary_key must be a list of column names")
        _validate_business_primary_key(existing, [str(n) for n in names])
    # Merge for ready computation.
    business_name = kwargs.get("business_name", existing.business_name)
    business_description = kwargs.get(
        "business_description", existing.business_description
    )
    open_questions = kwargs.get("open_questions", existing.open_questions)
    ready = compute_business_semantics_ready(
        business_name=business_name,
        business_description=business_description,
        open_questions=open_questions,
    )
    store_kwargs: dict[str, Any] = {k: UNSET for k in _OBJECT_SEMANTIC_FIELDS}
    store_kwargs.update(kwargs)
    store_kwargs["semantic_source"] = semantic_source
    store_kwargs["business_semantics_ready"] = ready
    updated = get_catalog_store().patch_object_semantics(object_id, **store_kwargs)
    assert updated is not None
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_object",
        resource_id=object_id,
        action="semantics.object_patch",
        result="success",
        detail={
            "changed": list(kwargs.keys()),
            "cleared": [k for k, v in kwargs.items() if v is None],
            "semantic_source": semantic_source,
        },
    )
    return updated

def patch_column_semantics(
    *,
    column_id: str,
    data: dict[str, Any],
    actor_user_id: str | None,
    actor_token_id: str | None,
    semantic_source: str = "user_input",
) -> tuple[CatalogColumnRecord, bool]:
    """Patch column semantics. Returns (record, applied)."""
    existing = require_column(column_id)
    kwargs = _build_semantic_kwargs(data=data, fields=_COLUMN_SEMANTIC_FIELDS)
    if not kwargs:
        return existing, False
    store_kwargs: dict[str, Any] = {k: UNSET for k in _COLUMN_SEMANTIC_FIELDS}
    store_kwargs.update(kwargs)
    store_kwargs["semantic_source"] = semantic_source
    updated = get_catalog_store().patch_column_semantics(column_id, **store_kwargs)
    assert updated is not None
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_column",
        resource_id=column_id,
        action="semantics.column_patch",
        result="success",
        detail={
            "object_id": updated.object_id,
            "changed": list(kwargs.keys()),
            "cleared": [k for k, v in kwargs.items() if v is None],
            "semantic_source": semantic_source,
        },
    )
    return updated, True

def set_column_semantics_batch(
    *,
    object_id: str,
    columns: list[dict[str, Any]],
    actor_user_id: str | None,
    actor_token_id: str | None,
    semantic_source: str = "mcp",
) -> dict[str, Any]:
    obj = require_object(object_id)
    by_name = {c.name: c for c in obj.columns}
    updated_count = 0
    skipped_columns: list[dict[str, Any]] = []
    for item in columns:
        name = item.get("column_name")
        if not isinstance(name, str) or not name.strip():
            skipped_columns.append(
                {
                    "column_name": name if isinstance(name, str) else None,
                    "reason": "invalid_column_name",
                }
            )
            continue
        col = by_name.get(name)
        if col is None:
            skipped_columns.append(
                {"column_name": name, "reason": "invalid_column_name"}
            )
            continue
        data = {k: v for k, v in item.items() if k != "column_name"}
        _, applied = patch_column_semantics(
            column_id=col.id,
            data=data,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            semantic_source=semantic_source,
        )
        if applied:
            updated_count += 1
        else:
            skipped_columns.append({"column_name": name, "reason": "no_changes"})
    return {
        "updated_count": updated_count,
        "requested_count": len(columns),
        "skipped_columns": skipped_columns,
    }

def list_joins(object_id: str) -> list[JoinView]:
    require_object(object_id)
    return [join_view(j) for j in get_catalog_store().list_joins_for_object(object_id)]

def upsert_join(
    *,
    from_column_id: str,
    to_column_id: str,
    evidence: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
    join_kind: str = "INNER",
    join_expression: str | None = None,
    origin: str = "human",
) -> CatalogJoinRecord:
    cleaned = (evidence or "").strip()
    if not cleaned:
        raise JoinEvidenceRequired()
    if from_column_id == to_column_id:
        raise JoinInvalid()
    from_col = require_column(from_column_id)
    to_col = require_column(to_column_id)
    from_obj = require_object(from_col.object_id)
    to_obj = require_object(to_col.object_id)
    if from_obj.source_id != to_obj.source_id:
        raise JoinCrossSource()
    expression = join_expression
    if expression is None:
        expression = f"{from_col.name} = {to_col.name}"
    kind = (join_kind or "INNER").strip() or "INNER"
    store = get_catalog_store()
    existing = store.get_join_by_pair(from_column_id, to_column_id)
    existing_origin = existing.origin if existing is not None else None
    if (
        resolve_join_write(
            existing_origin=existing_origin,
            incoming_origin=origin,
        )
        == "keep_existing"
    ):
        assert existing is not None
        return existing
    record = store.upsert_join(
        from_column_id=from_column_id,
        to_column_id=to_column_id,
        evidence=cleaned,
        created_by_user_id=actor_user_id,
        join_kind=kind,
        join_expression=expression,
        origin=origin,
    )
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_join",
        resource_id=record.id,
        action="join.upsert",
        result="success",
        detail={
            "from_column_id": from_column_id,
            "to_column_id": to_column_id,
            "evidence": cleaned[:_EVIDENCE_AUDIT_MAX],
            "join_kind": kind,
            "origin": origin,
        },
    )
    return record

def upsert_joins_batch(
    *,
    joins: list[dict[str, Any]],
    actor_user_id: str | None,
    actor_token_id: str | None,
    origin: str = "human",
) -> tuple[list[CatalogJoinRecord], int, int]:
    """Upsert many joins; all edges must share one Source. Returns items, created, known."""
    if not joins:
        return [], 0, 0
    store = get_catalog_store()
    source_id: str | None = None
    created = 0
    known = 0
    items: list[CatalogJoinRecord] = []
    for item in joins:
        from_id = str(item["from_column_id"])
        to_id = str(item["to_column_id"])
        from_col = require_column(from_id)
        to_col = require_column(to_id)
        from_obj = require_object(from_col.object_id)
        to_obj = require_object(to_col.object_id)
        if from_obj.source_id != to_obj.source_id:
            raise JoinCrossSource()
        if source_id is None:
            source_id = from_obj.source_id
        elif from_obj.source_id != source_id:
            raise JoinCrossSource()
        # Pair known?
        existing = None
        for j in store.list_all_joins_for_source(from_obj.source_id):
            if j.from_column_id == from_id and j.to_column_id == to_id:
                existing = j
                break
        record = upsert_join(
            from_column_id=from_id,
            to_column_id=to_id,
            evidence=str(item.get("evidence") or ""),
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            join_kind=str(item.get("join_kind") or "INNER"),
            join_expression=item.get("join_expression"),
            origin=origin,
        )
        if existing is not None:
            known += 1
        else:
            created += 1
        items.append(record)
    return items, created, known

def delete_join(
    *,
    join_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    existing = require_join(join_id)
    deleted = get_catalog_store().delete_join(join_id)
    if not deleted:
        raise CatalogJoinNotFound()
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_join",
        resource_id=join_id,
        action="join.delete",
        result="success",
        detail={
            "from_column_id": existing.from_column_id,
            "to_column_id": existing.to_column_id,
        },
    )
