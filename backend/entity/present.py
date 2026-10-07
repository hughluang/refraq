"""Project Business Entity records into contract shapes."""

from __future__ import annotations

from typing import Any

from backend.entity.attribute_type import resolve
from backend.entity.data.values import user_display_labels
from backend.entity.dictionaries.store import get_dictionary_store
from backend.entity.dictionary_binding import relevant_snapshot
from backend.entity.lifecycle import PUBLISHED, ever_published, latest_published_of
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.reference_binding import business_key_attr
from backend.entity.store import EntityStore, get_entity_store

__all__ = [
    "entity_out",
    "present_user_value",
    "version_out",
]


def present_user_value(user_id: str | None) -> dict[str, str] | None:
    """Display surface for one stored User id.

    A missing or disabled-then-deleted User keeps the id and omits the names.
    """
    if not user_id:
        return None
    found = user_display_labels([user_id]).get(user_id)
    if found is None:
        return {"id": user_id}
    return {"id": user_id, **found}


def attribute_payload(
    store: EntityStore,
    attr: AttributeRecord,
    *,
    version: EntityVersionRecord | None = None,
    attribute_id: str | None = None,
) -> dict[str, Any]:
    """Stored attribute shape, plus read-only reference and dictionary fields."""
    payload = attribute_to_dict(attr)
    payload["attribute_id"] = attribute_id
    reads = resolve(attr.type).reads
    if "target" in reads:
        payload["target"] = _reference_target(store, attr.target_entity_id)
        payload["reference_snapshot"] = _reference_snapshot(version, attr.name)
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


def _reference_snapshot(
    version: EntityVersionRecord | None, name: str
) -> dict[str, Any] | None:
    if version is None:
        return None
    snap = version.reference_snapshots.get(name)
    if not isinstance(snap, dict):
        return None
    frozen: dict[str, Any] = {
        "attribute": snap.get("attribute"),
        "type": snap.get("type"),
    }
    if "max_length" in snap:
        frozen["max_length"] = snap["max_length"]
    return frozen


def _reference_target(
    store: EntityStore, entity_id: str | None
) -> dict[str, str | None] | None:
    if not entity_id:
        return None
    entity = store.get_entity(entity_id)
    if entity is None:
        return None
    current = store.current_version(entity.id)
    key_name: str | None = None
    if current is not None:
        key = business_key_attr(current.attributes)
        if key is not None:
            key_name = key.name
    return {
        "entity_id": entity.id,
        "name": entity.name,
        "table_name": entity.table_name,
        "business_key": key_name,
    }


def _attribute_ids(
    store: EntityStore, version: EntityVersionRecord
) -> dict[str, str]:
    """Published versions report their stored ids; drafts borrow the head's by name."""
    if version.publish_status == PUBLISHED:
        source: list[AttributeRecord] = version.attributes
    else:
        latest = latest_published_of(store.list_all_versions(version.entity_id))
        source = latest.attributes if latest is not None else []
    return {
        attr.name: attr.attribute_id
        for attr in source
        if attr.attribute_id is not None
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
    attribute_names: frozenset[str] | None = None,
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
    shown = version.attributes
    if attribute_names is not None:
        shown = [attr for attr in version.attributes if attr.name in attribute_names]
    if include_attributes:
        store = get_entity_store()
        ids = _attribute_ids(store, version)
        payload["attributes"] = [
            attribute_payload(
                store, attr, version=version, attribute_id=ids.get(attr.name)
            )
            for attr in shown
        ]
    else:
        payload["attribute_count"] = len(shown)
    return payload
