"""Resolve reference attributes against the target Business Key."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.entity.errors import EntityAttributeInvalid, EntityReferenced
from backend.entity.inbound import inbound_references_for
from backend.entity.lifecycle import latest_published_of
from backend.entity.records import AttributeRecord
from backend.entity.store import EntityStore
from backend.entity.table_name import table_present

__all__ = [
    "bind_reference_publish",
    "business_key_attr",
    "freeze_reference_bindings",
    "frozen_reference_bindings_cover",
    "require_business_key_stable",
]


def business_key_attr(
    attributes: list[AttributeRecord] | tuple[AttributeRecord, ...],
) -> AttributeRecord | None:
    marked = [attr for attr in attributes if attr.business_key]
    if not marked:
        return None
    return marked[0]


def _business_key_signature(
    attributes: list[AttributeRecord] | tuple[AttributeRecord, ...],
) -> tuple[str, str, int | None] | None:
    attr = business_key_attr(attributes)
    if attr is None:
        return None
    length = attr.max_length if attr.type == "string" else None
    return (attr.name, attr.type, length)


def require_business_key_stable(
    store: EntityStore,
    entity_id: str,
    before: list[AttributeRecord] | tuple[AttributeRecord, ...],
    after: list[AttributeRecord] | tuple[AttributeRecord, ...],
) -> None:
    """Refuse a Business Key change while a reference binding still serves."""
    if _business_key_signature(before) == _business_key_signature(after):
        return
    bound = _bound_references(store, entity_id, replacing=after)
    if not bound:
        return
    listed = ", ".join(
        f"{item['table_name']}.{item['attribute_name']}" for item in bound
    )
    raise EntityReferenced(
        "Business Key cannot change while a reference binding exists: " + listed
    )


def _bound_references(
    store: EntityStore,
    target_id: str,
    *,
    replacing: list[AttributeRecord] | tuple[AttributeRecord, ...],
) -> list[dict[str, str]]:
    """Current-version references, plus other entities' serving heads.

    ``replacing`` is the shape being saved for ``target_id``. That entity's
    stored current version is not a binding this write would leave behind, and
    its own serving head retires on the successor publish.
    """
    found: dict[tuple[str, str], dict[str, str]] = {}
    for item in _current_references(store, target_id, replacing=replacing):
        found[(item["table_name"], item["attribute_name"])] = item
    for entity in store.list_all_entities():
        if entity.id == target_id:
            continue
        head = latest_published_of(store.list_all_versions(entity.id))
        if head is None or not table_present(head):
            continue
        for attr in head.attributes:
            if attr.type != "reference" or attr.target_entity_id != target_id:
                continue
            if attr.name not in head.reference_snapshots:
                continue
            found[(entity.table_name, attr.name)] = {
                "entity_id": entity.id,
                "table_name": entity.table_name,
                "attribute_name": attr.name,
            }
    return sorted(
        found.values(),
        key=lambda item: (item["table_name"], item["attribute_name"]),
    )


def _current_references(
    store: EntityStore,
    target_id: str,
    *,
    replacing: list[AttributeRecord] | tuple[AttributeRecord, ...],
) -> list[dict[str, str]]:
    """Inbound references, with ``target_id`` judged by the shape being saved."""
    others = [
        item
        for item in inbound_references_for(store, target_id)
        if item["entity_id"] != target_id
    ]
    entity = store.get_entity(target_id)
    if entity is None:
        return others
    for attr in replacing:
        if attr.type != "reference" or attr.target_entity_id != target_id:
            continue
        others.append(
            {
                "entity_id": entity.id,
                "table_name": entity.table_name,
                "attribute_name": attr.name,
            }
        )
    others.sort(key=lambda item: (item["table_name"], item["attribute_name"]))
    return others


def freeze_reference_bindings(
    store: EntityStore,
    attributes: list[AttributeRecord],
    *,
    entity_id: str,
) -> dict[str, Any]:
    """Target Business Key captured once at publish acceptance."""
    bindings: dict[str, Any] = {}
    for attr in attributes:
        if attr.type != "reference":
            continue
        key = _target_business_key(
            store, attr, attributes=attributes, entity_id=entity_id
        )
        entry: dict[str, Any] = {"attribute": key.name, "type": key.type}
        if key.type == "string":
            entry["max_length"] = key.max_length
        bindings[attr.name] = entry
    return bindings


def frozen_reference_bindings_cover(
    attributes: list[AttributeRecord],
    raw: object,
) -> dict[str, Any] | None:
    """Return the frozen document when it names every reference attribute."""
    if not isinstance(raw, dict):
        return None
    for attr in attributes:
        if attr.type != "reference":
            continue
        if not _binding_entry(raw.get(attr.name)):
            return None
    return raw


def bind_reference_publish(
    store: EntityStore,
    attributes: list[AttributeRecord],
    bindings: dict[str, Any],
    *,
    entity_id: str,
) -> tuple[list[AttributeRecord], dict[str, Any]]:
    """Stamp columns from bindings that still match each target Business Key."""
    mismatches: list[str] = []
    for attr in attributes:
        if attr.type != "reference":
            continue
        frozen = bindings[attr.name]
        live = _target_business_key(
            store, attr, attributes=attributes, entity_id=entity_id
        )
        if not _matches(frozen, live):
            mismatches.append(attr.name)
    if mismatches:
        listed = ", ".join(mismatches)
        raise EntityAttributeInvalid(
            "Business Key changed after publish was accepted: " + listed
        )
    snapshots = {name: dict(entry) for name, entry in bindings.items()}
    return _stamp_reference_columns(attributes, snapshots), snapshots


def _stamp_reference_columns(
    attributes: list[AttributeRecord],
    snapshots: dict[str, Any],
) -> list[AttributeRecord]:
    stamped: list[AttributeRecord] = []
    for attr in attributes:
        if attr.type != "reference":
            stamped.append(attr)
            continue
        snap = snapshots[attr.name]
        stamped.append(
            replace(
                attr,
                reference_key_type=str(snap["type"]),
                reference_max_length=snap.get("max_length"),
            )
        )
    return stamped


def _target_business_key(
    store: EntityStore,
    attr: AttributeRecord,
    *,
    attributes: list[AttributeRecord],
    entity_id: str,
) -> AttributeRecord:
    target_id = (attr.target_entity_id or "").strip()
    if not target_id:
        raise EntityAttributeInvalid(
            f"Attribute '{attr.name}' of type reference requires target_entity_id"
        )
    if target_id == entity_id:
        target_attributes: list[AttributeRecord] | tuple[AttributeRecord, ...] = (
            attributes
        )
    else:
        current = store.current_version(target_id)
        if current is None:
            raise EntityAttributeInvalid(
                f"Attribute '{attr.name}' target has no version"
            )
        target_attributes = current.attributes
    key = business_key_attr(target_attributes)
    if key is None:
        raise EntityAttributeInvalid(
            f"Attribute '{attr.name}' target has no business_key"
        )
    return key


def _binding_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    key_type = entry.get("type")
    if not isinstance(entry.get("attribute"), str) or not entry["attribute"]:
        return False
    if key_type == "integer":
        return True
    if key_type == "string":
        length = entry.get("max_length")
        return isinstance(length, int) and not isinstance(length, bool) and length >= 1
    return False


def _matches(frozen: dict[str, Any], live: AttributeRecord) -> bool:
    if frozen.get("attribute") != live.name or frozen.get("type") != live.type:
        return False
    if live.type == "string":
        return frozen.get("max_length") == live.max_length
    return True
