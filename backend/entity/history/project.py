"""Adapt stored change images and project them with the current access policy.

A side whose image cannot feed the current shape is unavailable before that
statement. Schema absence is not a SQL NULL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.core.time import format_instant
from backend.entity.access.compiler import Outcome, Policy, render_shape
from backend.entity.access.dsl import validate_rule
from backend.entity.access.facts import AttrFact, Person
from backend.entity.access.masks import CLEAR
from backend.entity.ddl import EXPOSURE_OWNER_ROLE, ident
from backend.entity.records import AttributeRecord

_SIDE = "refraq_side"

SideState = Literal["absent", "unavailable", "visible"]


@dataclass(frozen=True, slots=True)
class HistorySide:
    """One side of a stored change.

    ``absent`` is not part of the operation. ``unavailable`` is not safely
    readable. Only ``visible`` carries ``values``. ``masked`` names attributes
    whose effective presentation is not clear. It stays off ``values`` and
    off the interactive HTTP body.
    """

    state: SideState
    values: dict[str, Any] | None = None
    masked: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SideWork:
    """One existing or absent image. ``image`` is None when the operation has no side."""

    image: dict[str, Any] | None
    attributes: Sequence[AttributeRecord]
    reference_snapshots: Mapping[str, Any]


def project_sides(
    conn: Connection,
    sides: Sequence[SideWork],
    policy: Policy,
    outcome: Outcome,
    person: Person,
) -> tuple[HistorySide, ...]:
    """One result per side, in input order.

    A side feeds the current shape when every attribute that shape consumes
    is present and has the same interpretation as the head. No image is
    ``absent``. A consumed attribute that is missing or whose interpretation
    differs, and a side the shape does not return, are both ``unavailable``.
    Names whose winning grant is not clear stay on ``masked`` and out of
    ``values``.

    ``conn`` is inside a transaction. ``outcome.shape`` is required.
    Head attributes are ``policy.source_attributes``.
    """
    if outcome.shape is None:
        raise RuntimeError("historical projection requires a subject shape")
    needed = _needed_ids(policy, outcome)
    cells = frozenset(column.attr.attribute_id for column in outcome.columns)
    head_by_id = {
        attr.attribute_id: attr
        for attr in policy.source_attributes
        if attr.attribute_id
    }
    slots: dict[int, HistorySide] = {}
    candidates: list[_Candidate] = []
    for index, side in enumerate(sides):
        if side.image is None:
            slots[index] = HistorySide(state="absent")
            continue
        present, incompatible, values, row_id = _adapt(
            side.image,
            side.attributes,
            policy,
            head_by_id,
            side.reference_snapshots,
        )
        if (needed - present) or (incompatible & (needed | cells)):
            slots[index] = HistorySide(state="unavailable")
            continue
        candidates.append(
            _Candidate(
                key=str(index),
                row_id=row_id,
                values=values,
                present=present,
            )
        )
    if candidates:
        found = _query(conn, candidates, policy, outcome, person)
        for item in candidates:
            slot = int(item.key)
            row = found.get(item.key)
            if row is None:
                slots[slot] = HistorySide(state="unavailable")
                continue
            slots[slot] = HistorySide(
                state="visible",
                values=_cells(row, outcome, item.present),
                masked=_masked(row, outcome, item.present),
            )
    return tuple(slots[index] for index in range(len(sides)))


@dataclass(frozen=True, slots=True)
class _Candidate:
    key: str
    row_id: Any
    values: dict[str, Any]
    present: frozenset[str]


def _needed_ids(policy: Policy, outcome: Outcome) -> frozenset[str]:
    shape = outcome.shape
    assert shape is not None
    attrs = {item.attribute_id: item for item in policy.attributes}
    grants = {grant.id: grant for grant in policy.grants}
    needed: set[str] = set()
    for grant_id in outcome.grant_ids:
        needed.update(
            validate_rule(
                grants[grant_id].row_rule, attrs, policy.subject_attrs
            ).attribute_ids
        )
    for rule in shape.row_rules:
        needed.update(validate_rule(rule, attrs, policy.subject_attrs).attribute_ids)
    return frozenset(needed)


def _adapt(
    image: dict[str, Any],
    attributes: Sequence[AttributeRecord],
    policy: Policy,
    head_by_id: Mapping[str, AttributeRecord],
    snapshots: Mapping[str, Any],
) -> tuple[frozenset[str], frozenset[str], dict[str, Any], Any]:
    current_by_id = {fact.attribute_id: fact for fact in policy.attributes}
    present: set[str] = set()
    incompatible: set[str] = set()
    values: dict[str, Any] = {}
    for attr in attributes:
        if not attr.attribute_id:
            continue
        current = current_by_id.get(attr.attribute_id)
        head = head_by_id.get(attr.attribute_id)
        if current is None or head is None:
            continue
        present.add(attr.attribute_id)
        if not _compatible(attr, head, current, snapshots):
            incompatible.add(attr.attribute_id)
            continue
        values[current.name] = image.get(attr.name)
    return frozenset(present), frozenset(incompatible), values, image.get("row_id")


def _interpretation(
    attr: AttributeRecord, key_type: str | None
) -> tuple[str, str | None, str | None, str | None]:
    """Type, dictionary, reference target, and key type, compared as one value."""
    return (attr.type, attr.dictionary_id, attr.target_entity_id, key_type)


def _compatible(
    historical: AttributeRecord,
    head: AttributeRecord,
    current: AttrFact,
    snapshots: Mapping[str, Any],
) -> bool:
    """True when the stored attribute and the head read as the same value.

    A mismatch makes the side unavailable when that attribute feeds a rule
    or a cell. It does not raise.
    """
    return _interpretation(
        historical, _snapshot_key_type(snapshots, historical.name)
    ) == _interpretation(head, current.reference_key_type)


def _snapshot_key_type(snapshots: Mapping[str, Any], name: str) -> str | None:
    ref = snapshots.get(name)
    if not isinstance(ref, dict):
        return None
    kind = ref.get("type")
    return kind if isinstance(kind, str) else None


def _json_param(value: Any) -> str:
    """Text form of a value ``json.dumps`` cannot emit on its own.

    Decoded change images are already JSON values. A decimal or instant that
    arrives as a Python object stays exact: a decimal is not a binary float,
    and an instant keeps its microseconds.
    """
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return format_instant(value, timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    raise TypeError(
        f"historical projection cannot encode {type(value).__name__}"
    )


def _query(
    conn: Connection,
    candidates: Sequence[_Candidate],
    policy: Policy,
    outcome: Outcome,
    person: Person,
) -> dict[str, Any]:
    """Send every candidate as one JSON payload.

    Binding each cell would exceed PostgreSQL's 65535-parameter limit on a
    wide page.
    """
    assert outcome.shape is not None
    names = [fact.name for fact in policy.attributes]
    payload = json.dumps(
        [
            {
                _SIDE: item.key,
                "row_id": None if item.row_id is None else str(item.row_id),
                **{name: item.values.get(name) for name in names},
            }
            for item in candidates
        ],
        default=_json_param,
    )
    fields = ", ".join(
        [
            f"{ident(_SIDE)} text",
            f"{ident('row_id')} text",
            *(f"{ident(name)} text" for name in names),
        ]
    )
    casts = [
        f"v.{ident(_SIDE)} AS {ident(_SIDE)}",
        f"CAST(v.{ident('row_id')} AS bigint) AS {ident('row_id')}",
    ]
    for fact in policy.attributes:
        casts.append(
            f"CAST(v.{ident(fact.name)} AS {fact.pg_type()}) AS {ident(fact.name)}"
        )
    source = (
        "SELECT "
        + ", ".join(casts)
        + " FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS v("
        + fields
        + ")"
    )
    params = {"payload": payload}
    sql = render_shape(
        outcome.shape,
        replace(policy, source_sql=f"({source})"),
        acl=False,
        person=person,
        subject_values=policy.subject_values.get(person.user_id, {}),
        at=policy.now,
        carry=(_SIDE,),
        bind_subject=True,
        grant_flags=True,
    )
    conn.exec_driver_sql(f"SET LOCAL ROLE {ident(EXPOSURE_OWNER_ROLE)}")
    try:
        rows = list(conn.execute(text(sql), params).mappings())
    finally:
        conn.exec_driver_sql("RESET ROLE")
    return {str(row[_SIDE]): row for row in rows}


def _cells(
    row: Any, outcome: Outcome, present: frozenset[str]
) -> dict[str, Any]:
    present_names = {
        column.attr.name
        for column in outcome.columns
        if column.attr.attribute_id in present
    }
    values: dict[str, Any] = {"row_id": _json(row["row_id"])}
    for column in outcome.columns:
        if column.attr.attribute_id not in present:
            continue
        values[column.attr.name] = _json(row[column.attr.name])
    if outcome.withheld_field:
        raw = row.get("__withheld") or []
        values["__withheld"] = [
            str(name) for name in list(raw) if str(name) in present_names
        ]
    return values


def _masked(row: Any, outcome: Outcome, present: frozenset[str]) -> frozenset[str]:
    """Attribute names whose winning grant mode is not clear.

    ``grant_modes`` is clearest first, matching the projection CASE. A grant
    counts only when its flag produced this row, so a clear grant that did
    not match does not hide a mask, and a mask grant that did not match does
    not hide a clear value.
    """
    flags = {
        str(key).removeprefix("__g_"): bool(value)
        for key, value in row.items()
        if str(key).startswith("__g_")
    }
    names: list[str] = []
    for column in outcome.columns:
        if column.attr.attribute_id not in present:
            continue
        matching = [
            mode
            for grant_id, mode in column.grant_modes
            if flags.get(grant_id)
        ]
        if matching and matching[0] != CLEAR:
            names.append(column.attr.name)
    return frozenset(names)


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return format_instant(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    return value
