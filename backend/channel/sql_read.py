"""Run one channel SQL statement on the source the node selected."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from backend.entity.statements import (
    EntityStatementLimit,
    EntityStatementRejected,
    execute_entity_statement,
)
from backend.metadata.source_statements import (
    SourceStatementNotReadonly,
    SourceStatementRejected,
    execute_source_statement,
    guard_editor_source_sql,
)

__all__ = ["ITEM_LIMIT", "SqlReadError", "run_channel_sql"]

ITEM_LIMIT = 100_000


class SqlReadError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def run_channel_sql(
    statement: str,
    *,
    source: Mapping[str, Any],
    statement_timeout_sec: int,
    max_rows: int = ITEM_LIMIT,
    rollback: bool = False,
    strict_limit: bool = True,
    editor: bool = False,
) -> dict[str, Any]:
    """Execute one statement and return ``{rows, count, rowcount}``.

    Text that is not exactly one statement fails before either driver runs.
    More than ``max_rows`` rows fails the read when ``strict_limit`` is set.
    A database error fails the read with the database message. ``rollback``
    applies only to the entity database: the statement runs and the transaction
    is rolled back. ``editor`` on a registered Source requires the Controlled
    Query read-only guard and does not send a rejected statement to the driver.
    """
    kind = source["kind"]
    try:
        if kind == "entity":
            page = execute_entity_statement(
                statement,
                timeout_sec=statement_timeout_sec,
                max_rows=max_rows,
                rollback=rollback,
                strict_limit=strict_limit,
            )
            rows = [
                {key: _jsonable(value) for key, value in row.items()}
                for row in page.rows
            ]
            rowcount = page.rowcount
        else:
            if editor:
                guard_editor_source_sql(str(source["source_id"]), statement)
            page = execute_source_statement(
                source["source_id"],
                statement,
                timeout_sec=statement_timeout_sec,
                max_rows=max_rows,
            )
            if page.truncated and strict_limit:
                raise SqlReadError(
                    "CHANNEL_ITEM_LIMIT_EXCEEDED",
                    f"SQL returned more than {max_rows} rows",
                )
            rows = [
                {
                    column: _jsonable(value)
                    for column, value in zip(page.columns, row, strict=False)
                }
                for row in page.rows
            ]
            rowcount = page.rowcount
    except SqlReadError:
        raise
    except SourceStatementNotReadonly as exc:
        raise SqlReadError("CHANNEL_NODE_FAILED", str(exc)) from exc
    except (EntityStatementRejected, SourceStatementRejected):
        raise SqlReadError(
            "CHANNEL_SQL_NOT_ONE_STATEMENT",
            "SQL must be exactly one statement",
        ) from None
    except EntityStatementLimit:
        raise SqlReadError(
            "CHANNEL_ITEM_LIMIT_EXCEEDED",
            f"SQL returned more than {max_rows} rows",
        ) from None
    except DBAPIError as exc:
        raise SqlReadError("CHANNEL_NODE_FAILED", _db_message(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise SqlReadError("CHANNEL_NODE_FAILED", str(exc)) from exc
    return {"rows": rows, "count": len(rows), "rowcount": rowcount}


def _db_message(exc: DBAPIError) -> str:
    origin = exc.orig
    text_value = str(origin or exc).strip()
    return text_value or "SQL statement failed"


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SqlReadError(
                "CHANNEL_NODE_FAILED",
                "SQL value is not valid UTF-8 text",
            ) from exc
    return value
