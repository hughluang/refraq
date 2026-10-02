"""Classify two attribute sets after binding dictionary codes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

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
        if attr.type != "dictionary":
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
    if before.type == "dictionary":
        return _dictionary_changes(prefix, before, after)
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


def _dictionary_changes(
    prefix: str, before: AttributeRecord, after: AttributeRecord
) -> list[ShapeChange]:
    before_codes = tuple(before.codes or ())
    after_codes = tuple(after.codes or ())
    before_set = set(before_codes)
    after_set = set(after_codes)
    added = sorted(after_set - before_set)
    removed = sorted(before_set - after_set)
    same_list = before.dictionary_id == after.dictionary_id
    if before_set == after_set and same_list:
        return []
    if before_set == after_set:
        change_class: ChangeClass = "unchanged"
    elif not removed:
        change_class = "non_breaking"
    else:
        change_class = "breaking"
    return [
        ShapeChange(
            field=f"{prefix}.config.dictionary",
            old_value={
                "dictionary_id": before.dictionary_id,
                "codes": list(before_codes),
            },
            new_value={
                "dictionary_id": after.dictionary_id,
                "codes": list(after_codes),
                "added": added,
                "removed": removed,
            },
            change_class=change_class,
        )
    ]


def _roll_up(changes: list[ShapeChange]) -> ChangeClass:
    classes = {item.change_class for item in changes}
    if "breaking" in classes:
        return "breaking"
    if "non_breaking" in classes:
        return "non_breaking"
    return "unchanged"
