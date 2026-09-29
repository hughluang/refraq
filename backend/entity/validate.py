"""Write validation for Business Entity definitions."""

from __future__ import annotations

import re
from dataclasses import replace

from backend.entity.ddl import ROW_ID_COLUMN
from backend.entity.errors import (
    EntityAttributeInvalid,
    EntityTableNameInvalid,
)
from backend.entity.lifecycle import is_deprecated
from backend.entity.records import AttributeRecord, EnumerationEntry
from backend.entity.store import EntityStore

IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PHYSICAL_TABLE_RE = re.compile(r"^.+__v[0-9]+__[0-9a-f]{16}$")
TABLE_NAME_MAX_LEN = 63
ATTRIBUTE_NAME_MAX_LEN = 63
STRING_MAX_LENGTH_MIN = 1
STRING_MAX_LENGTH_MAX = 65535
ENUM_CODE_MAX_LEN = 64
ENUM_LABEL_MAX_LEN = 200
DECIMAL_PRECISION_MIN = 1
DECIMAL_PRECISION_MAX = 1000

ATTRIBUTE_TYPES = frozenset(
    {
        "string",
        "text",
        "integer",
        "decimal",
        "number",
        "boolean",
        "date",
        "timestamp",
        "time",
        "json",
        "enumeration",
        "reference",
    }
)
CONFIG_KEYS: dict[str, frozenset[str]] = {
    "string": frozenset({"max_length"}),
    "text": frozenset(),
    "integer": frozenset(),
    "decimal": frozenset({"precision", "scale"}),
    "number": frozenset(),
    "boolean": frozenset(),
    "date": frozenset(),
    "timestamp": frozenset(),
    "time": frozenset(),
    "json": frozenset(),
    "enumeration": frozenset({"entries"}),
    "reference": frozenset({"target_entity_id"}),
}

REFERENCE_SELF = "self"

__all__ = [
    "ATTRIBUTE_NAME_MAX_LEN",
    "ATTRIBUTE_TYPES",
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
    if cleaned not in ATTRIBUTE_TYPES:
        raise EntityAttributeInvalid(
            f"Attribute type '{cleaned}' is not in the closed set"
            if cleaned
            else "Attribute type is required"
        )
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
    return cleaned_attrs


def _validate_attribute(
    attr: AttributeRecord,
    *,
    name: str,
) -> AttributeRecord:
    attribute_type = require_attribute_type(attr.type)
    description = _clean_description(attr.description)
    _reject_foreign_config(attr, name=name, attribute_type=attribute_type)
    if attribute_type == "string":
        max_length = _require_max_length(name=name, max_length=attr.max_length)
        return _base(attr, name=name, attribute_type=attribute_type, description=description, max_length=max_length)
    if attribute_type == "decimal":
        precision, scale = _require_precision_scale(
            name=name, precision=attr.precision, scale=attr.scale
        )
        return _base(
            attr,
            name=name,
            attribute_type=attribute_type,
            description=description,
            precision=precision,
            scale=scale,
        )
    if attribute_type == "enumeration":
        entries = _require_entries(name=name, entries=attr.entries)
        return _base(
            attr,
            name=name,
            attribute_type=attribute_type,
            description=description,
            entries=entries,
        )
    if attribute_type == "reference":
        target = (attr.target_entity_id or "").strip()
        if not target:
            raise EntityAttributeInvalid(
                f"Attribute '{name}' of type reference requires target_entity_id"
            )
        return _base(
            attr,
            name=name,
            attribute_type=attribute_type,
            description=description,
            target_entity_id=target,
        )
    return _base(attr, name=name, attribute_type=attribute_type, description=description)


def _base(
    attr: AttributeRecord,
    *,
    name: str,
    attribute_type: str,
    description: str | None,
    max_length: int | None = None,
    precision: int | None = None,
    scale: int | None = None,
    entries: tuple[EnumerationEntry, ...] | None = None,
    target_entity_id: str | None = None,
) -> AttributeRecord:
    return AttributeRecord(
        name=name,
        type=attribute_type,
        required=bool(attr.required),
        unique=bool(attr.unique),
        indexed=bool(attr.indexed),
        description=description,
        max_length=max_length,
        precision=precision,
        scale=scale,
        entries=entries,
        target_entity_id=target_entity_id,
    )


def _reject_foreign_config(
    attr: AttributeRecord, *, name: str, attribute_type: str
) -> None:
    present: list[str] = []
    if attr.max_length is not None:
        present.append("max_length")
    if attr.precision is not None:
        present.append("precision")
    if attr.scale is not None:
        present.append("scale")
    if attr.entries is not None:
        present.append("entries")
    if attr.target_entity_id is not None:
        present.append("target_entity_id")
    allowed = CONFIG_KEYS[attribute_type]
    foreign = [key for key in present if key not in allowed]
    if foreign:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' of type {attribute_type} rejects config"
            f" {', '.join(foreign)}"
        )


def bind_reference_self(
    attributes: list[AttributeRecord],
    *,
    entity_id: str,
) -> list[AttributeRecord]:
    """Replace the write sentinel ``self`` with the entity id of this request."""
    bound: list[AttributeRecord] = []
    for attr in attributes:
        target = (attr.target_entity_id or "").strip()
        if attr.type == "reference" and target == REFERENCE_SELF:
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
        if attr.type != "reference":
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


def _require_max_length(*, name: str, max_length: int | None) -> int:
    if max_length is None:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' of type string requires max_length"
        )
    if not isinstance(max_length, int) or isinstance(max_length, bool):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' max_length must be an integer"
        )
    if max_length < STRING_MAX_LENGTH_MIN or max_length > STRING_MAX_LENGTH_MAX:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' max_length must be between"
            f" {STRING_MAX_LENGTH_MIN} and {STRING_MAX_LENGTH_MAX} (got {max_length})"
        )
    return max_length


def _require_precision_scale(
    *,
    name: str,
    precision: int | None,
    scale: int | None,
) -> tuple[int, int]:
    if precision is None or scale is None:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' of type decimal requires precision and scale"
        )
    if not isinstance(precision, int) or isinstance(precision, bool):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' decimal precision must be an integer"
        )
    if not isinstance(scale, int) or isinstance(scale, bool):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' decimal scale must be an integer"
        )
    if precision < DECIMAL_PRECISION_MIN or precision > DECIMAL_PRECISION_MAX:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' decimal precision must be between"
            f" {DECIMAL_PRECISION_MIN} and {DECIMAL_PRECISION_MAX} (got {precision})"
        )
    if scale < 0 or scale > precision:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' decimal scale must be between 0 and precision"
            f" (got {scale})"
        )
    return precision, scale


def _require_entries(
    *,
    name: str,
    entries: tuple[EnumerationEntry, ...] | None,
) -> tuple[EnumerationEntry, ...]:
    if entries is None or len(entries) == 0:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' enumeration must be a non-empty list"
        )
    seen_codes: set[str] = set()
    cleaned: list[EnumerationEntry] = []
    for entry in entries:
        code = _validate_enum_code(name=name, code=entry.code)
        if code in seen_codes:
            raise EntityAttributeInvalid(
                f"Attribute '{name}' enumeration code '{code}' is duplicated"
            )
        seen_codes.add(code)
        label = _validate_enum_label(name=name, label=entry.label)
        cleaned.append(EnumerationEntry(code=code, label=label))
    return tuple(cleaned)


def _validate_enum_code(*, name: str, code: str) -> str:
    if not isinstance(code, str):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' enumeration code must be a string"
        )
    if not code or len(code) > ENUM_CODE_MAX_LEN:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' enumeration code must be non-empty and"
            f" at most {ENUM_CODE_MAX_LEN} characters"
        )
    return code


def _validate_enum_label(*, name: str, label: str | None) -> str | None:
    if label is None:
        return None
    if not isinstance(label, str):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' enumeration label must be a string"
        )
    if len(label) > ENUM_LABEL_MAX_LEN:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' enumeration label must be at most"
            f" {ENUM_LABEL_MAX_LEN} characters"
        )
    return label


def _clean_description(description: str | None) -> str | None:
    if isinstance(description, str) and description.strip():
        return description.strip()
    if isinstance(description, str):
        return description
    return None
