"""Catalog semantics and join domain service (HTTP + MCP shared)."""

from __future__ import annotations

from typing import Any

from backend.admin.audit import persist_audit_event
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
    JoinCrossSource,
    JoinEvidenceRequired,
    JoinInvalid,
)

_EVIDENCE_AUDIT_MAX = 500


def _apply_patch_fields(
    data: dict[str, Any],
) -> tuple[Any, Any]:
    """Map request fields to store Unset/value; explicit null is ignored (no wipe)."""
    business_name: Any = UNSET
    business_description: Any = UNSET
    if "business_name" in data and data["business_name"] is not None:
        business_name = data["business_name"]
    if "business_description" in data and data["business_description"] is not None:
        business_description = data["business_description"]
    return business_name, business_description


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


def get_object_semantics(object_id: str) -> CatalogObjectRecord:
    return require_object(object_id)


def patch_object_semantics(
    *,
    object_id: str,
    data: dict[str, Any],
    actor_user_id: str | None,
    actor_token_id: str | None,
    open_questions: str | None = None,
) -> CatalogObjectRecord:
    require_object(object_id)
    business_name, business_description = _apply_patch_fields(data)
    updated = get_catalog_store().patch_object_semantics(
        object_id,
        business_name=business_name,
        business_description=business_description,
    )
    assert updated is not None
    detail: dict[str, Any] = {
        "changed": [k for k in ("business_name", "business_description") if k in data and data[k] is not None],
        "ignored_null": [k for k in ("business_name", "business_description") if k in data and data[k] is None],
    }
    if open_questions is not None:
        detail["open_questions"] = open_questions
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_object",
        resource_id=object_id,
        action="semantics.object_patch",
        result="success",
        detail=detail,
    )
    return updated


def patch_column_semantics(
    *,
    column_id: str,
    data: dict[str, Any],
    actor_user_id: str | None,
    actor_token_id: str | None,
    open_questions: str | None = None,
) -> CatalogColumnRecord:
    require_column(column_id)
    business_name, business_description = _apply_patch_fields(data)
    updated = get_catalog_store().patch_column_semantics(
        column_id,
        business_name=business_name,
        business_description=business_description,
    )
    assert updated is not None
    detail: dict[str, Any] = {
        "object_id": updated.object_id,
        "changed": [k for k in ("business_name", "business_description") if k in data and data[k] is not None],
        "ignored_null": [k for k in ("business_name", "business_description") if k in data and data[k] is None],
    }
    if open_questions is not None:
        detail["open_questions"] = open_questions
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="catalog_column",
        resource_id=column_id,
        action="semantics.column_patch",
        result="success",
        detail=detail,
    )
    return updated


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
    record = get_catalog_store().upsert_join(
        from_column_id=from_column_id,
        to_column_id=to_column_id,
        evidence=cleaned,
        created_by_user_id=actor_user_id,
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
        },
    )
    return record


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
