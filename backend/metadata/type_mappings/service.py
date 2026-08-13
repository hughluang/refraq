"""Type Mapping domain service (HTTP + structure Job shared)."""

from __future__ import annotations

from dataclasses import replace

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.metadata.catalog.normalized_type import (
    PATCHABLE_NORMALIZED_TYPES,
    canonicalize_native_type,
)
from backend.metadata.catalog.records import CatalogObjectRecord
from backend.metadata.errors import (
    TypeMappingNotFound,
    TypeMappingSeedImmutable,
    TypeMappingUnknownForbidden,
)
from backend.metadata.type_mappings.store import (
    TypeMappingRecord,
    get_type_mapping_store,
    new_type_mapping_id,
)

__all__ = [
    "assign_normalized_types",
    "list_mappings",
    "patch_mapping",
    "require_mapping",
    "resolve_normalized_type",
]


def require_mapping(mapping_id: str) -> TypeMappingRecord:
    record = get_type_mapping_store().get(mapping_id)
    if record is None:
        raise TypeMappingNotFound()
    return record


def list_mappings(
    *,
    q: str | None = None,
    engine: str | None = None,
    origin: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[TypeMappingRecord], int]:
    return get_type_mapping_store().list_mappings(
        q=q, engine=engine, origin=origin, limit=limit, offset=offset
    )


def resolve_normalized_type(*, engine: str, data_type: str) -> str:
    """Look up or insert Type Mapping; never overwrites an existing row."""
    cleaned_engine = (engine or "").strip()
    if not cleaned_engine:
        raise ValueError("engine is required to resolve Normalized Type")
    canonical = canonicalize_native_type(data_type)
    if not canonical:
        return "unknown"
    store = get_type_mapping_store()
    existing = store.get_by_key(cleaned_engine, canonical)
    if existing is not None:
        return existing.normalized_type
    now = utc_now()
    inserted = store.insert_if_absent(
        TypeMappingRecord(
            id=new_type_mapping_id(),
            engine=cleaned_engine,
            native_type=canonical,
            normalized_type="unknown",
            origin="job",
            created_at=now,
            updated_at=now,
        )
    )
    return inserted.normalized_type


def assign_normalized_types(
    objects: list[CatalogObjectRecord], *, engine: str
) -> list[CatalogObjectRecord]:
    """Set each column's Normalized Type snapshot. Merge stays a pure function."""
    out: list[CatalogObjectRecord] = []
    for obj in objects:
        cols = [
            replace(
                col,
                normalized_type=resolve_normalized_type(
                    engine=engine, data_type=col.data_type
                ),
            )
            for col in obj.columns
        ]
        out.append(replace(obj, columns=cols))
    return out


def patch_mapping(
    *,
    mapping_id: str,
    normalized_type: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> TypeMappingRecord:
    existing = require_mapping(mapping_id)
    if existing.origin == "product":
        raise TypeMappingSeedImmutable()
    target = (normalized_type or "").strip()
    if target not in PATCHABLE_NORMALIZED_TYPES:
        raise TypeMappingUnknownForbidden()
    if target == existing.normalized_type and existing.origin == "user":
        return existing
    updated = get_type_mapping_store().save(
        TypeMappingRecord(
            id=existing.id,
            engine=existing.engine,
            native_type=existing.native_type,
            normalized_type=target,
            origin="user",
            created_at=existing.created_at,
            updated_at=utc_now(),
        )
    )
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="type_mapping",
        resource_id=mapping_id,
        action="type_mapping.patch",
        result="success",
        detail={
            "engine": updated.engine,
            "native_type": updated.native_type,
            "normalized_type": updated.normalized_type,
        },
    )
    return updated
