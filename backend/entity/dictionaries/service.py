"""Dictionary create, update, delete, and reference lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.entity.dictionaries.records import DictionaryEntryRecord, DictionaryRecord
from backend.entity.dictionaries.rules import (
    active_codes,
    clean_description,
    normalize_entries,
    require_dictionary_name,
    require_display_name,
)
from backend.entity.dictionaries.status import DictionaryListStatus
from backend.entity.dictionaries.store import get_dictionary_store
from backend.entity.errors import DictionaryInUse, DictionaryNotFound
from backend.entity.ids import new_dictionary_id
from backend.entity.store import get_entity_store

__all__ = [
    "DictionaryUsage",
    "dictionary_out",
    "create_dictionary",
    "delete_dictionary",
    "get_dictionary",
    "list_dictionaries",
    "snapshotted_codes",
    "update_dictionary",
]


@dataclass(frozen=True, slots=True)
class DictionaryUsage:
    entity_id: str
    entity_name: str
    table_name: str
    attribute_name: str
    version_id: str
    version: int
    publish_status: str
    behind: bool


def list_dictionaries(
    *,
    q: str | None,
    statuses: list[DictionaryListStatus] | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    items, total = get_dictionary_store().list_dictionaries(
        q=q,
        statuses=None if statuses is None else frozenset(statuses),
        limit=limit,
        offset=offset,
    )
    return [dictionary_out(item, include_detail=False) for item in items], total


def get_dictionary(dictionary_id: str) -> dict[str, Any]:
    return dictionary_out(_require(dictionary_id), include_detail=True)


def create_dictionary(
    *,
    name: str,
    display_name: str,
    description: str | None,
    entries: list[dict[str, object]],
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    now = utc_now()
    record = DictionaryRecord(
        id=new_dictionary_id(),
        name=require_dictionary_name(name),
        display_name=require_display_name(display_name),
        description=clean_description(description),
        revision=1,
        deprecated_at=None,
        entries=normalize_entries(entries, snapshotted=frozenset()),
        created_at=now,
        updated_at=now,
    )
    saved = get_dictionary_store().create(record)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="dictionary",
        resource_id=saved.id,
        action="dictionary.create",
        result="success",
        detail={"name": saved.name},
    )
    return dictionary_out(saved, include_detail=True)


def update_dictionary(
    dictionary_id: str,
    *,
    display_name: str | None,
    description: str | None,
    description_set: bool,
    deprecated: bool | None,
    entries: list[dict[str, object]] | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> dict[str, Any]:
    snapshotted = (
        snapshotted_codes(dictionary_id) if entries is not None else frozenset()
    )

    def apply(current: DictionaryRecord) -> DictionaryRecord:
        new_display = (
            current.display_name
            if display_name is None
            else require_display_name(display_name)
        )
        new_description = (
            clean_description(description) if description_set else current.description
        )
        revision = current.revision
        new_entries = current.entries
        if entries is not None:
            new_entries = normalize_entries(
                entries,
                snapshotted=snapshotted,
                previous=current.entries,
            )
            if active_codes(current.entries) != active_codes(new_entries):
                revision = current.revision + 1
        deprecated_at = current.deprecated_at
        now = utc_now()
        if deprecated is True and deprecated_at is None:
            deprecated_at = now
        elif deprecated is False:
            deprecated_at = None
        return DictionaryRecord(
            id=current.id,
            name=current.name,
            display_name=new_display,
            description=new_description,
            revision=revision,
            deprecated_at=deprecated_at,
            entries=new_entries,
            created_at=current.created_at,
            updated_at=now,
        )

    saved = get_dictionary_store().modify(dictionary_id, apply)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="dictionary",
        resource_id=saved.id,
        action="dictionary.update",
        result="success",
        detail={"name": saved.name, "revision": saved.revision},
    )
    return dictionary_out(saved, include_detail=True)


def delete_dictionary(
    dictionary_id: str,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    current = _require(dictionary_id)
    usages = collect_usages(dictionary_id, revision=current.revision)
    if usages:
        shown = ", ".join(
            f"{item.table_name}.{item.attribute_name}" for item in usages[:8]
        )
        raise DictionaryInUse(f"Dictionary is in use: {shown}")
    if not get_dictionary_store().delete(dictionary_id):
        raise DictionaryNotFound()
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="dictionary",
        resource_id=dictionary_id,
        action="dictionary.delete",
        result="success",
        detail={"name": current.name},
    )


def snapshotted_codes(dictionary_id: str) -> frozenset[str]:
    found: set[str] = set()
    store = get_entity_store()
    for entity in store.list_all_entities():
        for version in store.list_all_versions(entity.id):
            for snapshot in version.dictionary_snapshots.values():
                if snapshot.get("dictionary_id") != dictionary_id:
                    continue
                codes = snapshot.get("codes") or ()
                found.update(str(code) for code in codes)
    return frozenset(found)


def collect_usages(dictionary_id: str, *, revision: int) -> list[DictionaryUsage]:
    usages: list[DictionaryUsage] = []
    store = get_entity_store()
    for entity in store.list_all_entities():
        for version in store.list_all_versions(entity.id):
            for attr in version.attributes:
                if attr.type != "dictionary" or attr.dictionary_id != dictionary_id:
                    continue
                snapshot = version.dictionary_snapshots.get(attr.name) or {}
                behind = (
                    snapshot.get("dictionary_id") == dictionary_id
                    and int(snapshot.get("revision") or 0) < revision
                )
                usages.append(_usage(entity, version, attr.name, behind=behind))
    usages.sort(key=lambda item: (item.table_name, item.version, item.attribute_name))
    return usages


def dictionary_out(record: DictionaryRecord, *, include_detail: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": record.id,
        "name": record.name,
        "display_name": record.display_name,
        "description": record.description,
        "revision": record.revision,
        "deprecated_at": record.deprecated_at,
        "entry_count": len(record.entries),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    if not include_detail:
        return payload
    payload["entries"] = [
        _entry_out(entry) for entry in sorted(record.entries, key=lambda item: item.position)
    ]
    payload["usages"] = [
        {
            "entity_id": item.entity_id,
            "entity_name": item.entity_name,
            "table_name": item.table_name,
            "attribute_name": item.attribute_name,
            "version_id": item.version_id,
            "version": item.version,
            "publish_status": item.publish_status,
            "behind": item.behind,
        }
        for item in collect_usages(record.id, revision=record.revision)
    ]
    return payload


def _require(dictionary_id: str) -> DictionaryRecord:
    found = get_dictionary_store().get(dictionary_id)
    if found is None:
        raise DictionaryNotFound()
    return found


def _entry_out(entry: DictionaryEntryRecord) -> dict[str, Any]:
    return {"code": entry.code, "label": entry.label, "active": entry.active}


def _usage(entity: Any, version: Any, attribute_name: str, *, behind: bool) -> DictionaryUsage:
    return DictionaryUsage(
        entity_id=entity.id,
        entity_name=entity.name,
        table_name=entity.table_name,
        attribute_name=attribute_name,
        version_id=version.id,
        version=version.version,
        publish_status=version.publish_status,
        behind=behind,
    )
