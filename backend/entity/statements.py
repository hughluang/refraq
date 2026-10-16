"""One statement on the entity owner connection for Data Channel SQL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Result
from sqlglot import parse
from sqlglot.errors import SqlglotError

from backend.entity.ddl import ENTITY_DATA_SCHEMA
from backend.entity.entity_db import get_entity_engine

__all__ = [
    "EntityStatement",
    "EntityStatementLimit",
    "EntityStatementRejected",
    "execute_entity_statement",
]


class EntityStatementRejected(Exception):
    """The text is not exactly one PostgreSQL statement."""

    def __init__(self) -> None:
        super().__init__("SQL must be exactly one statement")


class EntityStatementLimit(Exception):
    """The statement returned more rows than the caller will hold."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"statement returned more than {limit} rows")
        self.limit = limit


@dataclass(frozen=True)
class EntityStatement:
    rows: list[dict[str, Any]]
    rowcount: int | None


def _exactly_one_postgres_statement(sql: str) -> bool:
    """Same count as ``prove_one_statement`` for postgresql.

    Entity does not import metadata. One trailing semicolon is ignored.
    """
    cleaned = (sql or "").strip()
    body = cleaned[:-1].strip() if cleaned.endswith(";") else cleaned
    if not body:
        return False
    try:
        statements = [item for item in parse(body, read="postgres") if item is not None]
    except SqlglotError:
        return False
    return len(statements) == 1


def execute_entity_statement(
    sql: str,
    *,
    timeout_sec: int,
    max_rows: int,
) -> EntityStatement:
    """Run ``sql`` as the entity owner with ``search_path`` set to ``entity_data``.

    The text must already be exactly one statement. The transaction commits when
    this returns. A driver error rolls the transaction back. A result past
    ``max_rows`` raises and rolls back.
    """
    if not _exactly_one_postgres_statement(sql):
        raise EntityStatementRejected()
    with get_entity_engine().begin() as conn:
        return _run_statement(conn, sql, timeout_sec=timeout_sec, max_rows=max_rows)


def _run_statement(
    conn: Any,
    sql: str,
    *,
    timeout_sec: int,
    max_rows: int,
) -> EntityStatement:
    timeout_ms = str(max(1, int(timeout_sec)) * 1000)
    conn.execute(
        text("SELECT set_config('search_path', :path, true)"),
        {"path": ENTITY_DATA_SCHEMA},
    )
    conn.execute(
        text("SELECT set_config('statement_timeout', :ms, true)"),
        {"ms": timeout_ms},
    )
    conn.execute(
        text("SELECT set_config('lock_timeout', :ms, true)"),
        {"ms": timeout_ms},
    )
    result = conn.exec_driver_sql(sql)
    if not result.returns_rows:
        return EntityStatement(rows=[], rowcount=_rowcount(result))
    fetched = result.mappings().fetchmany(max_rows + 1)
    if len(fetched) > max_rows:
        raise EntityStatementLimit(max_rows)
    rows = [dict(row) for row in fetched]
    return EntityStatement(rows=rows, rowcount=_rowcount(result))


def _rowcount(result: Result[Any]) -> int | None:
    count = result.rowcount
    if count is None or count < 0:
        return None
    return int(count)
