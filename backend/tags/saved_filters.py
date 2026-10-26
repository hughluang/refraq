"""Saved Filter use cases. Writes are not audited."""

from __future__ import annotations

from typing import Any

from backend.core.time import utc_now
from backend.tags.errors import (
    SavedFilterNameInvalid,
    SavedFilterNotFound,
    SavedFilterRequestInvalid,
    TagNameInvalid,
)
from backend.tags.ids import new_saved_filter_id
from backend.tags.names import enforce_tag_name
from backend.tags.saved_filter_store import SavedFilterRecord, get_saved_filter_store

__all__ = [
    "create_saved_filter",
    "delete_saved_filter",
    "normalize_saved_query",
    "owned_visible",
    "remember_saved_filter",
    "update_saved_filter",
]

_ENTITY_STATUS = ("not_serving", "serving", "deprecated")
_Q_MAX = 200
_TAG_MAX = 50
_TAG_LEN = 32


def _collapse(values: list[str]) -> list[str]:
    seen: list[str] = []
    for item in values:
        if item not in seen:
            seen.append(item)
    return seen


def normalize_saved_query(list_name: str, query: object) -> dict[str, Any]:
    """Store the list query. Do not execute it. Unknown keys are invalid."""

    if list_name == "entities":
        allowed = {"q", "status", "tag_ids"}
    elif list_name == "channels":
        allowed = {"q", "active", "tag_ids"}
    else:
        raise SavedFilterRequestInvalid()
    if not isinstance(query, dict) or set(query) != allowed:
        raise SavedFilterRequestInvalid()
    q = query["q"]
    if not isinstance(q, str) or len(q) > _Q_MAX:
        raise SavedFilterRequestInvalid()
    tag_ids = _tag_ids(query["tag_ids"])
    if list_name == "entities":
        return {"q": q, "status": _statuses(query["status"]), "tag_ids": tag_ids}
    active = query["active"]
    if active is not None and not isinstance(active, bool):
        raise SavedFilterRequestInvalid()
    return {"q": q, "active": active, "tag_ids": tag_ids}


def _statuses(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SavedFilterRequestInvalid()
    if any(item not in _ENTITY_STATUS for item in value):
        raise SavedFilterRequestInvalid()
    return _collapse(value)


def _tag_ids(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SavedFilterRequestInvalid()
    if any(len(item) > _TAG_LEN for item in value):
        raise SavedFilterRequestInvalid()
    collapsed = _collapse(value)
    if len(collapsed) > _TAG_MAX:
        raise SavedFilterRequestInvalid()
    return collapsed


def _name(value: str) -> tuple[str, str]:
    try:
        return enforce_tag_name(value)
    except TagNameInvalid:
        raise SavedFilterNameInvalid() from None


def owned_visible(
    record: SavedFilterRecord | None, user_id: str
) -> SavedFilterRecord:
    """Another user's id is the same as a missing id."""

    if record is None or record.user_id != user_id:
        raise SavedFilterNotFound()
    return record


def update_saved_filter(
    filter_id: str,
    *,
    user_id: str,
    name: str | None,
    name_set: bool,
    query: object,
    query_set: bool,
) -> SavedFilterRecord:
    current = owned_visible(get_saved_filter_store().get(filter_id), user_id)
    new_name = current.name
    new_key = current.name_key
    new_query = current.query
    if name_set:
        if name is None:
            raise SavedFilterNameInvalid()
        new_name, new_key = _name(name)
    if query_set:
        if query is None:
            raise SavedFilterRequestInvalid()
        new_query = normalize_saved_query(current.list_name, query)
    if (
        new_name == current.name
        and new_key == current.name_key
        and new_query == current.query
    ):
        return current
    return get_saved_filter_store().update(
        SavedFilterRecord(
            id=current.id,
            user_id=current.user_id,
            list_name=current.list_name,
            name=new_name,
            name_key=new_key,
            query=new_query,
            created_at=current.created_at,
            updated_at=utc_now(),
        )
    )


def delete_saved_filter(filter_id: str, *, user_id: str) -> None:
    owned_visible(get_saved_filter_store().get(filter_id), user_id)
    get_saved_filter_store().delete(filter_id)


def remember_saved_filter(
    *,
    user_id: str,
    list_name: str,
    saved_filter_id: str | None,
) -> None:
    if saved_filter_id is None:
        get_saved_filter_store().set_default(user_id, list_name, None)
        return
    record = owned_visible(get_saved_filter_store().get(saved_filter_id), user_id)
    if record.list_name != list_name:
        raise SavedFilterRequestInvalid()
    get_saved_filter_store().set_default(user_id, list_name, record.id)


def create_saved_filter(
    *,
    user_id: str,
    list_name: str,
    name: str,
    query: object,
) -> SavedFilterRecord:
    display, comparison = _name(name)
    stored_query = normalize_saved_query(list_name, query)
    now = utc_now()
    return get_saved_filter_store().create(
        SavedFilterRecord(
            id=new_saved_filter_id(),
            user_id=user_id,
            list_name=list_name,
            name=display,
            name_key=comparison,
            query=stored_query,
            created_at=now,
            updated_at=now,
        )
    )
