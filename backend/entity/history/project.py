"""Adapt stored change images and project them with the current access policy.

One statement evaluates every candidate side. A side that lacks a rule input,
or whose stored type cannot feed a rule or cell, is unavailable before that
statement. Schema absence is not a SQL NULL.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.core.time import format_instant
from backend.entity.access.compiler import Outcome, Policy, render_shape
from backend.entity.access.dsl import validate_rule
from backend.entity.access.facts import AttrFact, Person
from backend.entity.ddl import EXPOSURE_OWNER_ROLE, ident
from backend.entity.records import AttributeRecord

_SIDE = "refraq_side"


@dataclass(frozen=True, slots=True)
class SideWork:
    """One existing or absent image. ``image`` is None when the operation has no side."""

    key: str
    image: dict[str, Any] | None
    attributes: Sequence[AttributeRecord]
    reference_snapshots: Mapping[str, Any]


def project_sides(
    conn: Connection,
    sides: Sequence[SideWork],
    policy: Policy,
    outcome: Outcome,
    person: Person,
    head_attributes: Sequence[AttributeRecord],
) -> dict[str, tuple[str, dict[str, Any] | None]]:
    """Project each side. States are ``absent``, ``unavailable``, or ``visible``."""
    if outcome.shape is None:
        raise RuntimeError("historical projection requires a subject shape")
    needed = _needed_ids(policy, outcome)
    cells = frozenset(column.attr.attribute_id for column in outcome.columns)
    head_by_id = {
        attr.attribute_id: attr for attr in head_attributes if attr.attribute_id
    }
    result: dict[str, tuple[str, dict[str, Any] | None]] = {}
    candidates: list[_Candidate] = []
    for side in sides:
        if side.image is None:
            result[side.key] = ("absent", None)
            continue
        present, incompatible, values, row_id = _adapt(
            side.image,
            side.attributes,
            policy,
            head_by_id,
            side.reference_snapshots,
        )
        if (needed - present) or (incompatible & (needed | cells)):
            result[side.key] = ("unavailable", None)
            continue
        candidates.append(
            _Candidate(
                key=side.key,
                row_id=row_id,
                values=values,
                present=present,
            )
        )
    if not candidates:
        return result
    found = _query(conn, candidates, policy, outcome, person)
    for item in candidates:
        row = found.get(item.key)
        if row is None:
            result[item.key] = ("unavailable", None)
            continue
        result[item.key] = ("visible", _cells(row, outcome, item.present))
    return result


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


def _compatible(
    historical: AttributeRecord,
    head: AttributeRecord,
    current: AttrFact,
    snapshots: Mapping[str, Any],
) -> bool:
    """Same type, dictionary, and reference-target checks as access ``_compatible``.

    A reference whose stored snapshot key type differs from the current fact
    is also incompatible. That makes the side unavailable; it does not raise.
    """
    if historical.type != head.type:
        return False
    if historical.type == "dictionary" and historical.dictionary_id != head.dictionary_id:
        return False
    if historical.type != "reference":
        return True
    if historical.target_entity_id != head.target_entity_id:
        return False
    return _snapshot_key_type(snapshots, historical.name) == current.reference_key_type


def _snapshot_key_type(snapshots: Mapping[str, Any], name: str) -> str | None:
    ref = snapshots.get(name)
    if not isinstance(ref, dict):
        return None
    kind = ref.get("type")
    return kind if isinstance(kind, str) else None


def _query(
    conn: Connection,
    candidates: Sequence[_Candidate],
    policy: Policy,
    outcome: Outcome,
    person: Person,
) -> dict[str, Any]:
    assert outcome.shape is not None
    names = [fact.name for fact in policy.attributes]
    params: dict[str, Any] = {}
    tuples: list[str] = []
    for index, item in enumerate(candidates):
        side_param = f"sk{index}"
        row_param = f"rk{index}"
        params[side_param] = item.key
        params[row_param] = item.row_id
        slots = [f":{side_param}", f":{row_param}"]
        for column, name in enumerate(names):
            value_param = f"v{index}_{column}"
            params[value_param] = item.values.get(name)
            slots.append(f":{value_param}")
        tuples.append("(" + ", ".join(slots) + ")")
    aliases = ", ".join(
        [ident(_SIDE), ident("row_id"), *(ident(name) for name in names)]
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
        + " FROM (VALUES "
        + ", ".join(tuples)
        + f") AS v({aliases})"
    )
    sql = render_shape(
        outcome.shape,
        replace(policy, source_sql=f"({source})"),
        acl=False,
        person=person,
        subject_values=policy.subject_values.get(person.user_id, {}),
        at=policy.now,
        carry=(_SIDE,),
        bind_subject=True,
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
