"""In-memory records for Business Entity persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

__all__ = [
    "AttributeRecord",
    "BusinessEntityRecord",
    "EntityVersionRecord",
    "attribute_from_dict",
    "attribute_to_dict",
    "snapshot_from_attributes",
    "snapshot_signature",
]


@dataclass(frozen=True, slots=True)
class AttributeRecord:
    name: str
    normalized_type: str
    nullable: bool
    description: str | None = None
    unique: bool = False
    indexed: bool = False


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
        "normalized_type": attr.normalized_type,
        "nullable": attr.nullable,
        "unique": bool(attr.unique),
        "indexed": bool(attr.indexed),
        "description": attr.description,
    }


def attribute_from_dict(payload: dict[str, Any]) -> AttributeRecord:
    description = payload.get("description")
    return AttributeRecord(
        name=str(payload["name"]),
        normalized_type=str(payload["normalized_type"]),
        nullable=bool(payload["nullable"]),
        description=str(description) if isinstance(description, str) else None,
        unique=bool(payload.get("unique", False)),
        indexed=bool(payload.get("indexed", False)),
    )


def snapshot_from_attributes(attributes: list[AttributeRecord]) -> list[dict[str, Any]]:
    return [
        {
            "name": attr.name,
            "normalized_type": attr.normalized_type,
            "nullable": attr.nullable,
            "unique": bool(attr.unique),
            "indexed": bool(attr.indexed),
        }
        for attr in attributes
    ]


def snapshot_signature(
    items: list[dict[str, Any]],
) -> tuple[tuple[str, str, bool, bool, bool], ...]:
    rows = [
        (
            str(item["name"]),
            str(item["normalized_type"]),
            bool(item["nullable"]),
            bool(item.get("unique", False)),
            bool(item.get("indexed", False)),
        )
        for item in items
    ]
    return tuple(sorted(rows))
