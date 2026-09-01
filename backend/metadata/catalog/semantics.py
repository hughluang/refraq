"""Object Semantics writes (HTTP + MCP)."""

from __future__ import annotations

from typing import Any

from backend.admin.audit import persist_audit_event
from backend.metadata.business_domains.service import require_domain_by_code
from backend.metadata.catalog.refs import require_column
from backend.metadata.catalog.store import (
    CatalogColumnRecord,
    CatalogObjectRecord,
    UNSET,
    get_catalog_store,
    require_object,
)
from backend.metadata.errors import SemanticColumnUnknown

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
