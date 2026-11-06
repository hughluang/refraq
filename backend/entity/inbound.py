"""Inbound References: Entity References aimed at one entity."""

from __future__ import annotations

from backend.entity.lifecycle import latest_published_of
from backend.entity.store import EntityStore
from backend.entity.table_name import published_attributes

__all__ = ["inbound_references_for", "serving_inbound_references"]


def inbound_references_for(
    store: EntityStore, target_entity_id: str
) -> list[dict[str, str]]:
    """Current-version Entity References aimed at ``target_entity_id``."""
    found: list[dict[str, str]] = []
    for entity in store.list_all_entities():
        current = store.current_version(entity.id)
        if current is None:
            continue
        for attr in current.attributes:
            if attr.type != "reference":
                continue
            if attr.target_entity_id != target_entity_id:
                continue
            found.append(
                {
                    "entity_id": entity.id,
                    "table_name": entity.table_name,
                    "attribute_name": attr.name,
                }
            )
    found.sort(key=lambda item: (item["table_name"], item["attribute_name"]))
    return found


def serving_inbound_references(
    store: EntityStore, target_entity_id: str
) -> list[dict[str, str]]:
    """References aimed at ``target_entity_id`` from each serving head.

    The serving head is the latest published version. An unpublished current
    version does not count. Items carry ``entity_id`` so a caller can apply
    its own visibility cut, plus ``table_name`` and ``attribute``.
    """
    found: list[dict[str, str]] = []
    for entity in store.list_all_entities():
        head = latest_published_of(store.list_all_versions(entity.id))
        if head is None:
            continue
        for attr in published_attributes(head):
            if attr.type != "reference":
                continue
            if attr.target_entity_id != target_entity_id:
                continue
            found.append(
                {
                    "entity_id": entity.id,
                    "table_name": entity.table_name,
                    "attribute": attr.name,
                }
            )
    found.sort(key=lambda item: (item["table_name"], item["attribute"]))
    return found
