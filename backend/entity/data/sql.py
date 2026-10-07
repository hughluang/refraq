"""Entity-database SQL for Entity Data API action verbs.

Reads select the caller's profile view on the reader connection. Writes run on the
owner connection against the physical table and return only ``row_id``; the caller
presents written rows through its read view.
"""

from __future__ import annotations

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
from backend.entity.ddl import ident
from backend.entity.entity_db import get_entity_engine, get_entity_reader_engine
from backend.entity.errors import (
    EntityNotServing,
    EntityRowConflict,
    EntityRowInvalid,
    EntityRowLimitExceeded,
    EntityRowNotFound,
)

__all__ = [
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
    "update_ids",
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
    return target.read_relation or target.qualified_table


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
    returning = _returning_cols(target)
    relation = target.qualified_table if lock else _read_from(target)
    sql = (
        f"SELECT {returning} FROM {relation} "
        f"WHERE {ident(column)} = :_locator"
        + (" FOR UPDATE" if lock else "")
    )
    row = conn.execute(text(sql), {"_locator": value}).one_or_none()
    if row is None:
        raise EntityRowNotFound()
    return decode_row(_column_names(target), tuple(row), target)


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
    sql = (
        f"UPDATE {target.qualified_table} SET {assigns} "
        f"WHERE {ident('row_id')} = ANY(:ids)"
    )
    result = conn.execute(text(sql), params)
    return int(result.rowcount or 0)


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
    return [decode_row(names, tuple(row), target) for row in rows]


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
