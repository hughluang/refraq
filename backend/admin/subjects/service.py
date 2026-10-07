"""User Group and Subject Attribute use cases."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.admin.errors import UserNotFound
from backend.admin.subjects.errors import (
    SubjectAttributeInvalid,
    SubjectAttributeNotFound,
    UserGroupInvalid,
    UserGroupNotFound,
)
from backend.admin.subjects.ports import dictionary_codes
from backend.admin.subjects.records import (
    KEY_MAX_LENGTH,
    NAME_MAX_LENGTH,
    STRING_VALUE_MAX_LENGTH,
    VALUE_TYPES,
    VALUES_MAX,
    SubjectAttributeRecord,
    SubjectType,
    SubjectValue,
    UserGroupRecord,
)
from backend.admin.subjects.store import SubjectStore, get_subject_store
from backend.admin.user_store import UserRecord, get_user_store
from backend.core.time import utc_now

__all__ = [
    "Unset",
    "add_member",
    "create_definition",
    "create_group",
    "decode_value",
    "decode_values",
    "delete_definition",
    "delete_group",
    "effective_values_of",
    "list_member_users",
    "own_values_of",
    "patch_definition",
    "patch_group",
    "remove_member",
    "replace_group_values",
    "replace_user_groups",
    "replace_user_values",
    "require_definition",
    "require_group",
    "require_user",
    "user_groups_of",
]

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BIGINT_MIN = -(2**63)
_BIGINT_MAX = 2**63 - 1


class Unset:
    """Marker for a PATCH field the request did not send."""


UNSET = Unset()


def _store() -> SubjectStore:
    return get_subject_store()


def _audit(
    *,
    actor_user_id: str,
    actor_token_id: str | None,
    resource_type: str,
    resource_id: str,
    action: str,
    detail: dict[str, Any] | None = None,
) -> None:
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        result="success",
        detail=detail or {},
    )


def _clean_key(raw: Any, error: type[UserGroupInvalid] | type[SubjectAttributeInvalid]) -> str:
    if not isinstance(raw, str) or not KEY_RE.match(raw) or len(raw) > KEY_MAX_LENGTH:
        raise error(
            "key must start with a lowercase letter, use only a-z, 0-9, and underscore,"
            f" and have at most {KEY_MAX_LENGTH} characters"
        )
    return raw


def _clean_name(raw: Any, error: type[UserGroupInvalid] | type[SubjectAttributeInvalid]) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise error("name is required")
    name = raw.strip()
    if len(name) > NAME_MAX_LENGTH:
        raise error(f"name must have at most {NAME_MAX_LENGTH} characters")
    return name


def _clean_description(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def require_user(user_id: str) -> UserRecord:
    user = get_user_store().get_by_id(user_id)
    if user is None:
        raise UserNotFound()
    return user


def require_group(group_id: str) -> UserGroupRecord:
    group = _store().get_group(group_id)
    if group is None:
        raise UserGroupNotFound()
    return group


def require_definition(definition_id: str) -> SubjectAttributeRecord:
    found = _store().get_definition(definition_id)
    if found is None:
        raise SubjectAttributeNotFound()
    return found


def create_group(
    *,
    key: Any,
    name: Any,
    description: Any,
    actor_user_id: str,
    actor_token_id: str | None,
) -> UserGroupRecord:
    now = utc_now()
    record = UserGroupRecord(
        id=f"grp_{uuid.uuid4().hex[:12]}",
        key=_clean_key(key, UserGroupInvalid),
        name=_clean_name(name, UserGroupInvalid),
        description=_clean_description(description),
        created_at=now,
        updated_at=now,
    )
    _store().create_group(record)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="user_group",
        resource_id=record.id,
        action="create",
        detail={"key": record.key},
    )
    return record


def patch_group(
    group_id: str,
    *,
    key: Any = UNSET,
    name: Any = UNSET,
    description: Any = UNSET,
    actor_user_id: str,
    actor_token_id: str | None,
) -> UserGroupRecord:
    current = require_group(group_id)
    if not isinstance(key, Unset) and key != current.key:
        raise UserGroupInvalid("key is immutable")
    updated = current
    if not isinstance(name, Unset):
        updated = replace(updated, name=_clean_name(name, UserGroupInvalid))
    if not isinstance(description, Unset):
        updated = replace(updated, description=_clean_description(description))
    if updated == current:
        return current
    updated = replace(updated, updated_at=utc_now())
    _store().update_group(updated)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="user_group",
        resource_id=group_id,
        action="update",
    )
    return updated


def delete_group(group_id: str, *, actor_user_id: str, actor_token_id: str | None) -> None:
    group = require_group(group_id)
    _store().delete_group(group_id)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="user_group",
        resource_id=group_id,
        action="delete",
        detail={"key": group.key},
    )


def list_member_users(
    group_id: str, *, limit: int | None, offset: int
) -> tuple[list[UserRecord], int]:
    require_group(group_id)
    ids, total = _store().list_member_ids(group_id, limit=limit, offset=offset)
    users = get_user_store()
    found = [users.get_by_id(user_id) for user_id in ids]
    return [user for user in found if user is not None], total


def add_member(
    group_id: str, user_id: str, *, actor_user_id: str, actor_token_id: str | None
) -> None:
    require_group(group_id)
    require_user(user_id)
    store = _store()
    if group_id in store.group_ids_of(user_id):
        return
    store.add_member(group_id, user_id)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="user_group",
        resource_id=group_id,
        action="member_add",
        detail={"user_id": user_id},
    )


def remove_member(
    group_id: str, user_id: str, *, actor_user_id: str, actor_token_id: str | None
) -> None:
    require_group(group_id)
    store = _store()
    if group_id not in store.group_ids_of(user_id):
        return
    store.remove_member(group_id, user_id)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="user_group",
        resource_id=group_id,
        action="member_remove",
        detail={"user_id": user_id},
    )


def user_groups_of(user_id: str) -> list[UserGroupRecord]:
    store = _store()
    groups = [store.get_group(group_id) for group_id in store.group_ids_of(user_id)]
    return sorted(
        (group for group in groups if group is not None),
        key=lambda group: (group.key, group.id),
    )


def replace_user_groups(
    user_id: str,
    group_ids: list[str],
    *,
    actor_user_id: str,
    actor_token_id: str | None,
) -> list[UserGroupRecord]:
    require_user(user_id)
    store = _store()
    wanted = list(dict.fromkeys(group_ids))
    missing = sorted(set(wanted) - store.existing_group_ids(wanted))
    if missing:
        raise UserGroupInvalid(f"Unknown User Group id(s): {', '.join(missing)}")
    before = sorted(store.group_ids_of(user_id))
    if before != sorted(wanted):
        store.replace_user_groups(user_id, wanted)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="user",
            resource_id=user_id,
            action="groups_replace",
            detail={"before": before, "after": sorted(wanted)},
        )
    return user_groups_of(user_id)


def create_definition(
    *,
    key: Any,
    name: Any,
    description: Any,
    value_type: Any,
    dictionary_id: Any,
    multi_value: Any,
    actor_user_id: str,
    actor_token_id: str | None,
) -> SubjectAttributeRecord:
    if value_type not in VALUE_TYPES:
        raise SubjectAttributeInvalid(
            f"value_type must be one of {', '.join(VALUE_TYPES)}"
        )
    bound: str | None = None
    if value_type == "dictionary":
        if not isinstance(dictionary_id, str) or not dictionary_id.strip():
            raise SubjectAttributeInvalid("dictionary_id is required for dictionary")
        bound = dictionary_id.strip()
        if dictionary_codes().active_codes(bound) is None:
            raise SubjectAttributeInvalid(
                f"dictionary_id '{bound}' does not name a Dictionary"
            )
    elif dictionary_id is not None:
        raise SubjectAttributeInvalid("dictionary_id is only allowed for dictionary")
    if not isinstance(multi_value, bool):
        raise SubjectAttributeInvalid("multi_value must be a boolean")
    now = utc_now()
    record = SubjectAttributeRecord(
        id=f"sad_{uuid.uuid4().hex[:12]}",
        key=_clean_key(key, SubjectAttributeInvalid),
        name=_clean_name(name, SubjectAttributeInvalid),
        description=_clean_description(description),
        value_type=value_type,
        dictionary_id=bound,
        multi_value=multi_value,
        created_at=now,
        updated_at=now,
    )
    _store().create_definition(record)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="subject_attribute",
        resource_id=record.id,
        action="create",
        detail={"key": record.key, "value_type": record.value_type},
    )
    return record


def patch_definition(
    definition_id: str,
    *,
    key: Any = UNSET,
    value_type: Any = UNSET,
    dictionary_id: Any = UNSET,
    name: Any = UNSET,
    description: Any = UNSET,
    multi_value: Any = UNSET,
    actor_user_id: str,
    actor_token_id: str | None,
) -> SubjectAttributeRecord:
    current = require_definition(definition_id)
    for field, sent, stored in (
        ("key", key, current.key),
        ("value_type", value_type, current.value_type),
        ("dictionary_id", dictionary_id, current.dictionary_id),
    ):
        if not isinstance(sent, Unset) and sent != stored:
            raise SubjectAttributeInvalid(f"{field} is immutable")
    updated = current
    if not isinstance(name, Unset):
        updated = replace(updated, name=_clean_name(name, SubjectAttributeInvalid))
    if not isinstance(description, Unset):
        updated = replace(updated, description=_clean_description(description))
    if not isinstance(multi_value, Unset):
        if not isinstance(multi_value, bool):
            raise SubjectAttributeInvalid("multi_value must be a boolean")
        if current.multi_value and not multi_value:
            raise SubjectAttributeInvalid("multi_value cannot change from true to false")
        updated = replace(updated, multi_value=multi_value)
    if updated == current:
        return current
    updated = replace(updated, updated_at=utc_now())
    _store().update_definition(updated)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="subject_attribute",
        resource_id=definition_id,
        action="update",
    )
    return updated


def delete_definition(
    definition_id: str, *, actor_user_id: str, actor_token_id: str | None
) -> None:
    current = require_definition(definition_id)
    _store().delete_definition(definition_id)
    _audit(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="subject_attribute",
        resource_id=definition_id,
        action="delete",
        detail={"key": current.key},
    )


def decode_value(definition: SubjectAttributeRecord, stored: str) -> SubjectValue:
    if definition.value_type == "integer":
        return int(stored)
    return stored


def decode_values(
    stored: Mapping[str, tuple[str, ...]],
    definitions: Mapping[str, SubjectAttributeRecord],
) -> dict[str, list[SubjectValue]]:
    """Stored values keyed by definition id → wire values keyed by attribute key."""
    out: dict[str, list[SubjectValue]] = {}
    for definition_id, items in stored.items():
        definition = definitions.get(definition_id)
        if definition is None or not items:
            continue
        out[definition.key] = [decode_value(definition, item) for item in items]
    return dict(sorted(out.items()))


def _definitions_by_id() -> dict[str, SubjectAttributeRecord]:
    items, _total = _store().list_definitions()
    return {item.id: item for item in items}


def own_values_of(
    subject_type: SubjectType, subject_id: str
) -> dict[str, list[SubjectValue]]:
    stored = _store().values_for(subject_type, [subject_id]).get(subject_id, {})
    return decode_values(stored, _definitions_by_id())


def effective_values_of(user_id: str) -> dict[str, list[SubjectValue]]:
    store = _store()
    definitions = _definitions_by_id()
    merged: dict[str, list[str]] = {}
    sources = [store.values_for("user", [user_id]).get(user_id, {})]
    group_ids = sorted(group.id for group in user_groups_of(user_id))
    group_values = store.values_for("group", group_ids)
    sources.extend(group_values.get(group_id, {}) for group_id in group_ids)
    for stored in sources:
        for definition_id, items in stored.items():
            bucket = merged.setdefault(definition_id, [])
            bucket.extend(item for item in items if item not in bucket)
    return decode_values(
        {key: tuple(items) for key, items in merged.items()}, definitions
    )


def _encode_value(
    definition: SubjectAttributeRecord,
    raw: Any,
    *,
    kept: tuple[str, ...],
    active_codes: frozenset[str] | None,
) -> str:
    key = definition.key
    value_type = definition.value_type
    if value_type == "integer":
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise SubjectAttributeInvalid(f"'{key}' values must be integers")
        if raw < _BIGINT_MIN or raw > _BIGINT_MAX:
            raise SubjectAttributeInvalid(f"'{key}' value is out of 64-bit range")
        return str(raw)
    if not isinstance(raw, str):
        raise SubjectAttributeInvalid(f"'{key}' values must be strings")
    if "\x00" in raw:
        raise SubjectAttributeInvalid(f"'{key}' values must not contain NUL")
    if value_type == "string":
        if len(raw) > STRING_VALUE_MAX_LENGTH:
            raise SubjectAttributeInvalid(
                f"'{key}' values must have at most {STRING_VALUE_MAX_LENGTH} characters"
            )
        return raw
    if value_type == "date":
        try:
            if not _DATE_RE.match(raw):
                raise ValueError(raw)
            date.fromisoformat(raw)
        except ValueError as exc:
            raise SubjectAttributeInvalid(f"'{key}' values must be YYYY-MM-DD") from exc
        return raw
    if value_type == "dictionary":
        if raw in kept:
            return raw
        if active_codes is None or raw not in active_codes:
            raise SubjectAttributeInvalid(
                f"'{key}' value '{raw}' is not an active code of its Dictionary"
            )
        return raw
    if raw in kept:
        return raw
    if get_user_store().get_by_id(raw) is None:
        raise SubjectAttributeInvalid(f"'{key}' value '{raw}' does not name a User")
    return raw


def _encode_values_map(
    raw_values: Any, current: Mapping[str, tuple[str, ...]]
) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw_values, dict):
        raise SubjectAttributeInvalid("values must be an object")
    store = _store()
    encoded: dict[str, tuple[str, ...]] = {}
    for key, raw_list in raw_values.items():
        definition = store.get_definition_by_key(key) if isinstance(key, str) else None
        if definition is None:
            raise SubjectAttributeInvalid(f"Unknown Subject Attribute key '{key}'")
        if not isinstance(raw_list, list) or not raw_list:
            raise SubjectAttributeInvalid(f"'{key}' must be a non-empty list")
        kept = current.get(definition.id, ())
        active_codes = (
            dictionary_codes().active_codes(definition.dictionary_id or "")
            if definition.value_type == "dictionary"
            else None
        )
        items = tuple(
            dict.fromkeys(
                _encode_value(definition, raw, kept=kept, active_codes=active_codes)
                for raw in raw_list
            )
        )
        if len(items) > VALUES_MAX:
            raise SubjectAttributeInvalid(
                f"'{key}' has more than {VALUES_MAX} distinct values"
            )
        if not definition.multi_value and len(items) > 1:
            raise SubjectAttributeInvalid(f"'{key}' is single-valued")
        encoded[definition.id] = items
    return encoded


def _replace_values(
    subject_type: SubjectType,
    subject_id: str,
    raw_values: Any,
    *,
    actor_user_id: str,
    actor_token_id: str | None,
) -> dict[str, list[SubjectValue]]:
    store = _store()
    current = store.values_for(subject_type, [subject_id]).get(subject_id, {})
    encoded = _encode_values_map(raw_values, current)
    if encoded != current:
        store.replace_values(subject_type, subject_id, encoded)
        definitions = _definitions_by_id()
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type=subject_type,
            resource_id=subject_id,
            action="subject_attributes_replace",
            detail={
                "before": decode_values(current, definitions),
                "after": decode_values(encoded, definitions),
            },
        )
    return own_values_of(subject_type, subject_id)


def replace_user_values(
    user_id: str,
    raw_values: Any,
    *,
    actor_user_id: str,
    actor_token_id: str | None,
) -> dict[str, list[SubjectValue]]:
    require_user(user_id)
    return _replace_values(
        "user",
        user_id,
        raw_values,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )


def replace_group_values(
    group_id: str,
    raw_values: Any,
    *,
    actor_user_id: str,
    actor_token_id: str | None,
) -> dict[str, list[SubjectValue]]:
    require_group(group_id)
    return _replace_values(
        "group",
        group_id,
        raw_values,
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
    )
