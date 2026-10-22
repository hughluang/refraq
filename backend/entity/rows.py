"""Head-table row read and batch write for platform writers.

Callers pass a User. A Data Channel run passes the System Identity. Access
control is the same path as the Entity Data API.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text

from backend.admin.subjects import existing_user_ids
from backend.admin.user_store import UserRecord
from backend.entity.access.dsl import rule_sql
from backend.entity.access.enforce import (
    _clear_names,
    _grant,
    _restriction_applies,
    begin_data,
    read_context,
    require_write_grant,
)
from backend.entity.access.errors import EntityAccessWriteDenied
from backend.entity.attribute_type import resolve
from backend.entity.data import sql as data_sql
from backend.entity.data.filters import compile_filters
from backend.entity.data.head import HeadTarget, resolve_head
from backend.entity.data.values import (
    encode_inbound,
    require_business_key_value,
    writable_dictionary_codes,
)
from backend.entity.ddl import ident
from backend.entity.errors import (
    EntityNotFound,
    EntityRowInvalid,
    EntityRowWriteFailed,
)
from backend.entity.reference_binding import business_key_attr
from backend.entity.store import get_entity_store

__all__ = [
    "WRITE_CHUNK_SIZE",
    "RowWriteResult",
    "head_target",
    "read_rows",
    "write_rows",
]

# Rows held in memory while a dataset page is staged. Callers page by this size.
WRITE_CHUNK_SIZE = 1000

Mode = Literal["upsert", "create", "update", "delete"]


@dataclass(frozen=True)
class RowWriteResult:
    inserted: int
    updated: int
    unchanged: int
    deleted: int
    unmatched: int


def head_target(entity_id: str) -> HeadTarget | None:
    try:
        entity = get_entity_store().get_entity(entity_id)
        if entity is None:
            raise EntityNotFound()
        return resolve_head(entity.table_name, for_write=True)
    except EntityNotFound:
        return None


def read_rows(
    entity_id: str,
    *,
    filters: list[dict[str, Any]],
    user: UserRecord,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    entity = get_entity_store().get_entity(entity_id)
    if entity is None:
        raise EntityNotFound()
    access = begin_data(entity.table_name, user, {}, action="read", for_write=False)
    target = access.target
    compiled = compile_filters(_as_filter_tree(filters), target)
    fields = ["row_id", *[attr.name for attr in target.attributes]]
    ctx = read_context(access)
    with data_sql.entity_read_connection(ctx) as conn:
        items, total = data_sql.query_offset(
            conn,
            target,
            fields=fields,
            compiled=compiled,
            limit=limit + 1,
            offset=0,
            include_total=True,
        )
    if len(items) > limit:
        raise EntityRowWriteFailed(
            f"Read returned more than {limit} rows",
            reason="item_limit",
        )
    access.log(row_count=len(items), outcome_code="ok", verb="channel-read")
    return items, int(total or len(items))


def write_rows(
    entity_id: str,
    *,
    mode: Mode,
    match_key: str | None,
    rows: Sequence[Mapping[str, Any]] | Iterable[Sequence[Mapping[str, Any]]],
    user: UserRecord,
    statement_timeout_ms: int | None = None,
    pulse: Callable[[], int] | None = None,
) -> RowWriteResult:
    """Stage every chunk, validate the whole set, then write it in one transaction.

    A sequence of row mappings is one chunk, and ``_ord`` is the list index.
    Any other iterable yields chunks. A chunk of mappings continues ``_ord``
    from the previous mapping chunk, starting at 0. A chunk of ``(ord, row)``
    pairs keeps those ordinals. ``pulse`` returns the remaining wall-clock
    milliseconds and raises to stop the write. The target is unchanged when
    validation, the deadline, or the callback fails.
    """
    entity = get_entity_store().get_entity(entity_id)
    if entity is None:
        raise EntityNotFound()
    access = begin_data(entity.table_name, user, {}, action="write", for_write=True)
    target = access.target
    key_name = _match_key_name(target, match_key)
    chunks = _iter_chunks(rows)
    first: Sequence[Mapping[str, Any]] | None = None
    for chunk in chunks:
        if chunk:
            first = chunk
            break
    if first is None:
        return RowWriteResult(0, 0, 0, 0, 0)
    budget = pulse or _deadline_pulse(
        300_000 if statement_timeout_ms is None else statement_timeout_ms
    )
    try:
        with data_sql.entity_connection() as conn:
            result, row_count = _write_in_transaction(
                conn,
                access,
                target,
                mode,
                key_name,
                _chain(first, chunks),
                budget,
            )
        access.log(row_count=row_count, outcome_code="ok", verb="channel-write")
        return result
    except Exception as exc:
        access.log(
            row_count=None,
            outcome_code=getattr(exc, "code", "error"),
            verb="channel-write",
        )
        raise


def _as_filter_tree(filters: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not filters:
        return None
    leaves = []
    for item in filters:
        leaves.append(
            {
                "field": item["attribute"],
                "op": item.get("op", "eq"),
                "value": item.get("value"),
            }
        )
    if len(leaves) == 1:
        return leaves[0]
    return {"all": leaves}


def _match_key_name(target: HeadTarget, match_key: str | None) -> str:
    if match_key is None:
        marked = business_key_attr(target.attributes)
        if marked is None:
            raise EntityRowWriteFailed(
                "Target head has no Business Key",
                reason="business_key_missing",
            )
        return marked.name
    by_name = {attr.name: attr for attr in target.attributes}
    attr = by_name.get(match_key)
    if attr is None or not attr.unique:
        raise EntityRowWriteFailed(
            "Match key does not resolve",
            reason="match_key_not_unique",
        )
    return attr.name


def _deadline_pulse(timeout_ms: int) -> Callable[[], int]:
    deadline = time.monotonic() + max(1, int(timeout_ms)) / 1000

    def pulse() -> int:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EntityRowWriteFailed(
                "Write exceeded the statement timeout",
                reason="timeout",
            )
        return max(1, int(remaining * 1000))

    return pulse


def _iter_chunks(
    rows: Sequence[Mapping[str, Any]] | Iterable[Sequence[Mapping[str, Any]]],
) -> Iterator[Sequence[Mapping[str, Any]]]:
    if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
        yield rows
        return
    yield from rows


def _chain(
    first: Sequence[Mapping[str, Any]],
    rest: Iterator[Sequence[Mapping[str, Any]]],
) -> Iterator[Sequence[Mapping[str, Any]]]:
    yield first
    yield from rest


def _tick(conn: Any, pulse: Callable[[], int]) -> None:
    data_sql.set_write_timeouts(conn, pulse())


def _write_in_transaction(
    conn: Any,
    access: Any,
    target: HeadTarget,
    mode: Mode,
    key_name: str,
    chunks: Iterator[Sequence[Mapping[str, Any]]],
    pulse: Callable[[], int],
) -> tuple[RowWriteResult, int]:
    columns = [attr.name for attr in target.attributes]
    _tick(conn, pulse)
    stage = data_sql.create_write_stage(
        conn,
        [(attr.name, _stage_type(attr, target)) for attr in target.attributes],
    )
    codes = _dictionary_codes(target)
    column_ords: dict[str, int] = {}
    total = 0
    ordinal = 0
    for chunk in chunks:
        _tick(conn, pulse)
        if not chunk:
            continue
        paired = _is_ord_pair(chunk[0])
        encoded = _encode_chunk(chunk, target, mode, key_name, codes, ordinal, paired=paired)
        _tick(conn, pulse)
        data_sql.copy_write_stage(
            conn,
            stage,
            columns,
            [
                (ord_, present, *[values.get(name) for name in columns])
                for ord_, present, values in encoded
            ],
        )
        if mode != "delete":
            for ord_, present, _values in encoded:
                for name in present:
                    column_ords.setdefault(name, ord_)
        total += len(chunk)
        if not paired:
            ordinal += len(chunk)
    _validate(conn, pulse, access, target, stage, mode, key_name, columns, column_ords)
    _tick(conn, pulse)
    inserted, updated, unchanged, deleted, unmatched = data_sql.write_staged_counts(
        conn,
        target=target.qualified_table,
        stage=stage,
        mode=mode,
        key=key_name,
        columns=columns,
    )
    _tick(conn, pulse)
    data_sql.drop_write_stage(conn, stage)
    return RowWriteResult(inserted, updated, unchanged, deleted, unmatched), total


def _stage_type(attr: Any, target: HeadTarget) -> str:
    if attr.type == "reference":
        snap = target.head.reference_snapshots.get(attr.name)
        if isinstance(snap, dict) and snap.get("type") == "string":
            return f"VARCHAR({int(snap['max_length'])})"
        if isinstance(snap, dict) and snap.get("type") == "integer":
            return "BIGINT"
    return resolve(attr.type).physical_sql(attr)


def _dictionary_codes(target: HeadTarget) -> dict[str, frozenset[str]]:
    found: dict[str, frozenset[str]] = {}
    for attr in target.attributes:
        if "dictionary" in resolve(attr.type).reads:
            found[attr.name] = writable_dictionary_codes(attr, target)
    return found


def _is_ord_pair(item: Any) -> bool:
    return (
        isinstance(item, tuple)
        and len(item) == 2
        and isinstance(item[0], int)
        and not isinstance(item[0], bool)
        and isinstance(item[1], Mapping)
    )


def _encode_chunk(
    chunk: Sequence[Any],
    target: HeadTarget,
    mode: Mode,
    key_name: str,
    codes: dict[str, frozenset[str]],
    start: int,
    *,
    paired: bool,
) -> list[tuple[int, list[str], dict[str, Any]]]:
    encoded_rows: list[tuple[int, list[str], dict[str, Any]]] = []
    users: list[tuple[int, dict[str, Any]]] = []
    key_attr = next(attr for attr in target.attributes if attr.name == key_name)
    for offset, raw in enumerate(chunk):
        if paired:
            if not _is_ord_pair(raw):
                raise EntityRowWriteFailed(
                    "Source row is not an ordinal pair",
                    row_index=start + offset,
                    reason="invalid",
                )
            ordinal, row = int(raw[0]), raw[1]
        else:
            ordinal, row = start + offset, raw
        try:
            if mode == "delete":
                if key_name not in row:
                    raise EntityRowInvalid(f"Attribute '{key_name}' is required")
                encoded = {key_name: _encode_one(key_attr, row[key_name], target, codes)}
            else:
                encoded = _encode_map(dict(row), target, partial=mode == "update", codes=codes)
                if key_name not in encoded:
                    raise EntityRowInvalid(f"Attribute '{key_name}' is required")
        except EntityRowInvalid as exc:
            raise EntityRowWriteFailed(
                exc.message,
                row_index=ordinal,
                reason="invalid",
            ) from exc
        encoded_rows.append((ordinal, list(encoded), encoded))
        if mode != "delete":
            users.append((ordinal, encoded))
    if mode != "delete":
        _reject_unknown_users(target, users)
    return encoded_rows


def _encode_map(
    values: dict[str, Any],
    target: HeadTarget,
    *,
    partial: bool,
    codes: dict[str, frozenset[str]],
) -> dict[str, Any]:
    if "row_id" in values:
        raise EntityRowInvalid("row_id is not an authorable attribute")
    by_name = {attr.name: attr for attr in target.attributes}
    unknown = [key for key in values if key not in by_name]
    if unknown:
        raise EntityRowInvalid(f"Unknown attribute(s): {', '.join(sorted(unknown))}")
    if not values:
        raise EntityRowInvalid("values must not be empty")
    encoded: dict[str, Any] = {}
    for name, raw in values.items():
        require_business_key_value(by_name[name], raw)
        encoded[name] = _encode_one(by_name[name], raw, target, codes)
    if not partial:
        for attr in target.attributes:
            if attr.required and (attr.name not in encoded or encoded.get(attr.name) is None):
                raise EntityRowInvalid(f"Attribute '{attr.name}' is required")
    return encoded


def _encode_one(
    attr: Any,
    raw: Any,
    target: HeadTarget,
    codes: dict[str, frozenset[str]],
) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str) and "\x00" in raw:
        raise EntityRowInvalid(f"Attribute '{attr.name}' must not contain NUL")
    if attr.name in codes:
        return resolve(attr.type).encode(attr, raw, codes=codes[attr.name])
    return encode_inbound(attr, raw, target)


def _reject_unknown_users(
    target: HeadTarget,
    rows: list[tuple[int, dict[str, Any]]],
) -> None:
    specs = [attr for attr in target.attributes if "user" in resolve(attr.type).reads]
    if not specs:
        return
    wanted = {
        encoded[attr.name]
        for _ord, encoded in rows
        for attr in specs
        if encoded.get(attr.name) is not None
    }
    if not wanted:
        return
    unknown = wanted - existing_user_ids(wanted)
    if not unknown:
        return
    for ordinal, encoded in rows:
        hit = sorted(
            str(encoded[attr.name])
            for attr in specs
            if encoded.get(attr.name) in unknown
        )
        if hit:
            raise EntityRowWriteFailed(
                f"User id(s) do not name a User: {', '.join(hit)}",
                row_index=ordinal,
                reason="invalid",
            )


@dataclass(frozen=True)
class _Fault:
    ordinal: int
    rank: int
    message: str
    attribute: str | None
    value: Any
    reason: str


def _validate(
    conn: Any,
    pulse: Callable[[], int],
    access: Any,
    target: HeadTarget,
    stage: str,
    mode: Mode,
    key_name: str,
    columns: list[str],
    column_ords: dict[str, int],
) -> None:
    faults: list[_Fault] = []
    duplicate = _first_pair(conn, pulse, _duplicate_sql(stage, key_name))
    if duplicate is not None:
        faults.append(
            _Fault(
                duplicate[0],
                0,
                "Source list contains a duplicate match key",
                key_name,
                duplicate[1],
                "duplicate_key",
            )
        )
    if mode == "create":
        existing = _first_pair(conn, pulse, _existing_sql(target, stage, key_name))
        if existing is not None:
            faults.append(
                _Fault(
                    existing[0],
                    1,
                    "Match key already exists",
                    key_name,
                    existing[1],
                    "key_exists",
                )
            )
    business = business_key_attr(target.attributes)
    if (
        mode in {"upsert", "update"}
        and business is not None
        and business.name != key_name
    ):
        changed = _first_pair(
            conn, pulse, _business_key_sql(target, stage, key_name, business.name)
        )
        if changed is not None:
            faults.append(
                _Fault(
                    changed[0],
                    2,
                    f"Attribute '{business.name}' is the business key and cannot be changed",
                    business.name,
                    changed[1],
                    "business_key",
                )
            )
    written = {key_name} if mode == "delete" else set(column_ords)
    if written:
        covered = _covers(access, written)
        if not covered and mode == "delete":
            matched = _first_ord(conn, pulse, _matched_ord_sql(target, stage, key_name))
            if matched is not None:
                faults.append(
                    _Fault(
                        matched,
                        4,
                        f"Column '{key_name}' is outside the write grant",
                        key_name,
                        None,
                        "column",
                    )
                )
        elif not covered:
            fault = _column_fault(access, column_ords)
            if fault is not None:
                faults.append(
                    _Fault(
                        fault[0],
                        4,
                        f"Column '{fault[1]}' is outside the write grant",
                        fault[1],
                        None,
                        "column",
                    )
                )
        else:
            failed = _first_ord(
                conn,
                pulse,
                _rule_sql_query(
                    access,
                    covered,
                    target,
                    stage,
                    mode,
                    key_name,
                    columns,
                ),
            )
            if failed is not None:
                faults.append(
                    _Fault(failed, 3, "Row rule rejected the write", None, None, "row_rule")
                )
    if not faults:
        return
    fault = min(faults, key=lambda item: (item.ordinal, item.rank))
    raise EntityRowWriteFailed(
        fault.message,
        row_index=fault.ordinal,
        attribute=fault.attribute,
        value=fault.value,
        reason=fault.reason,
    )


def _covers(access: Any, written: set[str]) -> list[Any]:
    try:
        require_write_grant(access, written=written, before=[], after=[])
    except EntityAccessWriteDenied:
        return []
    found = []
    for grant_id in access.outcome.grant_ids:
        grant = _grant(access, grant_id)
        if grant is None or "write" not in grant.actions:
            continue
        if written <= _clear_names(access, grant):
            found.append(grant)
    return found


def _column_fault(access: Any, column_ords: dict[str, int]) -> tuple[int, str] | None:
    if not column_ords:
        return None
    union = set(column_ords)
    grants = []
    for grant_id in access.outcome.grant_ids:
        grant = _grant(access, grant_id)
        if grant is None or "write" not in grant.actions:
            continue
        grants.append(grant)
        if union <= _clear_names(access, grant):
            return None
    best: tuple[int, str] | None = None
    for grant in grants:
        clear = _clear_names(access, grant)
        outside = [name for name in union if name not in clear]
        if not outside:
            return None
        name = min(outside, key=lambda item: (column_ords[item], item))
        choice = (column_ords[name], name)
        if best is None or choice < best:
            best = choice
    if best is None:
        name = min(column_ords, key=lambda item: (column_ords[item], item))
        return column_ords[name], name
    return best


def _first_pair(conn: Any, pulse: Callable[[], int], sql: str) -> tuple[int, Any] | None:
    _tick(conn, pulse)
    row = conn.execute(text(sql)).first()
    if row is None:
        return None
    return int(row[0]), row[1]


def _first_ord(conn: Any, pulse: Callable[[], int], sql: str) -> int | None:
    _tick(conn, pulse)
    value = conn.execute(text(sql)).scalar()
    if value is None:
        return None
    return int(value)


def _duplicate_sql(stage: str, key: str) -> str:
    return (
        f"SELECT s.{ident('_ord')}, s.{ident(key)} FROM {stage} AS s "
        f"JOIN (SELECT {ident(key)} AS {ident('match_key')} FROM {stage} "
        f"GROUP BY {ident(key)} HAVING count(*) > 1) AS d "
        f"ON d.{ident('match_key')} IS NOT DISTINCT FROM s.{ident(key)} "
        f"ORDER BY s.{ident('_ord')} LIMIT 1"
    )


def _existing_sql(target: HeadTarget, stage: str, key: str) -> str:
    return (
        f"SELECT s.{ident('_ord')}, s.{ident(key)} FROM {stage} AS s "
        f"JOIN {target.qualified_table} AS t "
        f"ON t.{ident(key)} = s.{ident(key)} "
        f"ORDER BY s.{ident('_ord')} LIMIT 1"
    )


def _business_key_sql(target: HeadTarget, stage: str, key: str, business: str) -> str:
    return (
        f"SELECT s.{ident('_ord')}, s.{ident(business)} FROM {stage} AS s "
        f"JOIN {target.qualified_table} AS t "
        f"ON t.{ident(key)} = s.{ident(key)} "
        f"WHERE {_sql_lit(business)} = ANY(s.{ident('_present')}) "
        f"AND t.{ident(business)} IS DISTINCT FROM s.{ident(business)} "
        f"ORDER BY s.{ident('_ord')} LIMIT 1"
    )


def _matched_ord_sql(target: HeadTarget, stage: str, key: str) -> str:
    return (
        f"SELECT min(s.{ident('_ord')}) FROM {stage} AS s "
        f"JOIN {target.qualified_table} AS t "
        f"ON t.{ident(key)} = s.{ident(key)}"
    )


def _rule_sql_query(
    access: Any,
    grants: list[Any],
    target: HeadTarget,
    stage: str,
    mode: Mode,
    key: str,
    columns: list[str],
) -> str:
    """Fail unless one column-covering grant accepts every row that will be written.

    The reported ordinal is the minimum of each grant's own smallest rejection.
    A grant that accepts the whole set contributes NULL and the write passes.
    """
    distinct = _distinct_sql(key, columns)
    if mode == "delete":
        would = f"t.{ident('row_id')} IS NOT NULL"
    elif mode == "create":
        would = "TRUE"
    elif mode == "update":
        would = f"t.{ident('row_id')} IS NOT NULL AND ({distinct})"
    else:
        would = f"(t.{ident('row_id')} IS NULL OR ({distinct}))"
    per_grant = " UNION ALL ".join(
        "SELECT ("
        f"SELECT min(s.{ident('_ord')}) FROM {stage} AS s "
        f"LEFT JOIN {target.qualified_table} AS t "
        f"ON t.{ident(key)} = s.{ident(key)} "
        f"WHERE ({would}) AND NOT ({_grant_accepts(access, grant, target, mode)})"
        ") AS fail_ord"
        for grant in grants
    )
    return (
        f"SELECT min(fail_ord) FROM ({per_grant}) AS per_grant "
        "HAVING count(*) = count(fail_ord)"
    )


def _distinct_sql(key: str, columns: list[str]) -> str:
    others = [name for name in columns if name != key]
    if not others:
        return "FALSE"
    return " OR ".join(
        f"({_sql_lit(name)} = ANY(s.{ident('_present')}) "
        f"AND t.{ident(name)} IS DISTINCT FROM s.{ident(name)})"
        for name in others
    )


def _grant_accepts(access: Any, grant: Any, target: HeadTarget, mode: Mode) -> str:
    before = _image_predicate(access, grant, "t")
    after = _after_predicate(access, grant, target)
    if mode == "delete":
        return before
    if mode == "create":
        return after
    return (
        f"(t.{ident('row_id')} IS NULL AND ({after})) "
        f"OR (t.{ident('row_id')} IS NOT NULL AND ({before}) AND ({after}))"
    )


def _image_predicate(access: Any, grant: Any, alias: str) -> str:
    facts = {item.attribute_id: item for item in access.policy.attributes}
    values = access.policy.subject_values.get(access.person.user_id, {})
    subject_id = access.person.user_id
    parts = [
        rule_sql(
            grant.row_rule,
            facts,
            alias=alias,
            acl=False,
            subject_id=subject_id,
            subject_values=values,
        )
    ]
    for item in access.policy.restrictions:
        if "write" not in item.actions or item.id in access.compiled.broken_restrictions:
            continue
        if item.mode != "all" and not _restriction_applies(item, access.person):
            continue
        parts.append(
            rule_sql(
                item.row_rule,
                facts,
                alias=alias,
                acl=False,
                subject_id=subject_id,
                subject_values=values,
            )
        )
    return " AND ".join(f"COALESCE({part}, false)" for part in parts)


def _after_predicate(access: Any, grant: Any, target: HeadTarget) -> str:
    staged = {attr.name for attr in target.attributes}
    full = access.full.attributes
    projected = []
    for attr in full:
        column = ident(attr.name)
        if attr.name in staged:
            projected.append(
                f"CASE WHEN {_sql_lit(attr.name)} = ANY(s.{ident('_present')}) "
                f"THEN s.{column} ELSE t.{column} END AS {column}"
            )
        else:
            projected.append(f"t.{column} AS {column}")
    predicate = _image_predicate(access, grant, "img")
    return (
        f"COALESCE((SELECT {predicate} FROM (SELECT {', '.join(projected)}) AS img), false)"
    )


def _sql_lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
