"""Inbound References: current-version Entity References aimed at one entity."""

from __future__ import annotations

from backend.entity.store import EntityStore

__all__ = ["inbound_references_for"]


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
