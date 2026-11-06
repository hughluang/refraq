"""Execute one prepared Entity SQL statement on the reader pool.

The transaction is read-only and always rolls back. The signed context is
local to that transaction. The bound statement is one extended-protocol query
with no parameters.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from backend.admin.user_store import UserRecord
from backend.core.db import map_platform_db_error
from backend.core.errors import AppError, PlatformCapacityExceeded
from backend.entity.access.context import CONTEXT_TTL_SEC, issue_contexts
from backend.entity.access.enforce import _signing_ring, append_sql_log
from backend.entity.access.membership import person_of
from backend.entity.entity_db import get_entity_reader_engine
from backend.entity.errors import EntitySqlFailed, EntitySqlTimeout
from backend.entity.mcp.sql_encode import encode_sql_value
from backend.entity.mcp.sql_errors import rewrite_sql_message
from backend.entity.mcp.sql_prepare import PreparedSql, prepare_entity_sql
from backend.entity.parameters import entity_query_max_rows, entity_query_timeout_sec

_SKIP_AUDIT = frozenset(
    {
        "PLATFORM_CAPACITY_EXCEEDED",
        "ADMISSION_CAPACITY_EXCEEDED",
        "ADMISSION_ACTOR_LIMIT_EXCEEDED",
    }
)
_TIMEOUT_TYPE_NAMES = frozenset({"QueryCanceled"})


def run_entity_sql(
    sql: str,
    user: UserRecord,
    *,
    pat_id: str | None,
    request_id: str | None,
    max_rows: int | None,
) -> dict[str, Any]:
    """Prepare, sign, execute, and append one access-log row per Entity.

    Gate rejection and an unknown or invisible name raise before execution and
    write no access log. ``sql`` in the result is the submitted text.
    """

    prepared = prepare_entity_sql(sql, user)
    timeout_sec = int(entity_query_timeout_sec())
    cap = int(entity_query_max_rows())
    limit = cap if max_rows is None else min(cap, max(1, int(max_rows)))
    ttl_sec = max(CONTEXT_TTL_SEC, timeout_sec + 30)
    token = _sign(prepared, user, request_id or "", ttl_sec)
    started = time.perf_counter()
    try:
        presented = _execute(prepared, token, limit, timeout_sec)
    except AppError as exc:
        if exc.code not in _SKIP_AUDIT:
            _audit(prepared, user, pat_id, request_id, exc.code, None, started)
        raise
    except Exception as exc:
        mapped = _map_execution_error(exc, prepared)
        if mapped is None:
            raise
        if mapped.code not in _SKIP_AUDIT:
            _audit(prepared, user, pat_id, request_id, mapped.code, None, started)
        raise mapped from exc
    _audit(prepared, user, pat_id, request_id, "ok", presented["row_count"], started)
    return presented


def _sign(
    prepared: PreparedSql,
    user: UserRecord,
    request_id: str,
    ttl_sec: int,
) -> str:
    person = prepared.decisions[0].person if prepared.decisions else person_of(user)
    try:
        ring = _signing_ring()
    except Exception as exc:
        mapped = map_platform_db_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    policies = tuple((access.policy, access.compiled) for access in prepared.decisions)
    return issue_contexts(
        policies,
        person,
        ring,
        action="read",
        request_id=request_id,
        ttl_sec=ttl_sec,
    )


def _execute(
    prepared: PreparedSql,
    token: str,
    limit: int,
    timeout_sec: int,
) -> dict[str, Any]:
    engine = get_entity_reader_engine()
    try:
        sa_conn = engine.connect()
    except PoolTimeoutError as exc:
        mapped = map_platform_db_error(exc)
        raise (mapped or PlatformCapacityExceeded()) from exc
    try:
        return _query(sa_conn, prepared, token, limit, timeout_sec)
    finally:
        sa_conn.close()


def _query(
    sa_conn: Any,
    prepared: PreparedSql,
    token: str,
    limit: int,
    timeout_sec: int,
) -> dict[str, Any]:
    transaction = None
    body_error: BaseException | None = None
    try:
        transaction = sa_conn.begin()
        sa_conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        sa_conn.exec_driver_sql(
            "SELECT set_config('app.ctx', %s, true)",
            (token,),
        )
        timeout_ms = int(timeout_sec) * 1000
        sa_conn.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")
        raw = _driver(sa_conn)
        with raw.cursor() as cursor:
            _execute_bound(cursor, prepared.bound_sql)
            description = cursor.description
            fetched = cursor.fetchmany(limit + 1) if description else []
        type_names = _load_type_names(raw, description)
        columns, rows, truncated = _present(
            description, fetched, type_names, prepared, limit
        )
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "max_rows": limit,
            "sql": prepared.submitted_sql,
            "entities": list(prepared.entities),
            "partial_columns": [
                {"table_name": item.table_name, "column": item.column}
                for item in prepared.partial_columns
            ],
        }
    except Exception as exc:
        body_error = exc
        raise
    finally:
        if transaction is not None:
            try:
                transaction.rollback()
            except Exception:
                if body_error is None:
                    raise


def _execute_bound(cursor: Any, sql: str) -> None:
    """One extended-protocol statement, with no client parameters.

    ``Cursor.execute(sql)`` with no parameters uses the simple query protocol
    (``PQsendQuery``), which runs every statement in the string. ``binary=True``
    keeps parameters unset (so ``%`` stays literal) and selects
    ``PQsendQueryParams``, which rejects a second statement. The psycopg cursor
    is slotted, so ``_execute_send`` cannot be replaced.
    """

    cursor.execute(sql, binary=True)


def _driver(sa_conn: Any) -> Any:
    fairy = sa_conn.connection
    raw = getattr(fairy, "driver_connection", None)
    if raw is None:
        raw = getattr(fairy, "dbapi_connection", None)
    if raw is None:
        raise RuntimeError("reader connection has no driver")
    return raw


def _load_type_names(raw: Any, description: Any) -> dict[int, str]:
    if not description:
        return {}
    oids = list(dict.fromkeys(oid for oid in (_column_oid(col) for col in description) if oid))
    if not oids:
        return {}
    with raw.cursor() as meta:
        meta.execute(
            "SELECT oid, typname FROM pg_catalog.pg_type WHERE oid = ANY(%s)",
            (oids,),
        )
        found = meta.fetchall()
    return {int(oid): str(typname) for oid, typname in found}


def _present(
    description: Any,
    fetched: Any,
    type_names: dict[int, str],
    prepared: PreparedSql,
    limit: int,
) -> tuple[list[dict[str, str]], list[list[Any]], bool]:
    physical = _physical_names(prepared)
    columns: list[dict[str, str]] = []
    raw_types: list[str] = []
    for column in description or []:
        oid = _column_oid(column)
        raw_type = type_names.get(oid or -1, "unknown")
        shown = rewrite_sql_message(raw_type, prepared.views, physical=physical)
        columns.append({"name": _column_name(column), "type": shown})
        raw_types.append(raw_type)
    truncated = len(fetched) > limit
    rows: list[list[Any]] = []
    for fetched_row in list(fetched)[:limit]:
        rows.append(
            [
                encode_sql_value(value, raw_types[index])
                for index, value in enumerate(fetched_row)
            ]
        )
    return columns, rows, truncated


def _physical_names(prepared: PreparedSql) -> dict[str, str]:
    found: dict[str, str] = {}
    for access in prepared.decisions:
        table_name = access.target.entity.table_name
        names = (
            access.target.physical_table,
            access.full.physical_table,
            access.head.physical,
        )
        for name in names:
            if isinstance(name, str) and name and name != table_name:
                found[name] = table_name
    return found


def _column_name(column: Any) -> str:
    name = getattr(column, "name", None)
    if name is None:
        name = column[0]
    return str(name)


def _column_oid(column: Any) -> int | None:
    code = getattr(column, "type_code", None)
    if code is None and not hasattr(column, "type_code"):
        try:
            code = column[1]
        except (TypeError, IndexError):
            return None
    if code is None:
        return None
    return int(code)


def _audit(
    prepared: PreparedSql,
    user: UserRecord,
    pat_id: str | None,
    request_id: str | None,
    outcome_code: str,
    row_count: int | None,
    started: float,
) -> None:
    elapsed = int((time.perf_counter() - started) * 1000)
    digest = hashlib.sha256(prepared.submitted_sql.encode("utf-8")).hexdigest()
    for access in prepared.decisions:
        shape = access.outcome.shape
        append_sql_log(
            user_id=user.id,
            request_id=request_id,
            pat_id=pat_id,
            entity_id=access.target.entity.id,
            effective_grant_ids=list(access.outcome.grant_ids),
            view_name=shape.view_name if shape is not None else None,
            policy_revision=int(access.revision),
            row_count=row_count,
            outcome_code=outcome_code,
            duration_ms=elapsed,
            sql_sha256=digest,
            statement_summary=prepared.submitted_sql,
        )


def _map_execution_error(exc: BaseException, prepared: PreparedSql) -> Any:
    if isinstance(exc, PoolTimeoutError):
        return map_platform_db_error(exc) or PlatformCapacityExceeded()
    if _is_timeout(exc):
        return EntitySqlTimeout()
    mapped = map_platform_db_error(exc)
    if mapped is not None:
        return mapped
    state = _sqlstate(exc)
    if state or _looks_like_database_error(exc):
        primary = rewrite_sql_message(
            _primary_message(exc),
            prepared.views,
            physical=_physical_names(prepared),
        )
        if state:
            primary = f"{primary} (SQLSTATE {state})"
        return EntitySqlFailed(primary, sqlstate=state)
    return None


def _is_timeout(exc: BaseException) -> bool:
    if _sqlstate(exc) == "57014":
        return True
    for item in _chain(exc):
        if type(item).__name__ in _TIMEOUT_TYPE_NAMES:
            return True
    return False


def _looks_like_database_error(exc: BaseException) -> bool:
    for item in _chain(exc):
        module = type(item).__module__
        if module.startswith("psycopg") or module.startswith("sqlalchemy.exc"):
            if type(item).__name__ in {"TimeoutError", "PoolTimeoutError"}:
                continue
            if module.startswith("psycopg") or type(item).__name__ in {
                "DBAPIError",
                "OperationalError",
                "ProgrammingError",
                "DataError",
                "IntegrityError",
                "InternalError",
                "DatabaseError",
            }:
                return True
    return False


def _sqlstate(exc: BaseException) -> str | None:
    for item in _chain(exc):
        code = getattr(item, "sqlstate", None) or getattr(item, "pgcode", None)
        if isinstance(code, str) and code:
            return code
    return None


def _primary_message(exc: BaseException) -> str:
    for item in _chain(exc):
        diag = getattr(item, "diag", None)
        primary = getattr(diag, "message_primary", None) if diag is not None else None
        if isinstance(primary, str) and primary.strip():
            return primary
    return "Entity SQL execution failed"


def _chain(exc: BaseException) -> list[BaseException]:
    seen: set[int] = set()
    out: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        out.append(current)
        orig = getattr(current, "orig", None)
        if isinstance(orig, BaseException) and id(orig) not in seen:
            seen.add(id(orig))
            out.append(orig)
        current = current.__cause__ or current.__context__
    return out
