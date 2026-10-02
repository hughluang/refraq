"""In-memory records for Business Entity persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.entity.attribute_type import resolve

__all__ = [
    "AttributeRecord",
    "BusinessEntityRecord",
    "EntityVersionRecord",
    "attribute_from_dict",
    "attribute_to_dict",
]


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
    dictionary_id: str | None = None
    target_entity_id: str | None = None
    # Resolved for classify and DDL. Not stored on the attribute definition.
    codes: tuple[str, ...] | None = None


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
    dictionary_snapshots: dict[str, Any] = field(default_factory=dict)


def attribute_to_dict(attr: AttributeRecord) -> dict[str, Any]:
    return {
        "name": attr.name,
        "type": attr.type,
        "required": attr.required,
        "unique": bool(attr.unique),
        "indexed": bool(attr.indexed),
        "description": attr.description,
        "config": resolve(attr.type).config_payload(attr),
    }


def attribute_from_dict(payload: dict[str, Any]) -> AttributeRecord:
    """Hydrate a stored attribute. Only the Attribute Type shape is accepted."""
    if "type" not in payload:
        raise KeyError("attribute type")
    config = payload.get("config")
    if not isinstance(config, dict):
        raise TypeError("attribute config must be an object")
    description = payload.get("description")
    attribute_type = str(payload["type"])
    return AttributeRecord(
        name=str(payload["name"]),
        type=attribute_type,
        required=bool(payload.get("required", False)),
        unique=bool(payload.get("unique", False)),
        indexed=bool(payload.get("indexed", False)),
        description=str(description) if isinstance(description, str) else None,
        **resolve(attribute_type).stored_fields(config),
    )
