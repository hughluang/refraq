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
    "attribute_to_stored",
]


@dataclass(frozen=True, slots=True)
class AttributeRecord:
    name: str
    type: str
    required: bool = False
    unique: bool = False
    indexed: bool = False
    business_key: bool = False
    description: str | None = None
    max_length: int | None = None
    precision: int | None = None
    scale: int | None = None
    dictionary_id: str | None = None
    target_entity_id: str | None = None
    # Resolved for classify and DDL. Not stored on the attribute definition.
    codes: tuple[str, ...] | None = None
    # Stamped from the reference snapshot for DDL and row encoding. Not stored.
    reference_key_type: str | None = None
    reference_max_length: int | None = None
    # Server-assigned at publish; stable across versions while the name is kept.
    # Not part of shape equality and never accepted on write.
    attribute_id: str | None = field(default=None, compare=False)


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
    reference_snapshots: dict[str, Any] = field(default_factory=dict)


def attribute_to_dict(attr: AttributeRecord) -> dict[str, Any]:
    return {
        "name": attr.name,
        "type": attr.type,
        "required": attr.required,
        "unique": bool(attr.unique),
        "indexed": bool(attr.indexed),
        "business_key": bool(attr.business_key),
        "description": attr.description,
        "config": resolve(attr.type).config_payload(attr),
    }


def attribute_to_stored(attr: AttributeRecord) -> dict[str, Any]:
    """Definition-store form: the authored shape plus the assigned attribute_id."""
    payload = attribute_to_dict(attr)
    if attr.attribute_id is not None:
        payload["attribute_id"] = attr.attribute_id
    return payload


def attribute_from_dict(payload: dict[str, Any]) -> AttributeRecord:
    """Hydrate a stored attribute. Only the Attribute Type shape is accepted."""
    if "type" not in payload:
        raise KeyError("attribute type")
    config = payload.get("config")
    if not isinstance(config, dict):
        raise TypeError("attribute config must be an object")
    description = payload.get("description")
    attribute_type = str(payload["type"])
    attribute_id = payload.get("attribute_id")
    return AttributeRecord(
        name=str(payload["name"]),
        type=attribute_type,
        required=bool(payload.get("required", False)),
        unique=bool(payload.get("unique", False)),
        indexed=bool(payload.get("indexed", False)),
        business_key=bool(payload.get("business_key", False)),
        description=str(description) if isinstance(description, str) else None,
        attribute_id=attribute_id if isinstance(attribute_id, str) else None,
        **resolve(attribute_type).stored_fields(config),
    )
