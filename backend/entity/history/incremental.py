"""Single-connection SQL planning and execution for incremental Change Log reads.

``NoSides`` dataset materialization executes entirely inside PostgreSQL via
``WITH ... INSERT INTO "channel_dataset"."ds_<id>" SELECT ...`` with zero
Python cell shuttling. ``WithSides`` fuses Change Log JSONB extraction and
``render_shape`` on the connection and reuses Python cell formatting so all
13 Attribute Types keep one canonical wire representation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.core.time import format_instant
from backend.entity.access.compiler import Outcome, Policy, Shape, render_shape
from backend.entity.access.dsl import validate_rule
from backend.entity.access.facts import AttrFact, Person
from backend.entity.access.masks import CLEAR
from backend.entity.attribute_type import resolve
from backend.entity.change_log import CHANGE_LOG_SCHEMA, ENTRY_TABLE, ChangeLogTable
from backend.entity.ddl import ident, qualified_table
from backend.entity.errors import EntityNotServing
from backend.entity.history.project import (
    HistorySide,
    _Candidate,
    _cells,
    _compatible,
    _masked,
    _query,
)
from backend.entity.records import AttributeRecord

ChangesDatasetColumn = Literal[
    "sequence",
    "operation",
    "occurred_at",
    "source",
    "subject",
    "physical_table",
    "version_id",
    "version_number",
    "row_id",
    "business_key",
    "before",
    "after",
]

CHANGES_DATASET_COLUMNS: tuple[ChangesDatasetColumn, ...] = (
    "sequence",
    "operation",
    "occurred_at",
    "source",
    "subject",
    "physical_table",
    "version_id",
    "version_number",
    "row_id",
    "business_key",
    "before",
    "after",
)

DATASET_COLUMN_PG_TYPES: dict[str, str] = {
    "sequence": "bigint",
    "operation": "text",
    "occurred_at": "text",
    "source": "text",
    "subject": "text",
    "physical_table": "text",
    "version_id": "text",
    "version_number": "bigint",
    "row_id": "bigint",
    "business_key": "jsonb",
    "before": "jsonb",
    "after": "jsonb",
}

_ENTITY_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NAME_MAX = 63
_SERVING_HEAD_PREDATES = (
    "Serving head predates reference snapshots; publish a new version"
)
_CARRY_RN = "__chg_rn"
_CARRY_SIDE = "__chg_side"
_CARRY_PT = "__chg_pt"


@dataclass(frozen=True, slots=True)
class VersionMeta:
    version_id: str
    version_number: int
    table: ChangeLogTable


@dataclass(frozen=True, slots=True)
class _VersionPlan:
    physical_table: str
    version_id: str
    version_number: int
    unserving: bool
    compatible: bool
    present_ids: frozenset[str]
    hist_attr_by_id: Mapping[str, AttributeRecord]
    physical_sql_by_id: Mapping[str, str]
    projected_key_name: str | None
    clear_key_attr_id: str | None


@dataclass(frozen=True, slots=True)
class IncrementalPlan:
    policy: Policy
    outcome: Outcome
    person: Person
    active_ids: frozenset[str]
    columns: tuple[ChangesDatasetColumn, ...]
    want_sides: bool
    want_row_id: bool
    want_business_key: bool
    has_hash_mask: bool
    extract_facts: tuple[AttrFact, ...]
    pruned_shape: Shape
    pruned_outcome: Outcome
    versions: Mapping[str, _VersionPlan]
    known_tables: tuple[str, ...]
    unserving_tables: tuple[str, ...]
    compat_tables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IncrementalEvent:
    """One eligible consumption event, in commit order.

    ``physical_table`` stays so a later consumer can group the stored version.
    ``business_key_name`` is the projected name of the Business Key that
    version declares. It is none when that version declares no Business Key.
    """

    sequence: int
    commit_seq: int
    operation: str
    occurred_at: str
    source: str | None
    subject: str | None
    physical_table: str
    version_id: str
    version_number: int
    before: HistorySide
    after: HistorySide
    business_key_name: str | None = None


@dataclass(frozen=True, slots=True)
class PageScanSummary:
    scanned_count: int
    last_commit_seq: int | None
    last_seq: int | None
    has_more: bool


def normalize_dataset_columns(
    columns: Sequence[str] | None,
) -> tuple[ChangesDatasetColumn, ...]:
    """Canonical ordered subset of ``CHANGES_DATASET_COLUMNS``.

    ``None`` or empty selects all 12 canonical columns.
    """
    if not columns:
        return CHANGES_DATASET_COLUMNS
    wanted = {str(name) for name in columns}
    unknown = wanted - set(CHANGES_DATASET_COLUMNS)
    if unknown:
        bad = ", ".join(sorted(unknown))
        raise ValueError(f"unknown Changes Dataset column(s): {bad}")
    return tuple(col for col in CHANGES_DATASET_COLUMNS if col in wanted)


def compile_incremental_plan(
    *,
    policy: Policy,
    outcome: Outcome,
    person: Person,
    versions: Mapping[str, VersionMeta],
    columns: Sequence[str] | None = None,
) -> IncrementalPlan:
    """Build static per-version and shape plans for one policy snapshot."""
    if outcome.shape is None:
        raise RuntimeError("incremental projection requires a subject shape")
    selected = normalize_dataset_columns(columns)
    col_set = frozenset(selected)
    want_sides = ("before" in col_set) or ("after" in col_set)
    want_row_id = want_sides or ("row_id" in col_set)
    want_business_key = want_sides or ("business_key" in col_set)

    active_ids = frozenset(outcome.grant_ids)
    needed_ids = _needed_ids(policy, outcome)
    outcome_ids = frozenset(col.attr.attribute_id for col in outcome.columns)
    current_by_id = {fact.attribute_id: fact for fact in policy.attributes}
    head_by_id = {
        attr.attribute_id: attr
        for attr in policy.source_attributes
        if attr.attribute_id
    }
    col_by_id = {col.attr.attribute_id: col for col in outcome.columns}

    v_plans: dict[str, _VersionPlan] = {}
    for physical, meta in versions.items():
        vp = _build_version_plan(
            meta=meta,
            policy=policy,
            current_by_id=current_by_id,
            head_by_id=head_by_id,
            col_by_id=col_by_id,
            active_ids=active_ids,
            needed_ids=needed_ids,
            outcome_ids=outcome_ids,
        )
        v_plans[physical] = vp

    if want_sides:
        extract_ids = needed_ids | outcome_ids
        narrowed_cols = tuple(
            replace(
                col,
                grant_modes=tuple(
                    (gid, mode)
                    for gid, mode in col.grant_modes
                    if gid in active_ids
                ),
            )
            for col in outcome.columns
        )
        has_hash = any(
            isinstance(mode, dict) and mode.get("type") == "hash"
            for col in narrowed_cols
            for _gid, mode in col.grant_modes
        )
    else:
        bk_ids = (
            frozenset(
                vp.clear_key_attr_id
                for vp in v_plans.values()
                if vp.compatible and not vp.unserving and vp.clear_key_attr_id is not None
            )
            if want_business_key
            else frozenset()
        )
        extract_ids = needed_ids | bk_ids
        narrowed_cols = tuple(
            replace(
                col,
                grant_modes=tuple(
                    (gid, CLEAR if mode == CLEAR else {"type": "null"})
                    for gid, mode in col.grant_modes
                    if gid in active_ids
                ),
            )
            for col in outcome.columns
            if col.attr.attribute_id in bk_ids
        )
        has_hash = False

    shape = outcome.shape
    withheld = (
        any(col.row_varying for col in narrowed_cols)
        and len(shape.profile_ids) > 1
    )
    pruned_shape = replace(
        shape,
        grants=tuple(g for g in shape.grants if g.id in active_ids),
        columns=narrowed_cols,
        withheld=withheld,
    )
    pruned_outcome = replace(
        outcome,
        columns=narrowed_cols,
        withheld_field="__withheld" if withheld else None,
        shape=pruned_shape,
    )
    extract_facts = tuple(
        fact for fact in policy.attributes if fact.attribute_id in extract_ids
    )
    known_tables = tuple(v_plans.keys())
    unserving_tables = tuple(
        pt for pt, vp in v_plans.items() if vp.unserving
    )
    compat_tables = tuple(
        pt for pt, vp in v_plans.items() if vp.compatible and not vp.unserving
    )
    return IncrementalPlan(
        policy=policy,
        outcome=outcome,
        person=person,
        active_ids=active_ids,
        columns=selected,
        want_sides=want_sides,
        want_row_id=want_row_id,
        want_business_key=want_business_key,
        has_hash_mask=has_hash,
        extract_facts=extract_facts,
        pruned_shape=pruned_shape,
        pruned_outcome=pruned_outcome,
        versions=v_plans,
        known_tables=known_tables,
        unserving_tables=unserving_tables,
        compat_tables=compat_tables,
    )


def execute_nosides_dataset_page(
    conn: Connection,
    plan: IncrementalPlan,
    *,
    entity_id: str,
    relation: str,
    after_commit: int | None,
    bound_commit: int,
    page_limit: int,
    base_ord: int,
    sources: Collection[str] | None = None,
) -> tuple[PageScanSummary, int]:
    """Execute one page directly into ``relation`` without returning rows to Python."""
    assert not plan.want_sides
    validated_entity = _validate_entity_id(entity_id)
    params: dict[str, Any] = {}
    cte_prefix = _common_ctes(
        plan,
        params,
        entity_id=validated_entity,
        after_commit=after_commit,
        bound_commit=bound_commit,
        page_limit=page_limit,
        sources=sources,
    )
    shape_sql = render_shape(
        plan.pruned_shape,
        replace(plan.policy, source_sql="typed_sides"),
        acl=False,
        active=plan.active_ids,
        person=plan.person,
        subject_values=plan.policy.subject_values.get(plan.person.user_id, {}),
        at=plan.policy.now,
        carry=(_CARRY_RN, _CARRY_SIDE, _CARRY_PT),
        bind_subject=True,
        grant_flags=True,
    )
    clear_bk_expr = _clear_bk_sql(plan, params)
    version_id_expr, version_num_expr = _version_meta_sql(plan, params)
    params["base_ord"] = int(base_ord)

    insert_cols = [ident("_ord"), *(ident(col) for col in plan.columns)]
    select_exprs = [f":base_ord + row_number() OVER (ORDER BY e.rn)"]
    for col in plan.columns:
        select_exprs.append(_nosides_column_expr(col))

    sql = (
        f"{cte_prefix},\n"
        f"projected_sides AS (\n{shape_sql}\n),\n"
        "side_summary AS (\n"
        f"  SELECT p.{ident(_CARRY_RN)} AS rn, p.{ident(_CARRY_SIDE)} AS side_kind, "
        f"p.{ident('row_id')} AS row_id, {clear_bk_expr} AS clear_bk\n"
        "  FROM projected_sides AS p\n"
        "),\n"
        "eligible AS (\n"
        "  SELECT\n"
        "    k.rn,\n"
        "    k.seq,\n"
        "    k.operation,\n"
        "    k.occurred_at,\n"
        "    k.source,\n"
        "    k.subject,\n"
        "    k.physical_table,\n"
        f"    {version_id_expr} AS version_id,\n"
        f"    {version_num_expr} AS version_number,\n"
        "    (b.rn IS NOT NULL) AS b_present,\n"
        "    (a.rn IS NOT NULL) AS a_present,\n"
        "    b.row_id AS b_row_id,\n"
        "    a.row_id AS a_row_id,\n"
        "    b.clear_bk AS b_bk,\n"
        "    a.clear_bk AS a_bk\n"
        "  FROM kept AS k\n"
        "  LEFT JOIN side_summary AS b ON b.rn = k.rn AND b.side_kind = 0\n"
        "  LEFT JOIN side_summary AS a ON a.rn = k.rn AND a.side_kind = 1\n"
        "  WHERE b.rn IS NOT NULL OR a.rn IS NOT NULL\n"
        "),\n"
        "ins AS (\n"
        f"  INSERT INTO {relation} ({', '.join(insert_cols)})\n"
        f"  SELECT {', '.join(select_exprs)}\n"
        "  FROM eligible AS e\n"
        "  ORDER BY e.rn\n"
        "  RETURNING 1\n"
        ")\n"
        "SELECT\n"
        "  sum_cte.__sum_fetched,\n"
        "  sum_cte.__sum_cseq,\n"
        "  sum_cte.__sum_seq,\n"
        "  sum_cte.__sum_unk,\n"
        "  sum_cte.__sum_unserv,\n"
        "  sum_cte.__sum_bad_img,\n"
        "  sum_cte.__sum_miss_after,\n"
        "  sum_cte.__sum_miss_before,\n"
        "  (SELECT count(*) FROM ins) AS __sum_inserted\n"
        "FROM summary AS sum_cte"
    )
    row = conn.execute(text(sql), params).mappings().one()
    summary = _parse_summary(row, page_limit=page_limit)
    return summary, int(row["__sum_inserted"])


def execute_with_sides_page(
    conn: Connection,
    plan: IncrementalPlan,
    *,
    entity_id: str,
    after_commit: int | None,
    bound_commit: int,
    page_limit: int,
    sources: Collection[str] | None = None,
) -> tuple[PageScanSummary, list[IncrementalEvent]]:
    """Execute one page returning projected ``IncrementalEvent`` objects."""
    validated_entity = _validate_entity_id(entity_id)
    params: dict[str, Any] = {}
    cte_prefix = _common_ctes(
        plan,
        params,
        entity_id=validated_entity,
        after_commit=after_commit,
        bound_commit=bound_commit,
        page_limit=page_limit,
        sources=sources,
    )
    if not plan.has_hash_mask:
        shape_sql = render_shape(
            plan.pruned_shape,
            replace(plan.policy, source_sql="typed_sides"),
            acl=False,
            active=plan.active_ids,
            person=plan.person,
            subject_values=plan.policy.subject_values.get(plan.person.user_id, {}),
            at=plan.policy.now,
            carry=(_CARRY_RN, _CARRY_SIDE, _CARRY_PT),
            bind_subject=True,
            grant_flags=True,
        )
        sql = (
            f"{cte_prefix},\n"
            f"projected_sides AS (\n{shape_sql}\n),\n"
            "kept_sides AS (\n"
            "  SELECT\n"
            "    k.seq AS __k_seq,\n"
            "    k.commit_seq AS __k_cseq,\n"
            "    k.operation AS __k_op,\n"
            "    k.occurred_at AS __k_at,\n"
            "    k.source AS __k_src,\n"
            "    k.subject AS __k_subj,\n"
            "    p.*\n"
            "  FROM kept AS k\n"
            f"  JOIN projected_sides AS p ON p.{ident(_CARRY_RN)} = k.rn\n"
            ")\n"
            "SELECT\n"
            "  sum_cte.__sum_fetched,\n"
            "  sum_cte.__sum_cseq,\n"
            "  sum_cte.__sum_seq,\n"
            "  sum_cte.__sum_unk,\n"
            "  sum_cte.__sum_unserv,\n"
            "  sum_cte.__sum_bad_img,\n"
            "  sum_cte.__sum_miss_after,\n"
            "  sum_cte.__sum_miss_before,\n"
            "  ks.*\n"
            "FROM summary AS sum_cte\n"
            "LEFT JOIN kept_sides AS ks ON TRUE\n"
            f"ORDER BY ks.{ident(_CARRY_RN)}, ks.{ident(_CARRY_SIDE)}"
        )
        rows = list(conn.execute(text(sql), params).mappings())
        summary = _parse_summary(rows[0], page_limit=page_limit)
        if rows[0][_CARRY_RN] is None:
            return summary, []
        return summary, _events_from_projected_rows(rows, plan)

    # Rare path: active hash mask requires EXPOSURE_OWNER_ROLE for acl.mask_hash.
    sql = (
        f"{cte_prefix},\n"
        "kept_sides AS (\n"
        "  SELECT\n"
        "    k.seq AS __k_seq,\n"
        "    k.commit_seq AS __k_cseq,\n"
        "    k.operation AS __k_op,\n"
        "    k.occurred_at AS __k_at,\n"
        "    k.source AS __k_src,\n"
        "    k.subject AS __k_subj,\n"
        "    ts.*\n"
        "  FROM kept AS k\n"
        f"  JOIN typed_sides AS ts ON ts.{ident(_CARRY_RN)} = k.rn\n"
        ")\n"
        "SELECT\n"
        "  sum_cte.__sum_fetched,\n"
        "  sum_cte.__sum_cseq,\n"
        "  sum_cte.__sum_seq,\n"
        "  sum_cte.__sum_unk,\n"
        "  sum_cte.__sum_unserv,\n"
        "  sum_cte.__sum_bad_img,\n"
        "  sum_cte.__sum_miss_after,\n"
        "  sum_cte.__sum_miss_before,\n"
        "  ks.*\n"
        "FROM summary AS sum_cte\n"
        "LEFT JOIN kept_sides AS ks ON TRUE\n"
        f"ORDER BY ks.{ident(_CARRY_RN)}, ks.{ident(_CARRY_SIDE)}"
    )
    rows = list(conn.execute(text(sql), params).mappings())
    summary = _parse_summary(rows[0], page_limit=page_limit)
    if rows[0][_CARRY_RN] is None:
        return summary, []
    return summary, _events_via_exposure_role(conn, rows, plan)


def format_dataset_rows(
    events: Sequence[IncrementalEvent],
    columns: Sequence[ChangesDatasetColumn],
) -> list[tuple[Any, ...]]:
    """Serialize visible ``IncrementalEvent`` rows for ``COPY`` in ``columns`` order."""
    out: list[tuple[Any, ...]] = []
    for ev in events:
        cells: list[Any] = []
        for col in columns:
            if col == "sequence":
                cells.append(ev.sequence)
            elif col == "operation":
                cells.append(ev.operation)
            elif col == "occurred_at":
                cells.append(ev.occurred_at)
            elif col == "source":
                cells.append(ev.source)
            elif col == "subject":
                cells.append(ev.subject)
            elif col == "physical_table":
                cells.append(ev.physical_table)
            elif col == "version_id":
                cells.append(ev.version_id)
            elif col == "version_number":
                cells.append(ev.version_number)
            elif col == "row_id":
                cells.append(_agreed(ev, "row_id", _integer_cell))
            elif col == "business_key":
                cells.append(_json_text(_agreed(ev, ev.business_key_name, _clear_cell)))
            elif col == "before":
                cells.append(_json_text(_wire_side(ev.before)))
            elif col == "after":
                cells.append(_json_text(_wire_side(ev.after)))
        out.append(tuple(cells))
    return out


def _wire_side(side: HistorySide) -> dict[str, Any]:
    if side.state != "visible":
        return {"state": side.state}
    return {"state": "visible", "values": side.values}


def _clear_cell(side: HistorySide, name: str) -> Any:
    if side.state != "visible" or side.values is None:
        return None
    if name in side.masked or name not in side.values:
        return None
    withheld = side.values.get("__withheld")
    if isinstance(withheld, list) and name in {str(item) for item in withheld}:
        return None
    return side.values[name]


def _integer_cell(side: HistorySide, name: str) -> int | None:
    value = _clear_cell(side, name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _agreed(
    ev: IncrementalEvent,
    name: str | None,
    extractor: Callable[[HistorySide, str], Any],
) -> Any:
    if not name:
        return None
    found: list[Any] = []
    for side in (ev.before, ev.after):
        if side.state != "visible":
            continue
        value = extractor(side, name)
        if value is None:
            return None
        found.append(value)
    if not found or any(item != found[0] for item in found[1:]):
        return None
    return found[0]


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _events_from_projected_rows(
    rows: Sequence[Mapping[str, Any]],
    plan: IncrementalPlan,
) -> list[IncrementalEvent]:
    grouped: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    for row in rows:
        rn = int(row[_CARRY_RN])
        side_kind = int(row[_CARRY_SIDE])
        pt = str(row[_CARRY_PT])
        vp = plan.versions[pt]
        built = HistorySide(
            state="visible",
            values=_cells(row, plan.pruned_outcome, vp.present_ids),
            masked=_masked(row, plan.pruned_outcome, vp.present_ids),
        )
        bucket = grouped.get(rn)
        if bucket is None:
            bucket = {"meta": row, "pt": pt, 0: None, 1: None}
            grouped[rn] = bucket
            order.append(rn)
        bucket[side_kind] = built
    return _assemble_events(order, grouped, plan)


def _events_via_exposure_role(
    conn: Connection,
    rows: Sequence[Mapping[str, Any]],
    plan: IncrementalPlan,
) -> list[IncrementalEvent]:
    candidates: list[_Candidate] = []
    meta_by_rn: dict[int, tuple[Mapping[str, Any], str]] = {}
    order: list[int] = []
    names = [fact.name for fact in plan.policy.attributes]
    for row in rows:
        rn = int(row[_CARRY_RN])
        side_kind = int(row[_CARRY_SIDE])
        pt = str(row[_CARRY_PT])
        vp = plan.versions[pt]
        if rn not in meta_by_rn:
            meta_by_rn[rn] = (row, pt)
            order.append(rn)
        candidates.append(
            _Candidate(
                key=f"{rn}:{side_kind}",
                row_id=row["row_id"],
                values={name: row.get(name) for name in names},
                present=vp.present_ids,
            )
        )
    found = _query(
        conn,
        candidates,
        plan.policy,
        plan.pruned_outcome,
        plan.person,
    )
    grouped: dict[int, dict[str, Any]] = {}
    for rn in order:
        meta_row, pt = meta_by_rn[rn]
        vp = plan.versions[pt]
        b_row = found.get(f"{rn}:0")
        a_row = found.get(f"{rn}:1")
        if b_row is None and a_row is None:
            continue
        grouped[rn] = {
            "meta": meta_row,
            "pt": pt,
            0: (
                None
                if b_row is None
                else HistorySide(
                    state="visible",
                    values=_cells(b_row, plan.pruned_outcome, vp.present_ids),
                    masked=_masked(b_row, plan.pruned_outcome, vp.present_ids),
                )
            ),
            1: (
                None
                if a_row is None
                else HistorySide(
                    state="visible",
                    values=_cells(a_row, plan.pruned_outcome, vp.present_ids),
                    masked=_masked(a_row, plan.pruned_outcome, vp.present_ids),
                )
            ),
        }
    return _assemble_events([rn for rn in order if rn in grouped], grouped, plan)


def _assemble_events(
    order: Sequence[int],
    grouped: Mapping[int, Mapping[str, Any]],
    plan: IncrementalPlan,
) -> list[IncrementalEvent]:
    events: list[IncrementalEvent] = []
    for rn in order:
        bucket = grouped[rn]
        meta = bucket["meta"]
        pt = str(bucket["pt"])
        vp = plan.versions[pt]
        op = str(meta["__k_op"])
        b_side: HistorySide | None = bucket[0]
        a_side: HistorySide | None = bucket[1]
        if b_side is None:
            b_side = HistorySide(
                state="absent" if op == "insert" else "unavailable"
            )
        if a_side is None:
            a_side = HistorySide(
                state="absent" if op == "delete" else "unavailable"
            )
        events.append(
            IncrementalEvent(
                sequence=int(meta["__k_seq"]),
                commit_seq=int(meta["__k_cseq"]),
                operation=op,
                occurred_at=format_instant(meta["__k_at"]),
                source=None if meta["__k_src"] is None else str(meta["__k_src"]),
                subject=None if meta["__k_subj"] is None else str(meta["__k_subj"]),
                physical_table=pt,
                version_id=vp.version_id,
                version_number=vp.version_number,
                before=b_side,
                after=a_side,
                business_key_name=vp.projected_key_name,
            )
        )
    return events


def _common_ctes(
    plan: IncrementalPlan,
    params: dict[str, Any],
    *,
    entity_id: str,
    after_commit: int | None,
    bound_commit: int,
    page_limit: int,
    sources: Collection[str] | None,
) -> str:
    if page_limit < 1:
        raise ValueError("page_limit must be at least 1")
    entry_table = qualified_table(CHANGE_LOG_SCHEMA, ENTRY_TABLE)
    clauses = [
        "e.entity_id = :entity_id",
        "e.commit_seq IS NOT NULL",
        "e.commit_seq <= :bound_commit",
    ]
    params["entity_id"] = entity_id
    params["bound_commit"] = int(bound_commit)
    params["fetch_limit"] = int(page_limit) + 1
    params["page_limit"] = int(page_limit)
    params["known_tables"] = list(plan.known_tables)
    params["unserving_tables"] = list(plan.unserving_tables)
    params["compat_tables"] = list(plan.compat_tables)
    if after_commit is not None:
        clauses.append("e.commit_seq > :after_commit")
        params["after_commit"] = int(after_commit)

    source_filter = ""
    if sources is not None:
        params["sources"] = [str(item) for item in sources]
        source_filter = (
            "\n    AND COALESCE(s.source, 'unattributed') = ANY(CAST(:sources AS text[]))"
        )

    typed_cols = [
        f"rs.rn AS {ident(_CARRY_RN)}",
        f"rs.side_kind AS {ident(_CARRY_SIDE)}",
        f"rs.physical_table AS {ident(_CARRY_PT)}",
        f"{_row_id_sql(plan.want_row_id)} AS {ident('row_id')}",
    ]
    for f_idx, fact in enumerate(plan.extract_facts):
        expr = _typed_attr_sql(plan, fact, f_idx, params)
        typed_cols.append(f"{expr} AS {ident(fact.name)}")

    return (
        "WITH fetched AS (\n"
        "  SELECT\n"
        "    row_number() OVER (ORDER BY e.commit_seq) AS rn,\n"
        "    e.entity_id,\n"
        "    e.physical_table,\n"
        "    e.operation,\n"
        "    e.seq,\n"
        "    e.occurred_at,\n"
        "    e.source,\n"
        "    e.subject,\n"
        "    e.image,\n"
        "    e.commit_seq\n"
        f"  FROM {entry_table} AS e\n"
        f"  WHERE {' AND '.join(clauses)}\n"
        "  ORDER BY e.commit_seq\n"
        "  LIMIT :fetch_limit\n"
        "),\n"
        "scanned AS (\n"
        "  SELECT * FROM fetched WHERE rn <= :page_limit\n"
        "),\n"
        "summary AS (\n"
        "  SELECT\n"
        "    (SELECT count(*) FROM fetched) AS __sum_fetched,\n"
        "    (SELECT s.commit_seq FROM scanned AS s ORDER BY s.rn DESC LIMIT 1) AS __sum_cseq,\n"
        "    (SELECT s.seq FROM scanned AS s ORDER BY s.rn DESC LIMIT 1) AS __sum_seq,\n"
        "    (SELECT s.physical_table FROM scanned AS s "
        "WHERE NOT (s.physical_table = ANY(CAST(:known_tables AS text[]))) "
        "ORDER BY s.rn LIMIT 1) AS __sum_unk,\n"
        "    (SELECT count(*) FROM scanned AS s "
        "WHERE s.physical_table = ANY(CAST(:unserving_tables AS text[]))) AS __sum_unserv,\n"
        "    (SELECT count(*) FROM scanned AS s "
        "WHERE s.image IS NULL OR jsonb_typeof(s.image) <> 'object') AS __sum_bad_img,\n"
        "    (SELECT count(*) FROM scanned AS s "
        "WHERE jsonb_typeof(s.image) = 'object' AND s.operation IN ('insert', 'update') "
        "AND (NOT jsonb_exists(s.image, 'after') OR jsonb_typeof(s.image -> 'after') <> 'object')) AS __sum_miss_after,\n"
        "    (SELECT count(*) FROM scanned AS s "
        "WHERE jsonb_typeof(s.image) = 'object' AND s.operation = 'delete' "
        "AND (NOT jsonb_exists(s.image, 'before') OR jsonb_typeof(s.image -> 'before') <> 'object')) AS __sum_miss_before\n"
        "),\n"
        "kept AS (\n"
        "  SELECT s.*\n"
        "  FROM scanned AS s\n"
        "  WHERE s.physical_table = ANY(CAST(:compat_tables AS text[]))\n"
        "    AND jsonb_typeof(s.image) = 'object'\n"
        "    AND (\n"
        "      (s.operation IN ('insert', 'update') AND jsonb_exists(s.image, 'after') AND jsonb_typeof(s.image -> 'after') = 'object')\n"
        "      OR (s.operation = 'delete' AND jsonb_exists(s.image, 'before') AND jsonb_typeof(s.image -> 'before') = 'object')\n"
        f"    ){source_filter}\n"
        "),\n"
        "raw_sides AS (\n"
        "  SELECT k.rn, 0 AS side_kind, k.physical_table, k.operation, k.image\n"
        "  FROM kept AS k\n"
        "  WHERE k.operation IN ('delete', 'update')\n"
        "  UNION ALL\n"
        "  SELECT k.rn, 1 AS side_kind, k.physical_table, k.operation, k.image\n"
        "  FROM kept AS k\n"
        "  WHERE k.operation IN ('insert', 'update')\n"
        "),\n"
        "typed_sides AS (\n"
        f"  SELECT {', '.join(typed_cols)}\n"
        "  FROM raw_sides AS rs\n"
        ")"
    )


def _row_id_sql(want_row_id: bool) -> str:
    if not want_row_id:
        return "CAST(NULL AS bigint)"
    raw = _extract_text_expr("'row_id'")
    return f"CAST(({raw}) AS bigint)"


def _typed_attr_sql(
    plan: IncrementalPlan,
    fact: AttrFact,
    fact_index: int,
    params: dict[str, Any],
) -> str:
    head_pg = fact.pg_type()
    branches: list[str] = []
    for v_idx, pt in enumerate(plan.compat_tables):
        vp = plan.versions[pt]
        hist_attr = vp.hist_attr_by_id.get(fact.attribute_id)
        if hist_attr is None:
            continue
        pt_param = f"vt_{v_idx}"
        params.setdefault(pt_param, pt)
        key_param = f"hk_{fact_index}_{v_idx}"
        params[key_param] = hist_attr.name
        if fact.type == "json":
            sub = _extract_json_expr(f":{key_param}")
            cast_val = (
                f"CASE WHEN ({sub}) IS NULL OR jsonb_typeof({sub}) = 'null' "
                f"THEN CAST(NULL AS jsonb) ELSE ({sub}) END"
            )
        else:
            raw_txt = _extract_text_expr(f":{key_param}")
            v_phys = vp.physical_sql_by_id[fact.attribute_id]
            cast_val = f"CAST(CAST(({raw_txt}) AS {v_phys}) AS {head_pg})"
        branches.append(f"WHEN rs.physical_table = :{pt_param} THEN {cast_val}")
    if not branches:
        return f"CAST(NULL AS {head_pg})"
    return f"CASE {' '.join(branches)} ELSE CAST(NULL AS {head_pg}) END"


def _extract_text_expr(key_sql: str) -> str:
    return (
        "CASE "
        f"WHEN rs.side_kind = 1 THEN rs.image -> 'after' ->> {key_sql} "
        f"WHEN rs.operation = 'delete' THEN rs.image -> 'before' ->> {key_sql} "
        "WHEN rs.image -> 'changed' IS NOT NULL "
        "AND jsonb_typeof(rs.image -> 'changed') = 'object' "
        f"AND jsonb_exists(rs.image -> 'changed', {key_sql}) "
        f"THEN rs.image -> 'changed' ->> {key_sql} "
        f"ELSE rs.image -> 'after' ->> {key_sql} "
        "END"
    )


def _extract_json_expr(key_sql: str) -> str:
    return (
        "CASE "
        f"WHEN rs.side_kind = 1 THEN rs.image -> 'after' -> {key_sql} "
        f"WHEN rs.operation = 'delete' THEN rs.image -> 'before' -> {key_sql} "
        "WHEN rs.image -> 'changed' IS NOT NULL "
        "AND jsonb_typeof(rs.image -> 'changed') = 'object' "
        f"AND jsonb_exists(rs.image -> 'changed', {key_sql}) "
        f"THEN rs.image -> 'changed' -> {key_sql} "
        f"ELSE rs.image -> 'after' -> {key_sql} "
        "END"
    )


def _clear_bk_sql(plan: IncrementalPlan, params: dict[str, Any]) -> str:
    if not plan.want_business_key:
        return "CAST(NULL AS jsonb)"
    col_by_id = {col.attr.attribute_id: col for col in plan.outcome.columns}
    branches: list[str] = []
    for v_idx, pt in enumerate(plan.compat_tables):
        vp = plan.versions[pt]
        if vp.clear_key_attr_id is None:
            continue
        orig_col = col_by_id[vp.clear_key_attr_id]
        clear_flags = [
            f"p.{ident('__g_' + gid)}"
            for gid, mode in orig_col.grant_modes
            if gid in plan.active_ids and mode == CLEAR
        ]
        if not clear_flags:
            continue
        pt_param = f"vt_{v_idx}"
        params.setdefault(pt_param, pt)
        bk_col = f"p.{ident(orig_col.attr.name)}"
        cond = f"({' OR '.join(clear_flags)}) AND {bk_col} IS NOT NULL"
        branches.append(
            f"WHEN p.{ident(_CARRY_PT)} = :{pt_param} THEN "
            f"(CASE WHEN {cond} THEN to_jsonb({bk_col}) ELSE CAST(NULL AS jsonb) END)"
        )
    if not branches:
        return "CAST(NULL AS jsonb)"
    return f"CASE {' '.join(branches)} ELSE CAST(NULL AS jsonb) END"


def _version_meta_sql(
    plan: IncrementalPlan, params: dict[str, Any]
) -> tuple[str, str]:
    if not plan.compat_tables:
        return "CAST('' AS text)", "CAST(0 AS bigint)"
    id_branches: list[str] = []
    num_branches: list[str] = []
    for v_idx, pt in enumerate(plan.compat_tables):
        vp = plan.versions[pt]
        pt_param = f"vt_{v_idx}"
        vid_param = f"vid_{v_idx}"
        vnum_param = f"vnum_{v_idx}"
        params.setdefault(pt_param, pt)
        params[vid_param] = vp.version_id
        params[vnum_param] = int(vp.version_number)
        id_branches.append(f"WHEN k.physical_table = :{pt_param} THEN :{vid_param}")
        num_branches.append(
            f"WHEN k.physical_table = :{pt_param} THEN CAST(:{vnum_param} AS bigint)"
        )
    return (
        f"CASE {' '.join(id_branches)} ELSE '' END",
        f"CASE {' '.join(num_branches)} ELSE CAST(0 AS bigint) END",
    )


def _nosides_column_expr(col: ChangesDatasetColumn) -> str:
    if col == "sequence":
        return "e.seq"
    if col == "operation":
        return "e.operation"
    if col == "occurred_at":
        return (
            "to_char(date_trunc('second', e.occurred_at AT TIME ZONE 'UTC'), "
            "'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')"
        )
    if col == "source":
        return "e.source"
    if col == "subject":
        return "e.subject"
    if col == "physical_table":
        return "e.physical_table"
    if col == "version_id":
        return "e.version_id"
    if col == "version_number":
        return "e.version_number"
    if col == "row_id":
        return (
            "CASE "
            "WHEN e.b_present AND e.a_present THEN "
            "(CASE WHEN e.b_row_id IS NOT NULL AND e.a_row_id IS NOT NULL "
            "AND e.b_row_id = e.a_row_id THEN e.b_row_id ELSE CAST(NULL AS bigint) END) "
            "WHEN e.b_present THEN e.b_row_id "
            "WHEN e.a_present THEN e.a_row_id "
            "ELSE CAST(NULL AS bigint) END"
        )
    if col == "business_key":
        return (
            "CASE "
            "WHEN e.b_present AND e.a_present THEN "
            "(CASE WHEN e.b_bk IS NOT NULL AND e.a_bk IS NOT NULL "
            "AND e.b_bk = e.a_bk THEN e.b_bk ELSE CAST(NULL AS jsonb) END) "
            "WHEN e.b_present THEN e.b_bk "
            "WHEN e.a_present THEN e.a_bk "
            "ELSE CAST(NULL AS jsonb) END"
        )
    raise ValueError(f"unsupported NoSides column: {col}")


def _parse_summary(row: Mapping[str, Any], *, page_limit: int) -> PageScanSummary:
    unknown_table = row["__sum_unk"]
    if unknown_table is not None:
        raise ValueError(f"change-log physical table is not loaded: {unknown_table}")
    if int(row["__sum_bad_img"]) > 0:
        raise ValueError("change-log image must be an object")
    if int(row["__sum_miss_after"]) > 0:
        raise KeyError("after")
    if int(row["__sum_miss_before"]) > 0:
        raise KeyError("before")
    if int(row["__sum_unserv"]) > 0:
        raise EntityNotServing(_SERVING_HEAD_PREDATES)
    fetched = int(row["__sum_fetched"])
    has_more = fetched > page_limit
    scanned = min(fetched, page_limit)
    last_cseq = row["__sum_cseq"]
    last_seq = row["__sum_seq"]
    return PageScanSummary(
        scanned_count=scanned,
        last_commit_seq=None if last_cseq is None else int(last_cseq),
        last_seq=None if last_seq is None else int(last_seq),
        has_more=has_more,
    )


def _build_version_plan(
    *,
    meta: VersionMeta,
    policy: Policy,
    current_by_id: Mapping[str, AttrFact],
    head_by_id: Mapping[str, AttributeRecord],
    col_by_id: Mapping[str, Any],
    active_ids: frozenset[str],
    needed_ids: frozenset[str],
    outcome_ids: frozenset[str],
) -> _VersionPlan:
    table = meta.table
    snapshots = table.reference_snapshots
    for attr in table.attributes:
        if attr.type == "reference":
            snap = snapshots.get(attr.name)
            if not isinstance(snap, dict) or snap.get("type") not in ("string", "integer"):
                return _VersionPlan(
                    physical_table=table.physical_table,
                    version_id=meta.version_id,
                    version_number=meta.version_number,
                    unserving=True,
                    compatible=False,
                    present_ids=frozenset(),
                    hist_attr_by_id={},
                    physical_sql_by_id={},
                    projected_key_name=_projected_key_name(table, policy),
                    clear_key_attr_id=None,
                )

    present: set[str] = set()
    incompatible: set[str] = set()
    hist_attr_by_id: dict[str, AttributeRecord] = {}
    physical_sql_by_id: dict[str, str] = {}
    for attr in table.attributes:
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
        hist_attr_by_id[attr.attribute_id] = attr
        physical_sql_by_id[attr.attribute_id] = _version_attr_physical_sql(
            attr, snapshots
        )

    present_fs = frozenset(present)
    incompat_fs = frozenset(incompatible)
    compatible = not (
        bool(needed_ids - present_fs)
        or bool(incompat_fs & (needed_ids | outcome_ids))
    )
    projected_key = _projected_key_name(table, policy)
    clear_key_id: str | None = None
    if table.business_key:
        bk_attr = next(
            (item for item in table.attributes if item.name == table.business_key),
            None,
        )
        bk_id = None if bk_attr is None else bk_attr.attribute_id
        if (
            bk_id is not None
            and bk_id in hist_attr_by_id
            and bk_id in col_by_id
            and any(
                mode == CLEAR
                for gid, mode in col_by_id[bk_id].grant_modes
                if gid in active_ids
            )
        ):
            clear_key_id = bk_id

    return _VersionPlan(
        physical_table=table.physical_table,
        version_id=meta.version_id,
        version_number=meta.version_number,
        unserving=False,
        compatible=compatible,
        present_ids=present_fs,
        hist_attr_by_id=hist_attr_by_id,
        physical_sql_by_id=physical_sql_by_id,
        projected_key_name=projected_key,
        clear_key_attr_id=clear_key_id,
    )


def _version_attr_physical_sql(
    attr: AttributeRecord, snapshots: Mapping[str, Any]
) -> str:
    if attr.type == "reference":
        snap = snapshots[attr.name]
        if snap["type"] == "string":
            proxy = replace(attr, type="string", max_length=snap["max_length"])
        else:
            proxy = replace(attr, type="integer")
        return resolve(proxy.type).physical_sql(proxy)
    return resolve(attr.type).physical_sql(attr)


def _projected_key_name(table: ChangeLogTable, policy: Policy) -> str | None:
    historical = table.business_key
    if not historical:
        return None
    attr = next((item for item in table.attributes if item.name == historical), None)
    attribute_id = None if attr is None else attr.attribute_id
    if attribute_id:
        for fact in policy.attributes:
            if fact.attribute_id == attribute_id:
                return str(fact.name)
    return historical


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
        needed.update(
            validate_rule(rule, attrs, policy.subject_attrs).attribute_ids
        )
    return frozenset(needed)


def _validate_entity_id(entity_id: str) -> str:
    if not isinstance(entity_id, str) or _ENTITY_ID_RE.fullmatch(entity_id) is None:
        raise ValueError("entity id must be an identifier")
    if len(f"seq_{entity_id}") > _NAME_MAX:
        raise ValueError("entity id is too long for a change-log sequence")
    return entity_id
