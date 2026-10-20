"""Run one channel SQL statement on the source the node selected."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic_core import to_jsonable_python
from sqlalchemy.exc import DBAPIError

from backend.entity.statements import (
    EntityStatementLimit,
    EntityStatementRejected,
    execute_entity_statement,
)
from backend.metadata.source_statements import (
    SourceStatementRejected,
    execute_source_statement,
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
) -> dict[str, Any]:
    """Execute one statement and return ``{rows, count, rowcount}``.

    Text that is not exactly one statement fails before either driver runs.
    More than ``ITEM_LIMIT`` rows fails the read.
    A database error fails the read with the database message.
    """
    kind = source["kind"]
    try:
        if kind == "entity":
            page = execute_entity_statement(
                statement,
                timeout_sec=statement_timeout_sec,
                max_rows=ITEM_LIMIT,
            )
            rows = [
                {key: _jsonable(value) for key, value in row.items()}
                for row in page.rows
            ]
            rowcount = page.rowcount
        else:
            page = execute_source_statement(
                source["source_id"],
                statement,
                timeout_sec=statement_timeout_sec,
                max_rows=ITEM_LIMIT,
            )
            if page.truncated:
                raise SqlReadError(
                    "CHANNEL_ITEM_LIMIT_EXCEEDED",
                    f"SQL returned more than {ITEM_LIMIT} rows",
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
    except (EntityStatementRejected, SourceStatementRejected):
        raise SqlReadError(
            "CHANNEL_SQL_NOT_ONE_STATEMENT",
            "SQL must be exactly one statement",
        ) from None
    except EntityStatementLimit:
        raise SqlReadError(
            "CHANNEL_ITEM_LIMIT_EXCEEDED",
            f"SQL returned more than {ITEM_LIMIT} rows",
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
    """Make one driver cell JSON-safe.

    ``memoryview`` is what drivers return for binary columns; Pydantic does not
    accept it. Invalid UTF-8 stays a channel failure with a fixed message.
    """
    if isinstance(value, memoryview):
        value = bytes(value)
    try:
        return to_jsonable_python(value)
    except UnicodeDecodeError as exc:
        raise SqlReadError(
            "CHANNEL_NODE_FAILED",
            "SQL value is not valid UTF-8 text",
        ) from exc
