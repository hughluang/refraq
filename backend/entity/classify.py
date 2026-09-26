"""Change classifier: a pure function of two attribute sets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.entity.records import AttributeRecord, attribute_to_dict

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
                change_class="non_breaking" if after.nullable else "breaking",
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
    if before.normalized_type != after.normalized_type:
        found.append(
            ShapeChange(
                field=f"{prefix}.normalized_type",
                old_value=before.normalized_type,
                new_value=after.normalized_type,
                change_class=_type_change_class(
                    before.normalized_type, after.normalized_type
                ),
            )
        )
    if before.nullable != after.nullable:
        found.append(
            ShapeChange(
                field=f"{prefix}.nullable",
                old_value=before.nullable,
                new_value=after.nullable,
                change_class="non_breaking" if after.nullable else "breaking",
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


def _type_change_class(old: str, new: str) -> ChangeClass:
    if old == "unknown":
        return "non_breaking"
    if old == "integer" and new == "number":
        return "non_breaking"
    return "breaking"


def _roll_up(changes: list[ShapeChange]) -> ChangeClass:
    classes = {item.change_class for item in changes}
    if "breaking" in classes:
        return "breaking"
    if "non_breaking" in classes:
        return "non_breaking"
    return "unchanged"
