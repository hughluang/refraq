"""Resolve a serving head target by Entity table_name."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from backend.entity.ddl import qualified_table
from backend.entity.entity_db import entity_db_schema
from backend.entity.errors import (
    EntityDeprecated,
    EntityNotFound,
    EntityNotServing,
    EntityPublishing,
)
from backend.entity.lifecycle import PUBLISHING, is_deprecated, latest_published_of
from backend.entity.present import physical_table_name, table_present
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_from_dict,
)
from backend.entity.store import get_entity_store

__all__ = [
    "HeadTarget",
    "resolve_head",
]


@dataclass(frozen=True, slots=True)
class HeadTarget:
    entity: BusinessEntityRecord
    head: EntityVersionRecord
    attributes: tuple[AttributeRecord, ...]
    physical_table: str
    qualified_table: str
    writable: bool


def resolve_head(table_name: str, *, for_write: bool) -> HeadTarget:
    store = get_entity_store()
    entity = store.get_entity_by_table_name(table_name)
    if entity is None:
        raise EntityNotFound(
            f"Business Entity with table_name '{table_name}' was not found"
        )
    if is_deprecated(entity):
        raise EntityDeprecated()
    versions = store.list_all_versions(entity.id)
    publishing = any(item.publish_status == PUBLISHING for item in versions)
    if for_write and publishing:
        raise EntityPublishing()
    head = latest_published_of(versions)
    if head is None or not table_present(head):
        raise EntityNotServing()
    physical = cast(str, physical_table_name(head, entity.table_name))
    attributes = tuple(
        attribute_from_dict(item) for item in head.materialized_attributes
    )
    schema = entity_db_schema()
    return HeadTarget(
        entity=entity,
        head=head,
        attributes=attributes,
        physical_table=physical,
        qualified_table=qualified_table(schema, physical),
        writable=not publishing,
    )
