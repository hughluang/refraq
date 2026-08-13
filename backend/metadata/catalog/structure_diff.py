"""Structure Diff facts: existing vs incoming catalog (not the touched-object plan)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.metadata.catalog.identity import (
    _incoming_covers_existing,
    _match_existing_for_incoming,
)
from backend.metadata.catalog.records import CatalogObjectRecord

DIFF_SCHEMA = "structure.diff.v1"

COUNT_KEYS = (
    "objects_added",
    "objects_removed",
    "columns_added",
    "columns_removed",
    "type_changed",
    "pk_changed",
    "nullable_tightened",
    "nullable_widened",
    "comments_or_defaults",
)

BREAKING_COUNT_KEYS = frozenset(
    {
        "objects_removed",
        "columns_removed",
        "type_changed",
        "pk_changed",
        "nullable_tightened",
    }
)

NON_BREAKING_COUNT_KEYS = frozenset(
    {
        "objects_added",
        "columns_added",
        "nullable_widened",
        "comments_or_defaults",
    }
)


@dataclass(frozen=True)
class StructureChange:
    change: str
    locator_key: str
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {"change": self.change, "locator_key": self.locator_key}
        payload.update(self.extra)
        return payload


@dataclass(frozen=True)
class StructureDiffFacts:
    diff_class: str
    counts: dict[str, int]
    changes: tuple[StructureChange, ...]

    def result_envelope(self, structure_diff_id: str) -> dict[str, Any]:
        return {
            "schema": DIFF_SCHEMA,
            "class": self.diff_class,
            "counts": dict(self.counts),
            "structure_diff_id": structure_diff_id,
        }

    def changes_document(self) -> list[dict[str, Any]]:
        return [c.as_dict() for c in self.changes]


def empty_counts() -> dict[str, int]:
    return {key: 0 for key in COUNT_KEYS}


def derive_class(counts: dict[str, int]) -> str:
    if any(counts.get(key, 0) > 0 for key in BREAKING_COUNT_KEYS):
        return "breaking"
    if any(counts.get(key, 0) > 0 for key in NON_BREAKING_COUNT_KEYS):
        return "non_breaking"
    return "unchanged"


def compute_structure_diff(
    *,
    existing: list[CatalogObjectRecord],
    incoming: list[CatalogObjectRecord],
    schema_scope: str | None,
) -> StructureDiffFacts:
    """Diff current catalog against a trusted incoming collect (pre-commit)."""
    incoming_keys = {(o.schema_name, o.name, o.object_type): o for o in incoming}
    existing_by_key = {
        (o.schema_name, o.name, o.object_type): o for o in existing
    }
    counts = empty_counts()
    changes: list[StructureChange] = []

    for old in existing:
        if not old.is_present:
            continue
        if schema_scope is not None and old.schema_name != schema_scope:
            continue
        if _incoming_covers_existing(
            existing_schema=old.schema_name,
            existing_name=old.name,
            existing_type=old.object_type,
            incoming_keys=incoming_keys,
        ):
            continue
        counts["objects_removed"] += 1
        changes.append(
            StructureChange(change="object_removed", locator_key=old.locator_key)
        )

    for incoming_obj in incoming:
        match = _match_existing_for_incoming(
            schema_name=incoming_obj.schema_name,
            name=incoming_obj.name,
            object_type=incoming_obj.object_type,
            existing_by_key=existing_by_key,
        )
        if match is None or not match.is_present:
            counts["objects_added"] += 1
            changes.append(
                StructureChange(
                    change="object_added",
                    locator_key=incoming_obj.locator_key,
                )
            )
            continue
        _diff_matched_object(match, incoming_obj, counts, changes)

    return StructureDiffFacts(
        diff_class=derive_class(counts),
        counts=counts,
        changes=tuple(changes),
    )


def _pk_tuple(value: list[str] | None) -> tuple[str, ...]:
    return tuple(value or ())


def _diff_matched_object(
    existing_obj: CatalogObjectRecord,
    incoming_obj: CatalogObjectRecord,
    counts: dict[str, int],
    changes: list[StructureChange],
) -> None:
    if _pk_tuple(existing_obj.primary_key) != _pk_tuple(incoming_obj.primary_key):
        counts["pk_changed"] += 1
        changes.append(
            StructureChange(
                change="pk_changed",
                locator_key=incoming_obj.locator_key or existing_obj.locator_key,
                extra={
                    "from": list(existing_obj.primary_key or []),
                    "to": list(incoming_obj.primary_key or []),
                },
            )
        )

    existing_cols = {c.name: c for c in existing_obj.columns if c.is_present}
    incoming_cols = {c.name: c for c in incoming_obj.columns if c.is_present}

    for name, col in incoming_cols.items():
        prev = existing_cols.get(name)
        if prev is None:
            counts["columns_added"] += 1
            changes.append(
                StructureChange(change="column_added", locator_key=col.locator_key)
            )
            continue
        if prev.data_type != col.data_type:
            counts["type_changed"] += 1
            changes.append(
                StructureChange(
                    change="type_changed",
                    locator_key=col.locator_key,
                    extra={"from": prev.data_type, "to": col.data_type},
                )
            )
        if prev.nullable and not col.nullable:
            counts["nullable_tightened"] += 1
            changes.append(
                StructureChange(
                    change="nullable_tightened",
                    locator_key=col.locator_key,
                    extra={"from": True, "to": False},
                )
            )
        elif (not prev.nullable) and col.nullable:
            counts["nullable_widened"] += 1
            changes.append(
                StructureChange(
                    change="nullable_widened",
                    locator_key=col.locator_key,
                    extra={"from": False, "to": True},
                )
            )
        if (prev.comment or None) != (col.comment or None) or (
            prev.default_value or None
        ) != (col.default_value or None):
            counts["comments_or_defaults"] += 1
            changes.append(
                StructureChange(
                    change="comment_or_default_changed",
                    locator_key=col.locator_key,
                )
            )

    for name, prev in existing_cols.items():
        if name not in incoming_cols:
            counts["columns_removed"] += 1
            changes.append(
                StructureChange(
                    change="column_removed", locator_key=prev.locator_key
                )
            )

    _diff_named(
        existing_present={fk.name for fk in existing_obj.foreign_keys if fk.is_present},
        incoming_present={fk.name for fk in incoming_obj.foreign_keys if fk.is_present},
        locator_key=incoming_obj.locator_key or existing_obj.locator_key,
        added_change="fk_added",
        removed_change="fk_removed",
        changes=changes,
    )
    _diff_named(
        existing_present={
            idx.name for idx in existing_obj.indexes if idx.is_present
        },
        incoming_present={
            idx.name for idx in incoming_obj.indexes if idx.is_present
        },
        locator_key=incoming_obj.locator_key or existing_obj.locator_key,
        added_change="index_added",
        removed_change="index_removed",
        changes=changes,
    )


def _diff_named(
    *,
    existing_present: set[str],
    incoming_present: set[str],
    locator_key: str,
    added_change: str,
    removed_change: str,
    changes: list[StructureChange],
) -> None:
    for name in sorted(incoming_present - existing_present):
        changes.append(
            StructureChange(
                change=added_change,
                locator_key=locator_key,
                extra={"name": name},
            )
        )
    for name in sorted(existing_present - incoming_present):
        changes.append(
            StructureChange(
                change=removed_change,
                locator_key=locator_key,
                extra={"name": name},
            )
        )
