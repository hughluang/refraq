"""Entity-database SQL for Entity Data API action verbs.

Reads select the caller's profile view on the reader connection. Writes run on the
owner connection against the physical table and return only ``row_id``; the caller
presents written rows through its read view.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from backend.core.config import get_settings
from backend.core.db import map_platform_db_error
from backend.core.errors import PlatformCapacityExceeded
from backend.entity.data.capabilities import ROW_WRITE_LIMIT
from backend.entity.data.filters import CompiledFilter
from backend.entity.data.head import HeadTarget
from backend.entity.data.values import decode_row
from backend.entity.change_log import SOURCE_GUC, SUBJECT_GUC
from backend.entity.ddl import ENTITY_DATA_SCHEMA, ident, qualified_table
from backend.entity.entity_db import get_entity_engine, get_entity_reader_engine
from backend.entity.errors import (
    EntityNotServing,
    EntityRowConflict,
    EntityRowInvalid,
    EntityRowLimitExceeded,
    EntityRowNotFound,
)

__all__ = [
    "copy_write_stage",
    "create_write_stage",
    "drop_write_stage",
    "delete_ids",
    "entity_connection",
    "entity_read_connection",
    "insert_row",
    "query_keyset",
    "query_offset",
    "require_entity_capacity",
    "require_entity_reader_capacity",
    "select_by_column",
    "select_ids",
    "select_matching",
    "select_stored_matching",
    "select_stored_row",
    "set_change_log_actor",
    "set_write_timeouts",
    "update_ids",
    "write_staged_counts",
]


def require_entity_capacity() -> Engine:
    settings = get_settings()
    if settings.store_backend == "memory":
        raise PlatformCapacityExceeded()
    try:
        return get_entity_engine()
    except PoolTimeoutError as exc:
        mapped = map_platform_db_error(exc)
        raise mapped or PlatformCapacityExceeded() from exc


def require_entity_reader_capacity() -> Engine:
    settings = get_settings()
    if settings.store_backend == "memory":
        raise PlatformCapacityExceeded()
    try:
        return get_entity_reader_engine()
    except PoolTimeoutError as exc:
        mapped = map_platform_db_error(exc)
        raise mapped or PlatformCapacityExceeded() from exc


@contextmanager
def entity_connection() -> Iterator[Connection]:
    """Owner connection for writes. Reads use ``entity_read_connection``."""
    engine = require_entity_capacity()
    try:
        with engine.begin() as conn:
            yield conn
    except Exception as exc:
        raise _translate(exc) from exc


@contextmanager
def entity_read_connection(ctx: str | None) -> Iterator[Connection]:
    """``refraq_reader`` connection with the signed access context set for this transaction.

    Profile views are granted only to the reader role; the owner cannot select them.
    """
    engine = require_entity_reader_capacity()
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.ctx', :token, true)"),
                {"token": ctx or ""},
            )
            yield conn
    except Exception as exc:
        raise _translate(exc) from exc


def _read_from(target: HeadTarget) -> str:
    if target.read_relation is None:
        raise EntityNotServing()
    return target.read_relation


def insert_row(conn: Connection, target: HeadTarget, values: dict[str, Any]) -> int:
    columns = list(values.keys())
    col_sql = ", ".join(ident(name) for name in columns)
    param_sql = ", ".join(f":{name}" for name in columns)
    sql = (
        f"INSERT INTO {target.qualified_table} ({col_sql}) "
        f"VALUES ({param_sql}) RETURNING {ident('row_id')}"
    )
    return int(conn.execute(text(sql), values).scalar_one())


def select_by_column(
    conn: Connection,
    target: HeadTarget,
    column: str,
    value: Any,
    *,
    lock: bool = False,
) -> dict[str, Any]:
    """One row by locator. ``lock`` takes ``FOR UPDATE`` on the physical table."""
    row = _fetch_one(conn, target, column, value, lock=lock)
    if row is None:
        raise EntityRowNotFound()
    return decode_row(_column_names(target), row, target)


def select_stored_row(
    conn: Connection,
    target: HeadTarget,
    column: str,
    value: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Locked physical row as ``(decoded, driver)``.

    Grants and presentation use the decoded row. An equal-value check compares
    driver values with the encoded assignment, which is what ``IS DISTINCT FROM``
    compares.
    """
    row = _fetch_one(conn, target, column, value, lock=True)
    if row is None:
        raise EntityRowNotFound()
    names = _column_names(target)
    return decode_row(names, row, target), dict(zip(names, row, strict=True))


def _fetch_one(
    conn: Connection,
    target: HeadTarget,
    column: str,
    value: Any,
    *,
    lock: bool,
) -> tuple[Any, ...] | None:
    returning = _returning_cols(target)
    relation = target.qualified_table if lock else _read_from(target)
    sql = (
        f"SELECT {returning} FROM {relation} "
        f"WHERE {ident(column)} = :_locator"
        + (" FOR UPDATE" if lock else "")
    )
    found = conn.execute(text(sql), {"_locator": value}).one_or_none()
    if found is None:
        return None
    return tuple(found)


def select_ids(
    conn: Connection, target: HeadTarget, row_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """Rows by id from the read relation; ids the relation does not show are absent."""
    if not row_ids:
        return {}
    returning = _returning_cols(target)
    sql = (
        f"SELECT {returning} FROM {_read_from(target)} "
        f"WHERE {ident('row_id')} = ANY(:ids)"
    )
    rows = conn.execute(text(sql), {"ids": list(row_ids)}).all()
    names = _column_names(target)
    decoded = [decode_row(names, tuple(row), target) for row in rows]
    return {int(row["row_id"]): row for row in decoded}


def update_ids(
    conn: Connection,
    target: HeadTarget,
    row_ids: list[int],
    values: dict[str, Any],
) -> int:
    if not row_ids:
        return 0
    assigns = ", ".join(f"{ident(name)} = :{name}" for name in values)
    params = dict(values)
    params["ids"] = row_ids
    distinct = " OR ".join(
        f"{ident(name)} IS DISTINCT FROM :{name}" for name in values
    )
    sql = (
        f"UPDATE {target.qualified_table} SET {assigns} "
        f"WHERE {ident('row_id')} = ANY(:ids) AND ({distinct})"
    )
    result = conn.execute(text(sql), params)
    return int(result.rowcount or 0)


def set_change_log_actor(conn: Connection, source: str, subject: str) -> None:
    """Attribute this write transaction. Both settings end when it commits."""
    conn.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": SOURCE_GUC, "value": source},
    )
    conn.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": SUBJECT_GUC, "value": subject},
    )


def set_write_timeouts(conn: Connection, remaining_ms: int) -> None:
    """Bound statement, lock, and idle-in-transaction waits to the remaining budget.

    ``idle_in_transaction_session_timeout`` is at least that budget so a gap
    spent encoding the next chunk is not cut by the connection default.
    """
    budget = str(max(1, int(remaining_ms)))
    conn.execute(text("SELECT set_config('statement_timeout', :ms, true)"), {"ms": budget})
    conn.execute(text("SELECT set_config('lock_timeout', :ms, true)"), {"ms": budget})
    conn.execute(
        text("SELECT set_config('idle_in_transaction_session_timeout', :ms, true)"),
        {"ms": budget},
    )


def create_write_stage(conn: Connection, columns: list[tuple[str, str]]) -> str:
    """Stage table in ``entity_data``, visible only until this transaction ends.

    The entity owner is not granted ``TEMP``, so this is an ordinary table
    created inside the write transaction. ``drop_write_stage`` removes it
    before commit; a rollback removes the create with the rest of the write.
    """
    defs = ['"_ord" bigint NOT NULL', '"_present" text[] NOT NULL']
    for name, type_sql in columns:
        defs.append(f"{ident(name)} {type_sql}")
    qualified = qualified_table(ENTITY_DATA_SCHEMA, f"wstage_{uuid.uuid4().hex[:16]}")
    conn.execute(text(f"CREATE TABLE {qualified} ({', '.join(defs)})"))
    return qualified


def drop_write_stage(conn: Connection, table: str) -> None:
    conn.execute(text(f"DROP TABLE {table}"))


def copy_write_stage(
    conn: Connection,
    table: str,
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    """Copy one chunk. ``columns`` follow ``_ord`` and ``_present``."""
    if not rows:
        return
    names = ", ".join(ident(name) for name in ["_ord", "_present", *columns])
    statement = f"COPY {table} ({names}) FROM STDIN"
    raw = conn.connection.driver_connection
    with raw.cursor() as cursor:
        with cursor.copy(statement) as copy:
            for row in rows:
                copy.write_row(row)


def write_staged_counts(
    conn: Connection,
    *,
    target: str,
    stage: str,
    mode: str,
    key: str,
    columns: list[str],
) -> tuple[int, int, int, int, int]:
    """Set-wise insert, update, or delete. Counts come from ``RETURNING`` old/new.

    A companion read of the target in the same statement sees the pre-write
    snapshot, so unchanged and unmatched are the staged rows ``RETURNING`` did
    not classify as changed. Locks are taken by this statement.
    """
    sql = _staged_sql(target, stage, mode, key, columns)
    row = conn.execute(text(sql)).one()
    return tuple(int(value) for value in row)  # type: ignore[return-value]


def _staged_sql(target: str, stage: str, mode: str, key: str, columns: list[str]) -> str:
    if mode == "delete":
        return _delete_sql(target, stage, key)
    if mode == "update":
        return _update_sql(target, stage, key, columns)
    if mode == "create":
        return _create_sql(target, stage, columns)
    return _upsert_sql(target, stage, key, columns)


def _stage_expr(name: str) -> str:
    return (
        f"CASE WHEN {_sql_lit(name)} = ANY(s.{ident('_present')}) "
        f"THEN s.{ident(name)} ELSE NULL END"
    )


def _sql_lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _create_sql(target: str, stage: str, columns: list[str]) -> str:
    col_sql = ", ".join(ident(name) for name in columns)
    select_sql = ", ".join(_stage_expr(name) for name in columns)
    return f"""
WITH written AS (
    INSERT INTO {target} ({col_sql})
    SELECT {select_sql}
    FROM {stage} AS s
    RETURNING (old.{ident('row_id')} IS NULL) AS inserted
)
SELECT
    (SELECT count(*) FROM written WHERE inserted)::int,
    0,
    0,
    0,
    0
"""


def _upsert_sql(target: str, stage: str, key: str, columns: list[str]) -> str:
    others = [name for name in columns if name != key]
    col_sql = ", ".join(ident(name) for name in columns)
    select_sql = ", ".join(_stage_expr(name) for name in columns)
    if others:
        assigns = ", ".join(_conflict_assign(stage, key, name) for name in others)
        guard = _conflict_guard(stage, key, others)
    else:
        assigns = f"{ident(key)} = excluded.{ident(key)}"
        guard = "FALSE"
    return f"""
WITH written AS (
    INSERT INTO {target} AS t ({col_sql})
    SELECT {select_sql}
    FROM {stage} AS s
    ON CONFLICT ({ident(key)}) DO UPDATE SET {assigns}
    WHERE {guard}
    RETURNING (old.{ident('row_id')} IS NULL) AS inserted
),
matched AS (
    SELECT 1
    FROM {stage} AS s
    JOIN {target} AS t ON t.{ident(key)} = s.{ident(key)}
)
SELECT
    (SELECT count(*) FROM written WHERE inserted)::int,
    (SELECT count(*) FROM written WHERE NOT inserted)::int,
    (
        (SELECT count(*) FROM matched)
        - (SELECT count(*) FROM written WHERE NOT inserted)
    )::int,
    0,
    0
"""


def _conflict_assign(stage: str, key: str, name: str) -> str:
    return (
        f"{ident(name)} = (SELECT CASE WHEN {_sql_lit(name)} = ANY(g.{ident('_present')}) "
        f"THEN g.{ident(name)} ELSE t.{ident(name)} END "
        f"FROM {stage} AS g "
        f"WHERE g.{ident(key)} = excluded.{ident(key)})"
    )


def _conflict_guard(stage: str, key: str, others: list[str]) -> str:
    terms = " OR ".join(
        f"({_sql_lit(name)} = ANY(g.{ident('_present')}) "
        f"AND t.{ident(name)} IS DISTINCT FROM g.{ident(name)})"
        for name in others
    )
    return (
        f"(SELECT {terms} FROM {stage} AS g "
        f"WHERE g.{ident(key)} = excluded.{ident(key)})"
    )


def _update_sql(target: str, stage: str, key: str, columns: list[str]) -> str:
    others = [name for name in columns if name != key]
    matched = (
        f"SELECT 1 FROM {stage} AS s "
        f"JOIN {target} AS t ON t.{ident(key)} = s.{ident(key)}"
    )
    if not others:
        return f"""
SELECT
    0,
    0,
    (SELECT count(*) FROM ({matched}) AS matched)::int,
    0,
    ((SELECT count(*) FROM {stage}) - (SELECT count(*) FROM ({matched}) AS matched))::int
"""
    assigns = ", ".join(
        f"{ident(name)} = CASE WHEN {_sql_lit(name)} = ANY(s.{ident('_present')}) "
        f"THEN s.{ident(name)} ELSE t.{ident(name)} END"
        for name in others
    )
    guard = " OR ".join(
        f"({_sql_lit(name)} = ANY(s.{ident('_present')}) "
        f"AND t.{ident(name)} IS DISTINCT FROM s.{ident(name)})"
        for name in others
    )
    return f"""
WITH written AS (
    UPDATE {target} AS t
    SET {assigns}
    FROM {stage} AS s
    WHERE t.{ident(key)} = s.{ident(key)}
      AND ({guard})
    RETURNING (old.{ident('row_id')} IS NOT NULL) AS updated
),
matched AS (
    {matched}
)
SELECT
    0,
    (SELECT count(*) FROM written)::int,
    ((SELECT count(*) FROM matched) - (SELECT count(*) FROM written))::int,
    0,
    ((SELECT count(*) FROM {stage}) - (SELECT count(*) FROM matched))::int
"""


def _delete_sql(target: str, stage: str, key: str) -> str:
    matched = (
        f"SELECT 1 FROM {stage} AS s "
        f"JOIN {target} AS t ON t.{ident(key)} = s.{ident(key)}"
    )
    return f"""
WITH written AS (
    DELETE FROM {target} AS t
    USING {stage} AS s
    WHERE t.{ident(key)} = s.{ident(key)}
    RETURNING old.{ident('row_id')}
),
matched AS (
    {matched}
)
SELECT
    0,
    0,
    0,
    (SELECT count(*) FROM written)::int,
    ((SELECT count(*) FROM {stage}) - (SELECT count(*) FROM matched))::int
"""


def delete_ids(conn: Connection, target: HeadTarget, row_ids: list[int]) -> int:
    if not row_ids:
        return 0
    result = conn.execute(
        text(
            f"DELETE FROM {target.qualified_table} "
            f"WHERE {ident('row_id')} = ANY(:ids)"
        ),
        {"ids": row_ids},
    )
    return int(result.rowcount or 0)


def select_matching(
    conn: Connection,
    target: HeadTarget,
    compiled: CompiledFilter,
) -> list[dict[str, Any]]:
    """Physical rows matching a filter, locked for write attribution. Owner connection."""
    stored = select_stored_matching(conn, target, compiled)
    return [decoded for decoded, _driver in stored]


def select_stored_matching(
    conn: Connection,
    target: HeadTarget,
    compiled: CompiledFilter,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Each locked match as ``(decoded, driver)``. See ``select_stored_row``."""
    where_sql, params = _where(compiled)
    returning = _returning_cols(target)
    sql = (
        f"SELECT {returning} FROM {target.qualified_table}{where_sql} "
        f"ORDER BY {ident('row_id')} ASC LIMIT {ROW_WRITE_LIMIT + 1} FOR UPDATE"
    )
    rows = conn.execute(text(sql), params).all()
    if len(rows) > ROW_WRITE_LIMIT:
        raise EntityRowLimitExceeded()
    names = _column_names(target)
    return [
        (decode_row(names, raw, target), dict(zip(names, raw, strict=True)))
        for raw in (tuple(row) for row in rows)
    ]


def query_offset(
    conn: Connection,
    target: HeadTarget,
    *,
    fields: list[str],
    compiled: CompiledFilter | None,
    limit: int,
    offset: int,
    include_total: bool,
) -> tuple[list[dict[str, Any]], int | None]:
    where_sql, params = _where(compiled)
    select_cols = ", ".join(ident(name) for name in fields)
    sql = (
        f"SELECT {select_cols} FROM {_read_from(target)}{where_sql} "
        f"ORDER BY {ident('row_id')} ASC LIMIT :_limit OFFSET :_offset"
    )
    params = dict(params)
    params["_limit"] = limit
    params["_offset"] = offset
    rows = conn.execute(text(sql), params).all()
    items = [decode_row(fields, tuple(row), target) for row in rows]
    total: int | None = None
    if include_total:
        count_sql = f"SELECT count(*) FROM {_read_from(target)}{where_sql}"
        count_params = {k: v for k, v in params.items() if not k.startswith("_")}
        total = int(conn.execute(text(count_sql), count_params).scalar_one())
    return items, total


def query_keyset(
    conn: Connection,
    target: HeadTarget,
    *,
    fields: list[str],
    compiled: CompiledFilter | None,
    limit: int,
    after_row_id: int | None,
) -> tuple[list[dict[str, Any]], int | None]:
    where_sql, params = _where(compiled)
    params = dict(params)
    if after_row_id is not None:
        key = "_after"
        params[key] = after_row_id
        clause = f"{ident('row_id')} > :{key}"
        where_sql = (
            f"{where_sql} AND {clause}"
            if where_sql
            else f" WHERE {clause}"
        )
    select_cols = ", ".join(ident(name) for name in fields)
    sql = (
        f"SELECT {select_cols} FROM {_read_from(target)}{where_sql} "
        f"ORDER BY {ident('row_id')} ASC LIMIT :_limit"
    )
    params["_limit"] = limit + 1
    rows = conn.execute(text(sql), params).all()
    page = rows[:limit]
    items = [decode_row(fields, tuple(row), target) for row in page]
    next_after: int | None = None
    if len(rows) > limit:
        next_after = int(items[-1]["row_id"])
    return items, next_after


def _where(compiled: CompiledFilter | None) -> tuple[str, dict[str, Any]]:
    if compiled is None:
        return "", {}
    return f" WHERE {compiled.sql}", dict(compiled.params)


def _column_names(target: HeadTarget) -> list[str]:
    return ["row_id", *[attr.name for attr in target.attributes]]


def _returning_cols(target: HeadTarget) -> str:
    return ", ".join(ident(name) for name in _column_names(target))


def _translate(exc: BaseException) -> BaseException:
    if isinstance(exc, (EntityRowNotFound, EntityRowConflict, EntityRowInvalid,
                        EntityRowLimitExceeded, EntityNotServing,
                        PlatformCapacityExceeded)):
        return exc
    mapped = map_platform_db_error(exc)
    if mapped is not None:
        return mapped
    state = _sqlstate(exc)
    if state == "23505":
        return EntityRowConflict()
    if state in {"23502", "23514"} or (state and state.startswith("22")):
        return EntityRowInvalid()
    if state == "42P01":
        return EntityNotServing()
    return exc


def _sqlstate(exc: BaseException) -> str | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "pgcode", None) or getattr(current, "sqlstate", None)
        if isinstance(code, str) and code:
            return code
        orig = getattr(current, "orig", None)
        if isinstance(orig, BaseException):
            code = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
            if isinstance(code, str) and code:
                return code
        current = current.__cause__ or current.__context__
    return None
