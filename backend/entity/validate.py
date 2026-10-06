"""Write validation for Business Entity definitions."""

from __future__ import annotations

import re
from dataclasses import replace

from backend.entity.attribute_type import resolve
from backend.entity.ddl import ROW_ID_COLUMN
from backend.entity.errors import (
    EntityAttributeInvalid,
    EntityTableNameInvalid,
)
from backend.entity.lifecycle import is_deprecated
from backend.entity.records import AttributeRecord
from backend.entity.store import EntityStore

IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PHYSICAL_TABLE_RE = re.compile(r"^.+__v[0-9]+__[0-9a-f]{16}$")
TABLE_NAME_MAX_LEN = 63
ATTRIBUTE_NAME_MAX_LEN = 63
REFERENCE_SELF = "self"

__all__ = [
    "ATTRIBUTE_NAME_MAX_LEN",
    "TABLE_NAME_MAX_LEN",
    "REFERENCE_SELF",
    "bind_reference_self",
    "require_attribute_name",
    "require_attribute_type",
    "require_reference_targets",
    "require_table_name",
    "validate_shape",
]


def require_table_name(table_name: str) -> str:
    cleaned = (table_name or "").strip()
    if (
        not cleaned
        or len(cleaned) > TABLE_NAME_MAX_LEN
        or not IDENT_RE.match(cleaned)
        or PHYSICAL_TABLE_RE.match(cleaned)
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


def require_attribute_type(attribute_type: str) -> str:
    cleaned = (attribute_type or "").strip()
    resolve(cleaned)
    return cleaned


def validate_shape(
    *,
    attributes: list[AttributeRecord],
) -> list[AttributeRecord]:
    seen: set[str] = set()
    cleaned_attrs: list[AttributeRecord] = []
    for attr in attributes:
        name = require_attribute_name(attr.name)
        if name in seen:
            raise EntityAttributeInvalid(
                f"Attribute name '{name}' is already used in this version"
            )
        seen.add(name)
        cleaned_attrs.append(_validate_attribute(attr, name=name))
    _require_business_key(cleaned_attrs)
    return cleaned_attrs


def _validate_attribute(
    attr: AttributeRecord,
    *,
    name: str,
) -> AttributeRecord:
    attribute_type = require_attribute_type(attr.type)
    prepared = replace(
        attr,
        name=name,
        type=attribute_type,
        description=_clean_description(attr.description),
        required=bool(attr.required),
        unique=bool(attr.unique),
        indexed=bool(attr.indexed),
        business_key=bool(attr.business_key),
    )
    return resolve(attribute_type).clean(prepared)


def bind_reference_self(
    attributes: list[AttributeRecord],
    *,
    entity_id: str,
) -> list[AttributeRecord]:
    """Replace the write sentinel ``self`` with the entity id of this request."""
    bound: list[AttributeRecord] = []
    for attr in attributes:
        target = (attr.target_entity_id or "").strip()
        if "target" in resolve(attr.type).reads and target == REFERENCE_SELF:
            bound.append(replace(attr, target_entity_id=entity_id))
        else:
            bound.append(attr)
    return bound


def require_reference_targets(
    store: EntityStore,
    attributes: list[AttributeRecord],
    *,
    entity_id: str,
) -> None:
    for attr in attributes:
        if "target" not in resolve(attr.type).reads:
            continue
        target_entity_id = attr.target_entity_id or ""
        if target_entity_id == entity_id:
            continue
        target = store.get_entity(target_entity_id)
        if target is None:
            raise EntityAttributeInvalid(
                f"Attribute target_entity_id '{target_entity_id}' does not name an existing entity"
            )
        if is_deprecated(target):
            raise EntityAttributeInvalid(
                f"Attribute target_entity_id '{target_entity_id}' names a deprecated entity"
            )


def _require_business_key(attributes: list[AttributeRecord]) -> None:
    marked = [attr for attr in attributes if attr.business_key]
    if len(marked) > 1:
        raise EntityAttributeInvalid("A version has at most one business_key")
    if not marked:
        return
    attr = marked[0]
    if attr.type not in ("string", "integer"):
        raise EntityAttributeInvalid(
            f"Attribute '{attr.name}' business_key requires type string or integer"
        )
    if not attr.unique or not attr.required:
        raise EntityAttributeInvalid(
            f"Attribute '{attr.name}' business_key requires unique and required"
        )


def _clean_description(description: str | None) -> str | None:
    if isinstance(description, str) and description.strip():
        return description.strip()
    if isinstance(description, str):
        return description
    return None
