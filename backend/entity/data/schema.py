"""Assemble Entity Data API schema responses (metadata only)."""

from __future__ import annotations

from typing import Any

from backend.entity.attribute_type import resolve
from backend.entity.data.capabilities import (
    FILTER_DEPTH_MAX,
    FILTER_IN_VALUES_MAX,
    FILTER_LEAVES_MAX,
    OFFSET_MAX,
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    ROW_WRITE_LIMIT,
    upsert_key_for,
)
from backend.entity.data.head import HeadTarget
from backend.entity.data.values import reference_value_attr
from backend.entity.dictionaries.store import get_dictionary_store
from backend.entity.records import AttributeRecord, attribute_to_dict
from backend.entity.reference_binding import business_key_attr
from backend.entity.store import EntityStore, get_entity_store

__all__ = ["build_schema"]


def build_schema(target: HeadTarget) -> dict[str, Any]:
    store = get_entity_store()
    attributes = [
        _attribute_out(store, attr, target) for attr in target.attributes
    ]
    key = business_key_attr(target.attributes)
    return {
        "entity": {
            "id": target.entity.id,
            "table_name": target.entity.table_name,
            "name": target.entity.name,
            "description": target.entity.description,
            "writable": target.writable,
        },
        "head": {
            "version_id": target.head.id,
            "version": target.head.version,
        },
        "row_id": {
            "type": "integer",
            "operators": list(resolve("integer").operators),
        },
        "business_key": key.name if key is not None else None,
        "attributes": attributes,
        "limits": {
            "page_limit_default": PAGE_LIMIT_DEFAULT,
            "page_limit_max": PAGE_LIMIT_MAX,
            "offset_max": OFFSET_MAX,
            "filter_leaves_max": FILTER_LEAVES_MAX,
            "filter_depth_max": FILTER_DEPTH_MAX,
            "filter_in_values_max": FILTER_IN_VALUES_MAX,
            "row_write_max": ROW_WRITE_LIMIT,
        },
    }


def _attribute_out(
    store: EntityStore, attr: AttributeRecord, target: HeadTarget
) -> dict[str, Any]:
    payload = attribute_to_dict(attr)
    spec = resolve(attr.type)
    payload["operators"] = _operators(attr, target)
    payload["upsert_key"] = upsert_key_for(attr)
    if "target" in spec.reads:
        payload["target"] = _reference_target(store, attr.target_entity_id)
    if "dictionary" in spec.reads:
        payload["dictionary"] = _dictionary_link(attr)
        payload["codes"] = _codes_for(attr, target)
    return payload


def _operators(attr: AttributeRecord, target: HeadTarget) -> list[str]:
    if attr.type == "reference":
        return list(resolve(reference_value_attr(attr, target).type).operators)
    return list(resolve(attr.type).operators)


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


def _dictionary_link(attr: AttributeRecord) -> dict[str, Any] | None:
    found = get_dictionary_store().get(attr.dictionary_id or "")
    if found is None:
        return None
    return {
        "id": found.id,
        "name": found.name,
        "display_name": found.display_name,
        "deprecated": found.deprecated_at is not None,
    }


def _codes_for(attr: AttributeRecord, target: HeadTarget) -> list[dict[str, Any]]:
    snapshot = target.head.dictionary_snapshots.get(attr.name)
    if not isinstance(snapshot, dict):
        return []
    snap_codes = [str(code) for code in (snapshot.get("codes") or [])]
    active: set[str] = set()
    labels: dict[str, str | None] = {}
    found = get_dictionary_store().get(attr.dictionary_id or "")
    if found is not None:
        for entry in found.entries:
            labels[entry.code] = entry.label
            if entry.active:
                active.add(entry.code)
    return [
        {
            "code": code,
            "label": labels.get(code),
            "writable": code in active,
        }
        for code in snap_codes
    ]
