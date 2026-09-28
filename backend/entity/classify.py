"""Change classifier: a pure function of two attribute sets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.entity.records import AttributeRecord, EnumerationEntry, attribute_to_dict

ChangeClass = Literal["breaking", "non_breaking", "unchanged"]

__all__ = [
    "ChangeClass",
    "Classification",
    "DefinitionShape",
    "ShapeChange",
    "classify_shapes",
]


@dataclass(frozen=True, slots=True)
class DefinitionShape:
    attributes: tuple[AttributeRecord, ...]


@dataclass(frozen=True, slots=True)
class ShapeChange:
    field: str
    old_value: Any
    new_value: Any
    change_class: ChangeClass


@dataclass(frozen=True, slots=True)
class Classification:
    change_class: ChangeClass
    changes: tuple[ShapeChange, ...]


def classify_shapes(before: DefinitionShape, after: DefinitionShape) -> Classification:
    changes: list[ShapeChange] = []
    before_attrs = {attr.name: attr for attr in before.attributes}
    after_attrs = {attr.name: attr for attr in after.attributes}
    for name in sorted(set(before_attrs) | set(after_attrs)):
        changes.extend(_attribute_changes(before_attrs.get(name), after_attrs.get(name)))
    return Classification(change_class=_roll_up(changes), changes=tuple(changes))


def _attribute_changes(
    before: AttributeRecord | None, after: AttributeRecord | None
) -> list[ShapeChange]:
    if before is None and after is not None:
        return [
            ShapeChange(
                field=f"attributes.{after.name}",
                old_value=None,
                new_value=attribute_to_dict(after),
                change_class="breaking" if after.required else "non_breaking",
            )
        ]
    if before is not None and after is None:
        return [
            ShapeChange(
                field=f"attributes.{before.name}",
                old_value=attribute_to_dict(before),
                new_value=None,
                change_class="breaking",
            )
        ]
    assert before is not None and after is not None
    prefix = f"attributes.{before.name}"
    found: list[ShapeChange] = []
    if before.type != after.type:
        found.append(
            ShapeChange(
                field=f"{prefix}.type",
                old_value=before.type,
                new_value=after.type,
                change_class="breaking",
            )
        )
        return found
    found.extend(_config_changes(prefix, before, after))
    if before.required != after.required:
        found.append(
            ShapeChange(
                field=f"{prefix}.required",
                old_value=before.required,
                new_value=after.required,
                change_class="breaking" if after.required else "non_breaking",
            )
        )
    if before.unique != after.unique:
        found.append(
            ShapeChange(
                field=f"{prefix}.unique",
                old_value=before.unique,
                new_value=after.unique,
                change_class="non_breaking",
            )
        )
    if before.indexed != after.indexed:
        found.append(
            ShapeChange(
                field=f"{prefix}.indexed",
                old_value=before.indexed,
                new_value=after.indexed,
                change_class="non_breaking",
            )
        )
    if before.description != after.description:
        found.append(
            ShapeChange(
                field=f"{prefix}.description",
                old_value=before.description,
                new_value=after.description,
                change_class="unchanged",
            )
        )
    return found


def _config_changes(
    prefix: str, before: AttributeRecord, after: AttributeRecord
) -> list[ShapeChange]:
    if before.type == "string":
        return _max_length_change(prefix, before, after)
    if before.type == "decimal":
        return _decimal_changes(prefix, before, after)
    if before.type == "enumeration":
        return _enumeration_changes(prefix, before.entries, after.entries)
    if before.type == "reference":
        return _target_change(prefix, before, after)
    return []


def _max_length_change(
    prefix: str, before: AttributeRecord, after: AttributeRecord
) -> list[ShapeChange]:
    if before.max_length == after.max_length:
        return []
    old = before.max_length
    new = after.max_length
    widening = old is not None and new is not None and new > old
    return [
        ShapeChange(
            field=f"{prefix}.config.max_length",
            old_value=old,
            new_value=new,
            change_class="non_breaking" if widening else "breaking",
        )
    ]


def _decimal_changes(
    prefix: str, before: AttributeRecord, after: AttributeRecord
) -> list[ShapeChange]:
    found: list[ShapeChange] = []
    if before.precision != after.precision:
        found.append(
            ShapeChange(
                field=f"{prefix}.config.precision",
                old_value=before.precision,
                new_value=after.precision,
                change_class="breaking",
            )
        )
    if before.scale != after.scale:
        found.append(
            ShapeChange(
                field=f"{prefix}.config.scale",
                old_value=before.scale,
                new_value=after.scale,
                change_class="breaking",
            )
        )
    return found


def _target_change(
    prefix: str, before: AttributeRecord, after: AttributeRecord
) -> list[ShapeChange]:
    if before.target_entity_id == after.target_entity_id:
        return []
    return [
        ShapeChange(
            field=f"{prefix}.config.target_entity_id",
            old_value=before.target_entity_id,
            new_value=after.target_entity_id,
            change_class="breaking",
        )
    ]


def _enumeration_changes(
    prefix: str,
    before: tuple[EnumerationEntry, ...] | None,
    after: tuple[EnumerationEntry, ...] | None,
) -> list[ShapeChange]:
    before_codes = _enum_codes(before)
    after_codes = _enum_codes(after)
    before_labels = _enum_labels(before)
    after_labels = _enum_labels(after)
    found: list[ShapeChange] = []
    before_set = set(before_codes)
    after_set = set(after_codes)
    if before_set != after_set:
        only_added = before_set < after_set
        found.append(
            ShapeChange(
                field=f"{prefix}.config.entries",
                old_value=_enum_payload(before),
                new_value=_enum_payload(after),
                change_class="non_breaking" if only_added else "breaking",
            )
        )
        return found
    if before_labels != after_labels:
        found.append(
            ShapeChange(
                field=f"{prefix}.config.entries",
                old_value=_enum_payload(before),
                new_value=_enum_payload(after),
                change_class="unchanged",
            )
        )
    return found


def _enum_codes(
    entries: tuple[EnumerationEntry, ...] | None,
) -> tuple[str, ...]:
    if entries is None:
        return ()
    return tuple(entry.code for entry in entries)


def _enum_labels(
    entries: tuple[EnumerationEntry, ...] | None,
) -> tuple[tuple[str, str | None], ...]:
    if entries is None:
        return ()
    return tuple(sorted((entry.code, entry.label) for entry in entries))


def _enum_payload(
    entries: tuple[EnumerationEntry, ...] | None,
) -> list[dict[str, str | None]] | None:
    if entries is None:
        return None
    return [
        (
            {"code": entry.code, "label": entry.label}
            if entry.label is not None
            else {"code": entry.code}
        )
        for entry in entries
    ]


def _roll_up(changes: list[ShapeChange]) -> ChangeClass:
    classes = {item.change_class for item in changes}
    if "breaking" in classes:
        return "breaking"
    if "non_breaking" in classes:
        return "non_breaking"
    return "unchanged"
