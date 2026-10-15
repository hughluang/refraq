"""Execute one author statement on a registered Source.

This is not Controlled Query. The statement is sent as written and the driver
result is returned.
"""

from __future__ import annotations

from backend.metadata.connectors.base import ConnectorError, StatementResult
from backend.metadata.connectors.runtime import prepare
from backend.metadata.errors import QueryMultiStatement, QueryNotReadonly
from backend.metadata.query.guards import (
    SqlNotOneStatement,
    assert_readonly_single_statement,
    prove_one_statement,
)
from backend.metadata.sources.access import decrypt_access_blob
from backend.metadata.sources.store import get_source_store

__all__ = [
    "SourceStatementNotReadonly",
    "SourceStatementRejected",
    "execute_source_statement",
    "guard_editor_source_sql",
    "source_exists",
]


class SourceStatementRejected(Exception):
    """The author text is not exactly one statement for the Source engine."""

    def __init__(self) -> None:
        super().__init__("SQL must be exactly one statement")


class SourceStatementNotReadonly(Exception):
    """Editor execution refused a Source statement the read-only guard rejects."""

    def __init__(self) -> None:
        super().__init__("Editor execution only runs read-only SQL on a Source")


def guard_editor_source_sql(source_id: str, sql: str) -> None:
    """Refuse a Source statement that is not one read-only statement.

    Does not open a connection. A missing Source is left for the caller, which
    already reports that the Source does not resolve.
    """
    record = get_source_store().get_source(source_id)
    if record is None or not record.engine:
        return
    try:
        assert_readonly_single_statement(sql, engine=record.engine)
    except (QueryNotReadonly, QueryMultiStatement) as exc:
        raise SourceStatementNotReadonly() from exc


def source_exists(source_id: str) -> bool:
    return get_source_store().get_source(source_id) is not None


def execute_source_statement(
    source_id: str,
    sql: str,
    *,
    timeout_sec: int,
    max_rows: int,
) -> StatementResult:
    """Run ``sql`` on the Source connection. Raises ``ConnectorError`` on failure."""
    record = get_source_store().get_source(source_id)
    if record is None:
        raise ConnectorError(
            "QUERY_ENDPOINT_FAILED",
            f"Source does not resolve: {source_id}",
        )
    if record.status != "active":
        raise ConnectorError("QUERY_ENDPOINT_FAILED", "Source is disabled")
    if not record.engine or not record.access_ciphertext:
        raise ConnectorError("QUERY_ENDPOINT_FAILED", "Source has no connection")
    try:
        prove_one_statement(sql, engine=record.engine)
    except SqlNotOneStatement as exc:
        raise SourceStatementRejected() from exc
    access = decrypt_access_blob(record.access_ciphertext)
    prepared = prepare(engine=record.engine, access=access)
    return prepared.connector.run_statement(
        prepared.endpoint,
        sql,
        max_rows=max_rows,
        timeout_sec=timeout_sec,
    )
