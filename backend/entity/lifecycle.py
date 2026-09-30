"""Stored publish and deprecate constants for Business Entity."""

from __future__ import annotations

from typing import Literal

from backend.entity.records import BusinessEntityRecord, EntityVersionRecord

UNPUBLISHED = "unpublished"
PUBLISHING = "publishing"
PUBLISHED = "published"

EntityListStatus = Literal["not_serving", "serving", "deprecated"]

ENTITY_LIST_STATUSES: frozenset[EntityListStatus] = frozenset(
    {"not_serving", "serving", "deprecated"}
)


def is_deprecated(entity: BusinessEntityRecord) -> bool:
    return entity.deprecated_at is not None


def any_publishing(versions: list[EntityVersionRecord]) -> bool:
    return any(item.publish_status == PUBLISHING for item in versions)


def ever_published(versions: list[EntityVersionRecord]) -> bool:
    return any(item.publish_status == PUBLISHED for item in versions)


def latest_published_of(
    versions: list[EntityVersionRecord],
) -> EntityVersionRecord | None:
    published = [item for item in versions if item.publish_status == PUBLISHED]
    if not published:
        return None
    return max(published, key=lambda item: (item.version, item.id))


def entity_list_status(
    entity: BusinessEntityRecord, versions: list[EntityVersionRecord]
) -> EntityListStatus:
    """Status the entity list filters on. Deprecated wins over a published version."""
    if entity.deprecated_at is not None:
        return "deprecated"
    if any(item.publish_status == PUBLISHED for item in versions):
        return "serving"
    return "not_serving"


def status_filter_selection(
    statuses: list[EntityListStatus] | None,
) -> frozenset[EntityListStatus] | None:
    """Normalize a list query into a store filter.

    ``None`` and the full set both mean no status predicate. Any other set is
    applied as a union, with duplicates collapsed.
    """
    if statuses is None:
        return None
    selected: frozenset[EntityListStatus] = frozenset(statuses)
    if selected == ENTITY_LIST_STATUSES:
        return None
    return selected
