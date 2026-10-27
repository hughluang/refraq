"""Short Entity rows for the Tag subject page.

Visibility is the same rule as the Entity list. Missing ids are omitted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from backend.admin.user_store import UserRecord
from backend.entity.lifecycle import ever_published
from backend.entity.service import _definition
from backend.entity.store import get_entity_store

__all__ = ["EntitySubjectDisplay", "entity_subject_displays"]


@dataclass(frozen=True, slots=True)
class EntitySubjectDisplay:
    id: str
    name: str
    table_name: str
    deprecated_at: datetime | None
    ever_published: bool


def entity_subject_displays(
    user: UserRecord, entity_ids: Sequence[str]
) -> list[EntitySubjectDisplay]:
    store = get_entity_store()
    found: list[EntitySubjectDisplay] = []
    for entity_id in entity_ids:
        entity = store.get_entity(entity_id)
        if entity is None:
            continue
        visible, _physical, _names = _definition(user, entity.id)
        if not visible:
            continue
        versions = store.list_all_versions(entity.id)
        found.append(
            EntitySubjectDisplay(
                id=entity.id,
                name=entity.name,
                table_name=entity.table_name,
                deprecated_at=entity.deprecated_at,
                ever_published=ever_published(versions),
            )
        )
    return found
