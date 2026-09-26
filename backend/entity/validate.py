"""Write validation for Business Entity definitions."""

from __future__ import annotations

import re

from backend.entity.ddl import ROW_ID_COLUMN
from backend.entity.errors import (
    EntityAttributeInvalid,
    EntityTableNameInvalid,
)
from backend.entity.records import AttributeRecord
from backend.metadata.catalog.normalized_type import CLOSED_NORMALIZED_TYPES

IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ARCHIVE_TABLE_RE = re.compile(r"__rfq_v[0-9]+$")
TABLE_NAME_MAX_LEN = 48
ATTRIBUTE_NAME_MAX_LEN = 63

__all__ = [
    "ATTRIBUTE_NAME_MAX_LEN",
    "TABLE_NAME_MAX_LEN",
    "require_attribute_name",
    "require_normalized_type",
    "require_table_name",
    "validate_shape",
]


def require_table_name(table_name: str) -> str:
    cleaned = (table_name or "").strip()
    if (
        not cleaned
        or len(cleaned) > TABLE_NAME_MAX_LEN
        or not IDENT_RE.match(cleaned)
        or ARCHIVE_TABLE_RE.search(cleaned)
    ):
        raise EntityTableNameInvalid()
    return cleaned


def require_attribute_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned:
        raise EntityAttributeInvalid("Attribute name is required")
    if len(cleaned) > ATTRIBUTE_NAME_MAX_LEN:
        raise EntityAttributeInvalid(
            f"Attribute name must be at most {ATTRIBUTE_NAME_MAX_LEN} characters"
        )
    if not IDENT_RE.match(cleaned):
        raise EntityAttributeInvalid(
            "Attribute name must start with a letter and use only a-z, 0-9, and underscore"
            f" (got '{cleaned}')"
        )
    if cleaned == ROW_ID_COLUMN:
        raise EntityAttributeInvalid(
            f"Attribute name '{ROW_ID_COLUMN}' is reserved for the platform primary key"
        )
    return cleaned


def require_normalized_type(normalized_type: str) -> str:
    cleaned = (normalized_type or "").strip()
    if cleaned not in CLOSED_NORMALIZED_TYPES:
        raise EntityAttributeInvalid(
            f"Attribute normalized_type '{cleaned}' is not in the closed set"
            if cleaned
            else "Attribute normalized_type is required"
        )
    return cleaned


def validate_shape(*, attributes: list[AttributeRecord]) -> list[AttributeRecord]:
    seen: set[str] = set()
    cleaned_attrs: list[AttributeRecord] = []
    for attr in attributes:
        name = require_attribute_name(attr.name)
        if name in seen:
            raise EntityAttributeInvalid(
                f"Attribute name '{name}' is already used in this version"
            )
        seen.add(name)
        cleaned_attrs.append(
            AttributeRecord(
                name=name,
                normalized_type=require_normalized_type(attr.normalized_type),
                nullable=bool(attr.nullable),
                unique=bool(attr.unique),
                indexed=bool(attr.indexed),
                description=(
                    attr.description.strip()
                    if isinstance(attr.description, str) and attr.description.strip()
                    else attr.description
                    if isinstance(attr.description, str)
                    else None
                ),
            )
        )
    return cleaned_attrs
