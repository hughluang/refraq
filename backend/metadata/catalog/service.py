"""Catalog semantics and join domain service (HTTP + MCP shared)."""

from __future__ import annotations

from typing import Any

from backend.admin.audit import persist_audit_event
from backend.metadata.business_domains.service import require_domain_by_code
from backend.metadata.catalog.store import (
    UNSET,
    CatalogColumnRecord,
    CatalogJoinRecord,
    CatalogObjectRecord,
    get_catalog_store,
    require_object,
)
from backend.metadata.errors import (
    CatalogColumnNotFound,
    CatalogJoinNotFound,
    CatalogObjectNotFound,
    JoinCrossSource,
    JoinEvidenceRequired,
    JoinInvalid,
    SemanticColumnUnknown,
)
from backend.metadata.sources.store import SourceRecord, get_source_store

_EVIDENCE_AUDIT_MAX = 500

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


def _build_semantic_kwargs(
    *,
    data: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """Build store kwargs from request data; JSON null does not wipe."""
    kwargs: dict[str, Any] = {}
    for key in fields:
        if key not in data:
            continue
        value = data[key]
        if value is None:
            continue
        kwargs[key] = value
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
        from backend.metadata.errors import SourceNotFound

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
    if "business_domain_code" in resolved and resolved["business_domain_code"] is not None:
        domain = require_domain_by_code(str(resolved["business_domain_code"]))
        resolved["business_domain_id"] = domain.id
    kwargs = _build_semantic_kwargs(data=resolved, fields=_OBJECT_SEMANTIC_FIELDS)
    if not kwargs:
        return existing
    if "business_primary_key" in kwargs:
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
            "semantic_source": semantic_source,
            "ignored_null": [
                k
                for k in (*_OBJECT_SEMANTIC_FIELDS, "business_domain_code")
                if k in data and data[k] is None
            ],
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
            "semantic_source": semantic_source,
            "ignored_null": [
                k for k in _COLUMN_SEMANTIC_FIELDS if k in data and data[k] is None
            ],
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


def list_joins(object_id: str) -> list[CatalogJoinRecord]:
    require_object(object_id)
    return get_catalog_store().list_joins_for_object(object_id)


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
    record = get_catalog_store().upsert_join(
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
