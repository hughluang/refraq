"""Role entitlement seed and the first-publish creator grant.

The upgrade seed itself is Alembic ``0054_entity_access_seed`` (plain SQL on the
migration connection); ``seed_entity_entitlements`` is the same rule for memory
tests. Profile views are not created here; startup reconciliation enqueues
``entity_access_views``.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime

from backend.admin.roles import SUPER_ADMIN_KEY, effective_permissions
from backend.admin.role_store import get_role_store
from backend.core.time import utc_now
from backend.entity.access.records import GrantRecord, ProfileRecord
from backend.entity.access.store import get_access_store
from backend.entity.access.views import rebuild_entity_views
from backend.entity.ids import new_access_grant_id, new_access_profile_id
from backend.entity.lifecycle import PUBLISHED
from backend.entity.records import AttributeRecord, attribute_from_dict, attribute_to_dict
from backend.entity.store import get_entity_store

__all__ = [
    "ALL_CLEAR_KEY",
    "CREATOR_ACTIONS",
    "ensure_creator_grant",
    "prepare_legacy_entity",
    "seed_entity_entitlements",
]

ALL_CLEAR_KEY = "all_clear"
CREATOR_ACTIONS = ["read", "export", "write"]


def seed_entity_entitlements(entity_id: str) -> bool:
    """all_clear profile and one grant per Role that holds data read or write."""
    attributes = _stamped_attributes(entity_id)
    if not attributes:
        return False
    store = get_access_store()
    now = utc_now()
    profile = _ensure_profile(entity_id, attributes, now)
    inserted = False
    for role, actions in _entitled_roles():
        if _grant_exists(entity_id, "role", role.id, profile.id):
            continue
        store.insert_grant(
            GrantRecord(
                id=new_access_grant_id(),
                entity_id=entity_id,
                subject_type="role",
                subject_id=role.id,
                profile_id=profile.id,
                row_rule=None,
                actions=actions,
                status="active",
                valid_until=None,
                created_at=now,
                updated_at=now,
            )
        )
        inserted = True
    if inserted or store.revision(entity_id) == 0:
        store.set_revision(entity_id, store.revision(entity_id) + (1 if inserted else 0))
    return inserted


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


def prepare_legacy_entity(entity_id: str) -> None:
    """Give entitled Roles their seed grant and mark that Entity's views ready.

    Memory tests use this for Entities created as already published. The startup
    reconciliation job is what production uses after the Alembic seed.
    """
    seed_entity_entitlements(entity_id)
    rebuild_entity_views(entity_id)


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


def _entitled_roles() -> list[tuple[object, list[str]]]:
    roles, _total = get_role_store().list_roles(limit=None)
    found: list[tuple[object, list[str]]] = []
    for role in roles:
        perms = set(effective_permissions(role))
        if role.key == SUPER_ADMIN_KEY:
            perms.update({"entity:data_read", "entity:data_write"})
        if "entity:data_read" not in perms and "entity:data_write" not in perms:
            continue
        actions = ["read"]
        if "entity:data_write" in perms:
            actions.append("write")
        found.append((role, actions))
    return found


def _stamped_attributes(entity_id: str) -> list[AttributeRecord]:
    store = get_entity_store()
    versions = [
        item
        for item in store.list_all_versions(entity_id)
        if item.publish_status == PUBLISHED
    ]
    if not versions:
        return []
    version = max(versions, key=lambda item: item.version)
    raw = version.materialized_attributes or [
        attribute_to_dict(attr) for attr in version.attributes
    ]
    stamped: list[dict] = []
    changed = False
    for item in raw:
        payload = dict(item)
        if not isinstance(payload.get("attribute_id"), str):
            name = str(payload.get("name") or "")
            payload["attribute_id"] = _stable_id(entity_id, name)
            changed = True
        stamped.append(payload)
    attributes = [attribute_from_dict(item) for item in stamped]
    if changed:
        store.save_version(
            replace(
                version,
                attributes=attributes,
                materialized_attributes=stamped,
                updated_at=utc_now(),
            )
        )
    return [attr for attr in attributes if attr.attribute_id]


def _stable_id(entity_id: str, name: str) -> str:
    digest = hashlib.sha256(f"{entity_id}\n{name}".encode()).hexdigest()[:12]
    return f"att_{digest}"
