"""Join edge list and writes (HTTP + MCP)."""

from __future__ import annotations

from typing import Any

from backend.admin.audit import persist_audit_event
from backend.metadata.catalog.join_origin import resolve_join_write
from backend.metadata.catalog.refs import require_column, require_join
from backend.metadata.catalog.store import (
    CatalogJoinRecord,
    get_catalog_store,
    require_object,
)
from backend.metadata.catalog.views import JoinView, join_view
from backend.metadata.errors import (
    CatalogJoinNotFound,
    JoinCrossSource,
    JoinEvidenceRequired,
    JoinInvalid,
)

_EVIDENCE_AUDIT_MAX = 500


def list_joins(
    object_id: str, *, limit: int | None = None, offset: int = 0
) -> tuple[list[JoinView], int]:
    require_object(object_id)
    records, total = get_catalog_store().list_joins_for_object(
        object_id, limit=limit, offset=offset
    )
    return [join_view(j) for j in records], total


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
        existing = store.get_join_by_pair(from_id, to_id)
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
