"""Published read port: a Business Entity's current head shape.

Data Channel validates write and read nodes against this shape. It does not
import Entity stores or version records.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.entity.lifecycle import latest_published_of
from backend.entity.store import get_entity_store
from backend.entity.table_name import published_attributes

__all__ = [
    "EntityHeadShape",
    "HeadAttribute",
    "get_entity_head",
]


@dataclass(frozen=True, slots=True)
class HeadAttribute:
    name: str
    unique: bool
    business_key: bool


@dataclass(frozen=True, slots=True)
class EntityHeadShape:
    attributes: tuple[HeadAttribute, ...]


def get_entity_head(entity_id: str) -> EntityHeadShape | None:
    """Return the latest published head, or None when the entity has no head."""
    store = get_entity_store()
    if store.get_entity(entity_id) is None:
        return None
    version = latest_published_of(store.list_all_versions(entity_id))
    if version is None:
        return None
    attributes = tuple(
        HeadAttribute(
            name=attr.name,
            unique=bool(attr.unique),
            business_key=bool(attr.business_key),
        )
        for attr in published_attributes(version)
    )
    return EntityHeadShape(attributes=attributes)
