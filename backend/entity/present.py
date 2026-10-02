"""Project Business Entity records into contract shapes."""

from __future__ import annotations

from typing import Any

from backend.entity.attribute_type import resolve
from backend.entity.dictionaries.store import get_dictionary_store
from backend.entity.dictionary_binding import relevant_snapshot
from backend.entity.lifecycle import ever_published
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import EntityStore, get_entity_store

__all__ = [
    "entity_out",
    "version_out",
]


def attribute_payload(
    store: EntityStore,
    attr: AttributeRecord,
    *,
    version: EntityVersionRecord | None = None,
) -> dict[str, Any]:
    """Stored attribute shape, plus read-only reference and dictionary fields."""
    payload = attribute_to_dict(attr)
    reads = resolve(attr.type).reads
    if "target" in reads:
        payload["target"] = _reference_target(store, attr.target_entity_id)
    if "dictionary" in reads:
        payload.update(_dictionary_read(store, attr, version))
    return payload


def _dictionary_read(
    store: EntityStore,
    attr: AttributeRecord,
    version: EntityVersionRecord | None,
) -> dict[str, Any]:
    linked = None
    revision: int | None = None
    found = get_dictionary_store().get(attr.dictionary_id or "")
    if found is not None:
        linked = {
            "id": found.id,
            "name": found.name,
            "display_name": found.display_name,
            "deprecated": found.deprecated_at is not None,
        }
        revision = found.revision
    behind = False
    if version is not None and revision is not None and attr.dictionary_id:
        versions = store.list_all_versions(version.entity_id)
        snapshot = relevant_snapshot(
            versions, version, attr.name, attr.dictionary_id
        )
        if snapshot is not None:
            behind = int(snapshot.get("revision") or 0) < revision
    return {"dictionary": linked, "behind": behind}


def _reference_target(
    store: EntityStore, entity_id: str | None
) -> dict[str, str] | None:
    if not entity_id:
        return None
    entity = store.get_entity(entity_id)
    if entity is None:
        return None
    return {
        "entity_id": entity.id,
        "name": entity.name,
        "table_name": entity.table_name,
    }


def entity_out(
    entity: BusinessEntityRecord,
    *,
    current: EntityVersionRecord | None,
    physical_table: str | None,
    alignment: dict[str, Any] | None,
    inbound_references: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    store = get_entity_store()
    versions = store.list_all_versions(entity.id)
    current_payload: dict[str, Any] | None = None
    if current is not None:
        current_payload = {
            "id": current.id,
            "version": current.version,
            "publish_status": current.publish_status,
            "table_name": physical_table,
            "alignment": alignment,
        }
    payload: dict[str, Any] = {
        "id": entity.id,
        "table_name": entity.table_name,
        "name": entity.name,
        "description": entity.description,
        "deprecated_at": entity.deprecated_at,
        "ever_published": ever_published(versions),
        "current_version": current_payload,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }
    if inbound_references is not None:
        payload["inbound_references"] = inbound_references
    return payload


def version_out(
    version: EntityVersionRecord,
    *,
    entity: BusinessEntityRecord,
    include_attributes: bool,
    physical_table: str | None,
    alignment: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": version.id,
        "entity_id": entity.id,
        "version": version.version,
        "publish_status": version.publish_status,
        "table_name": physical_table,
        "alignment": alignment,
        "created_at": version.created_at,
        "updated_at": version.updated_at,
    }
    if include_attributes:
        store = get_entity_store()
        payload["attributes"] = [
            attribute_payload(store, attr, version=version)
            for attr in version.attributes
        ]
    else:
        payload["attribute_count"] = len(version.attributes)
    return payload
