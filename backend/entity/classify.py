"""Classify two attribute sets after binding dictionary codes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from backend.entity.attribute_type import resolve
from backend.entity.dictionaries.store import get_dictionary_store
from backend.entity.errors import EntityAttributeInvalid
from backend.entity.lifecycle import latest_published_of
from backend.entity.records import AttributeRecord, EntityVersionRecord, attribute_to_dict

ChangeClass = Literal["breaking", "non_breaking", "unchanged"]

__all__ = [
    "ChangeClass",
    "Classification",
    "ShapeChange",
    "classify_shapes",
]


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


def classify_shapes(
    before: Sequence[AttributeRecord],
    after: Sequence[AttributeRecord],
    *,
    versions: Sequence[EntityVersionRecord],
) -> Classification:
    """Baseline uses a published snapshot when one exists; the proposal uses live codes.

    An unknown dictionary id is ``EntityAttributeInvalid``. Only active entries count.
    """
    version_list = list(versions)
    return _compare_shapes(
        _bind_dictionary_codes(
            tuple(before), versions=version_list, use_snapshot=True
        ),
        _bind_dictionary_codes(
            tuple(after), versions=version_list, use_snapshot=False
        ),
    )


def _bind_dictionary_codes(
    attributes: tuple[AttributeRecord, ...],
    *,
    versions: list[EntityVersionRecord],
    use_snapshot: bool,
) -> tuple[AttributeRecord, ...]:
    """Fill ``codes`` for a classifier input.

    ``use_snapshot`` is the baseline side: a published snapshot wins when one
    exists for that attribute. The proposal side always uses live active codes.
    """
    published = latest_published_of(versions)
    snapshots = published.dictionary_snapshots if published is not None else {}
    bound: list[AttributeRecord] = []
    for attr in attributes:
        if "dictionary" not in resolve(attr.type).reads:
            bound.append(attr)
            continue
        snapshot = snapshots.get(attr.name) if use_snapshot else None
        if isinstance(snapshot, dict) and snapshot.get("dictionary_id"):
            codes = tuple(str(code) for code in (snapshot.get("codes") or ()))
            bound.append(
                replace(
                    attr,
                    dictionary_id=str(snapshot["dictionary_id"]),
                    codes=codes,
                )
            )
            continue
        dictionary_id = attr.dictionary_id or ""
        found = get_dictionary_store().get(dictionary_id)
        if found is None:
            raise EntityAttributeInvalid(
                f"Attribute '{attr.name}' dictionary_id '{dictionary_id}'"
                " does not name a dictionary"
            )
        codes = tuple(entry.code for entry in found.entries if entry.active)
        bound.append(replace(attr, codes=codes))
    return tuple(bound)


def _compare_shapes(
    before: tuple[AttributeRecord, ...],
    after: tuple[AttributeRecord, ...],
) -> Classification:
    changes: list[ShapeChange] = []
    before_attrs = {attr.name: attr for attr in before}
    after_attrs = {attr.name: attr for attr in after}
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
    found.extend(
        ShapeChange(
            field=f"{prefix}.{change.suffix}",
            old_value=change.old_value,
            new_value=change.new_value,
            change_class=change.change_class,
        )
        for change in resolve(before.type).config_changes(before, after)
    )
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


def _roll_up(changes: list[ShapeChange]) -> ChangeClass:
    classes = {item.change_class for item in changes}
    if "breaking" in classes:
        return "breaking"
    if "non_breaking" in classes:
        return "non_breaking"
    return "unchanged"
