"""Tag vocabulary use cases."""

from __future__ import annotations

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.tags.errors import TagNameInvalid, TagNotFound
from backend.tags.ids import new_tag_id
from backend.tags.names import enforce_tag_description, enforce_tag_name
from backend.tags.records import TagRecord
from backend.tags.store import get_tag_store

__all__ = [
    "create_tag",
    "delete_tag",
    "get_tag",
    "update_tag",
]


def get_tag(tag_id: str) -> TagRecord:
    record = get_tag_store().get(tag_id)
    if record is None:
        raise TagNotFound()
    return record


def create_tag(
    *,
    name: str,
    description: str | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> TagRecord:
    display, comparison = enforce_tag_name(name)
    stored_description = enforce_tag_description(description)
    now = utc_now()
    saved = get_tag_store().create(
        TagRecord(
            id=new_tag_id(),
            name=display,
            name_key=comparison,
            description=stored_description,
            created_at=now,
            updated_at=now,
        )
    )
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="tag",
        resource_id=saved.id,
        action="create",
        result="success",
        detail={"name": saved.name},
    )
    return saved


def update_tag(
    tag_id: str,
    *,
    name: str | None,
    name_set: bool,
    description: str | None,
    description_set: bool,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> TagRecord:
    current = get_tag_store().get(tag_id)
    if current is None:
        raise TagNotFound()
    new_name = current.name
    new_key = current.name_key
    new_description = current.description
    if name_set:
        if name is None:
            raise TagNameInvalid()
        new_name, new_key = enforce_tag_name(name)
    if description_set:
        new_description = enforce_tag_description(description)
    if (
        new_name == current.name
        and new_key == current.name_key
        and new_description == current.description
    ):
        return current

    def apply(row: TagRecord) -> TagRecord:
        return TagRecord(
            id=row.id,
            name=new_name,
            name_key=new_key,
            description=new_description,
            created_at=row.created_at,
            updated_at=utc_now(),
        )

    saved = get_tag_store().modify(tag_id, apply)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="tag",
        resource_id=saved.id,
        action="update",
        result="success",
        detail={"name": saved.name},
    )
    return saved


def delete_tag(
    tag_id: str,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    removed = get_tag_store().delete(tag_id)
    if removed is None:
        raise TagNotFound()
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="tag",
        resource_id=removed.id,
        action="delete",
        result="success",
        detail={"name": removed.name},
    )
