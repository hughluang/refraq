"""In-memory records for Business Entity persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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
        dictionary_id=_optional_str(config.get("dictionary_id"))
        if "dictionary_id" in config
        else None,
        target_entity_id=(
            str(config["target_entity_id"])
            if config.get("target_entity_id") is not None
            else None
        ),
    )


def _config_dict(attr: AttributeRecord) -> dict[str, Any]:
    if attr.type == "string":
        return {"max_length": attr.max_length}
    if attr.type == "decimal":
        return {"precision": attr.precision, "scale": attr.scale}
    if attr.type == "dictionary":
        return {"dictionary_id": attr.dictionary_id}
    if attr.type == "reference":
        return {"target_entity_id": attr.target_entity_id}
    return {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("dictionary_id must be a string")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("attribute config integer fields must be integers")
    return value
