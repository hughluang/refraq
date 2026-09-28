"""In-memory records for Business Entity persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

__all__ = [
    "AttributeRecord",
    "BusinessEntityRecord",
    "EntityVersionRecord",
    "EnumerationEntry",
    "attribute_from_dict",
    "attribute_to_dict",
    "snapshot_signature",
]


@dataclass(frozen=True, slots=True)
class EnumerationEntry:
    code: str
    label: str | None = None


@dataclass(frozen=True, slots=True)
class AttributeRecord:
    name: str
    type: str
    required: bool = False
    unique: bool = False
    indexed: bool = False
    description: str | None = None
    max_length: int | None = None
    precision: int | None = None
    scale: int | None = None
    entries: tuple[EnumerationEntry, ...] | None = None
    target_entity_id: str | None = None


@dataclass
class BusinessEntityRecord:
    id: str
    table_name: str
    name: str
    description: str
    deprecated_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class EntityVersionRecord:
    id: str
    entity_id: str
    version: int
    attributes: list[AttributeRecord]
    materialized_attributes: list[dict[str, Any]]
    publish_status: str
    latest_reconcile_job_id: str | None
    created_at: datetime
    updated_at: datetime


def attribute_to_dict(attr: AttributeRecord) -> dict[str, Any]:
    return {
        "name": attr.name,
        "type": attr.type,
        "required": attr.required,
        "unique": bool(attr.unique),
        "indexed": bool(attr.indexed),
        "description": attr.description,
        "config": _config_dict(attr),
    }


def attribute_from_dict(payload: dict[str, Any]) -> AttributeRecord:
    """Hydrate a stored attribute. Only the Attribute Type shape is accepted."""
    if "type" not in payload:
        raise KeyError("attribute type")
    config = payload.get("config")
    if not isinstance(config, dict):
        raise TypeError("attribute config must be an object")
    description = payload.get("description")
    entries = (
        _enumeration_from_payload(config.get("entries"))
        if "entries" in config
        else None
    )
    return AttributeRecord(
        name=str(payload["name"]),
        type=str(payload["type"]),
        required=bool(payload.get("required", False)),
        unique=bool(payload.get("unique", False)),
        indexed=bool(payload.get("indexed", False)),
        description=str(description) if isinstance(description, str) else None,
        max_length=_optional_int(config.get("max_length")) if "max_length" in config else None,
        precision=_optional_int(config.get("precision")) if "precision" in config else None,
        scale=_optional_int(config.get("scale")) if "scale" in config else None,
        entries=entries,
        target_entity_id=(
            str(config["target_entity_id"])
            if config.get("target_entity_id") is not None
            else None
        ),
    )


def snapshot_signature(
    items: list[dict[str, Any]],
) -> tuple[tuple[Any, ...], ...]:
    rows = [_signature_row(item) for item in items]
    return tuple(sorted(rows))


def _config_dict(attr: AttributeRecord) -> dict[str, Any]:
    if attr.type == "string":
        return {"max_length": attr.max_length}
    if attr.type == "decimal":
        return {"precision": attr.precision, "scale": attr.scale}
    if attr.type == "enumeration":
        return {"entries": _entries_payload(attr.entries)}
    if attr.type == "reference":
        return {"target_entity_id": attr.target_entity_id}
    return {}


def _entries_payload(
    entries: tuple[EnumerationEntry, ...] | None,
) -> list[dict[str, str | None]]:
    if not entries:
        return []
    return [
        (
            {"code": entry.code, "label": entry.label}
            if entry.label is not None
            else {"code": entry.code}
        )
        for entry in entries
    ]


def _signature_row(item: dict[str, Any]) -> tuple[Any, ...]:
    config = item.get("config") if isinstance(item.get("config"), dict) else {}
    raw_entries = config.get("entries")
    enum_codes: tuple[str, ...] = ()
    if raw_entries is not None:
        enum_codes = tuple(str(entry["code"]) for entry in raw_entries)
    return (
        str(item["name"]),
        str(item["type"]),
        bool(item.get("required", False)),
        bool(item.get("unique", False)),
        bool(item.get("indexed", False)),
        config.get("max_length"),
        config.get("precision"),
        config.get("scale"),
        enum_codes,
        config.get("target_entity_id"),
    )


def _enumeration_from_payload(
    raw: Any,
) -> tuple[EnumerationEntry, ...] | None:
    if raw is None:
        return None
    entries: list[EnumerationEntry] = []
    for item in raw:
        if "label" not in item:
            label: str | None = None
        else:
            label = item["label"]
            if not isinstance(label, str):
                raise TypeError("enumeration label must be a string")
        entries.append(EnumerationEntry(code=str(item["code"]), label=label))
    return tuple(entries)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("attribute config integer fields must be integers")
    return value
