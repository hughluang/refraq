"""Entity-database SQL for Entity Data API action verbs."""

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
from backend.entity.entity_db import get_entity_engine
from backend.entity.errors import (
    EntityNotServing,
    EntityRowConflict,
    EntityRowInvalid,
    EntityRowLimitExceeded,
    EntityRowNotFound,
)

__all__ = [
    "delete_by_id",
    "delete_where",
    "entity_connection",
    "insert_one",
    "query_keyset",
    "query_offset",
    "require_entity_capacity",
    "select_by_id",
    "update_by_id",
    "update_where",
    "upsert_row",
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


@contextmanager
def entity_connection() -> Iterator[Connection]:
    engine = require_entity_capacity()
    try:
        with engine.begin() as conn:
            yield conn
    except Exception as exc:
        raise _translate(exc) from exc


def insert_one(
    conn: Connection, target: HeadTarget, values: dict[str, Any]
) -> dict[str, Any]:
    columns = list(values.keys())
    col_sql = ", ".join(ident(name) for name in columns)
    param_sql = ", ".join(f":{name}" for name in columns)
    returning = _returning_cols(target)
    sql = (
        f"INSERT INTO {target.qualified_table} ({col_sql}) "
        f"VALUES ({param_sql}) RETURNING {returning}"
    )
    row = conn.execute(text(sql), values).one()
    return decode_row(_column_names(target), tuple(row), target)


def select_by_id(
    conn: Connection, target: HeadTarget, row_id: int
) -> dict[str, Any]:
    returning = _returning_cols(target)
    sql = (
        f"SELECT {returning} FROM {target.qualified_table} "
        f"WHERE {ident('row_id')} = :row_id"
    )
    row = conn.execute(text(sql), {"row_id": row_id}).one_or_none()
    if row is None:
        raise EntityRowNotFound()
    return decode_row(_column_names(target), tuple(row), target)


def update_by_id(
    conn: Connection,
    target: HeadTarget,
    row_id: int,
    values: dict[str, Any],
) -> dict[str, Any]:
    assigns = ", ".join(f"{ident(name)} = :{name}" for name in values)
    returning = _returning_cols(target)
    params = dict(values)
    params["row_id"] = row_id
    sql = (
        f"UPDATE {target.qualified_table} SET {assigns} "
        f"WHERE {ident('row_id')} = :row_id RETURNING {returning}"
    )
    row = conn.execute(text(sql), params).one_or_none()
    if row is None:
        raise EntityRowNotFound()
    return decode_row(_column_names(target), tuple(row), target)


def delete_by_id(conn: Connection, target: HeadTarget, row_id: int) -> None:
    sql = (
        f"DELETE FROM {target.qualified_table} "
        f"WHERE {ident('row_id')} = :row_id"
    )
    result = conn.execute(text(sql), {"row_id": row_id})
    if result.rowcount == 0:
        raise EntityRowNotFound()


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
        f"SELECT {select_cols} FROM {target.qualified_table}{where_sql} "
        f"ORDER BY {ident('row_id')} ASC LIMIT :_limit OFFSET :_offset"
    )
    params = dict(params)
    params["_limit"] = limit
    params["_offset"] = offset
    rows = conn.execute(text(sql), params).all()
    items = [decode_row(fields, tuple(row), target) for row in rows]
    total: int | None = None
    if include_total:
        count_sql = f"SELECT count(*) FROM {target.qualified_table}{where_sql}"
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
        f"SELECT {select_cols} FROM {target.qualified_table}{where_sql} "
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


def update_where(
    conn: Connection,
    target: HeadTarget,
    *,
    compiled: CompiledFilter,
    values: dict[str, Any],
) -> int:
    ids = _lock_matching_ids(conn, target, compiled)
    if not ids:
        return 0
    assigns = ", ".join(f"{ident(name)} = :{name}" for name in values)
    params = dict(values)
    id_keys = []
    for index, row_id in enumerate(ids):
        key = f"_id{index}"
        params[key] = row_id
        id_keys.append(f":{key}")
    sql = (
        f"UPDATE {target.qualified_table} SET {assigns} "
        f"WHERE {ident('row_id')} IN ({', '.join(id_keys)})"
    )
    result = conn.execute(text(sql), params)
    return int(result.rowcount or 0)


def delete_where(
    conn: Connection,
    target: HeadTarget,
    *,
    compiled: CompiledFilter,
) -> int:
    ids = _lock_matching_ids(conn, target, compiled)
    if not ids:
        return 0
    params: dict[str, Any] = {}
    id_keys = []
    for index, row_id in enumerate(ids):
        key = f"_id{index}"
        params[key] = row_id
        id_keys.append(f":{key}")
    sql = (
        f"DELETE FROM {target.qualified_table} "
        f"WHERE {ident('row_id')} IN ({', '.join(id_keys)})"
    )
    result = conn.execute(text(sql), params)
    return int(result.rowcount or 0)


def upsert_row(
    conn: Connection,
    target: HeadTarget,
    *,
    key_name: str,
    key_value: Any,
    values: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """FOR UPDATE + INSERT ON CONFLICT DO NOTHING then SELECT/UPDATE.

    Returns (row, created).
    """
    lock_sql = (
        f"SELECT {ident('row_id')} FROM {target.qualified_table} "
        f"WHERE {ident(key_name)} = :key FOR UPDATE"
    )
    existing = conn.execute(text(lock_sql), {"key": key_value}).one_or_none()
    if existing is not None:
        row_id = int(existing[0])
        if not values:
            return select_by_id(conn, target, row_id), False
        updated = update_by_id(conn, target, row_id, values)
        return updated, False

    insert_values = dict(values)
    insert_values[key_name] = key_value
    columns = list(insert_values.keys())
    col_sql = ", ".join(ident(name) for name in columns)
    param_sql = ", ".join(f":{name}" for name in columns)
    insert_sql = (
        f"INSERT INTO {target.qualified_table} ({col_sql}) "
        f"VALUES ({param_sql}) "
        f"ON CONFLICT ({ident(key_name)}) DO NOTHING "
        f"RETURNING {ident('row_id')}"
    )
    inserted = conn.execute(text(insert_sql), insert_values).one_or_none()
    if inserted is not None:
        return select_by_id(conn, target, int(inserted[0])), True
    # Concurrent insert won; lock and update.
    existing = conn.execute(text(lock_sql), {"key": key_value}).one_or_none()
    if existing is None:
        raise EntityRowConflict()
    row_id = int(existing[0])
    if not values:
        return select_by_id(conn, target, row_id), False
    return update_by_id(conn, target, row_id, values), False


def _lock_matching_ids(
    conn: Connection, target: HeadTarget, compiled: CompiledFilter
) -> list[int]:
    where_sql, params = _where(compiled)
    sql = (
        f"SELECT {ident('row_id')} FROM {target.qualified_table}{where_sql} "
        f"ORDER BY {ident('row_id')} ASC "
        f"LIMIT {ROW_WRITE_LIMIT + 1} FOR UPDATE"
    )
    rows = conn.execute(text(sql), params).all()
    if len(rows) > ROW_WRITE_LIMIT:
        raise EntityRowLimitExceeded()
    return [int(row[0]) for row in rows]


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
