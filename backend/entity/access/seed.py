"""First-publish creator grant and the shared profile helpers.

The upgrade seed is Alembic ``0054_entity_access_seed`` (plain SQL on the migration
connection). Profile views are not created here; startup reconciliation enqueues
``entity_access_views``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from backend.core.time import utc_now
from backend.entity.access.records import GrantRecord, ProfileRecord
from backend.entity.access.store import get_access_store
from backend.entity.ids import new_access_grant_id, new_access_profile_id
from backend.entity.records import AttributeRecord

__all__ = [
    "ALL_CLEAR_KEY",
    "CREATOR_ACTIONS",
    "ensure_creator_grant",
]

ALL_CLEAR_KEY = "all_clear"
CREATOR_ACTIONS = ["read", "export", "write"]


def ensure_creator_grant(
    entity_id: str, user_id: str, attributes: list[AttributeRecord]
) -> str | None:
    """First publish: all rows, full-clear profile, read/export/write for that user."""
    if not user_id or not attributes:
        return None
    now = utc_now()
    store = get_access_store()
    profile = _ensure_profile(entity_id, attributes, now)
    wanted = _clear_columns(attributes)
    if profile.columns != wanted:
        # A failed first publish left this profile on attribute ids the retry re-mints.
        profile = replace(profile, columns=wanted, updated_at=now)
        store.update_profile(profile)
        store.set_revision(entity_id, store.revision(entity_id) + 1)
    if _grant_exists(entity_id, "user", user_id, profile.id):
        return None
    grant_id = new_access_grant_id()
    store.insert_grant(
        GrantRecord(
            id=grant_id,
            entity_id=entity_id,
            subject_type="user",
            subject_id=user_id,
            profile_id=profile.id,
            row_rule=None,
            actions=list(CREATOR_ACTIONS),
            status="active",
            valid_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    store.set_revision(entity_id, store.revision(entity_id) + 1)
    return grant_id


def _ensure_profile(
    entity_id: str, attributes: list[AttributeRecord], now: datetime
) -> ProfileRecord:
    store = get_access_store()
    existing = store.profile_by_key(entity_id, ALL_CLEAR_KEY)
    if existing is not None:
        return existing
    columns = _clear_columns(attributes)
    record = ProfileRecord(
        id=new_access_profile_id(),
        entity_id=entity_id,
        key=ALL_CLEAR_KEY,
        name="All clear",
        description=None,
        columns=columns,
        created_at=now,
        updated_at=now,
    )
    store.insert_profile(record)
    return record


def _clear_columns(attributes: list[AttributeRecord]) -> list[dict[str, str]]:
    return [
        {"attribute_id": attr.attribute_id, "level": "clear"}
        for attr in attributes
        if attr.attribute_id
    ]


def _grant_exists(entity_id: str, kind: str, subject_id: str, profile_id: str) -> bool:
    return any(
        item.entity_id == entity_id
        and item.subject_type == kind
        and item.subject_id == subject_id
        and item.profile_id == profile_id
        for item in get_access_store().grants(entity_id)
    )
