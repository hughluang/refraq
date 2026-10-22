"""Channel SQL result mapping. No database."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.channel.sql_read import SqlReadError, run_channel_sql
from backend.entity.statements import EntityStatementRejected, execute_entity_statement
from backend.metadata.connectors.base import (
    SourceEndpoint,
    StatementResult,
    consume_statement,
)
from backend.metadata.connectors.runtime import PreparedEngine
from backend.metadata.query.guards import SqlNotOneStatement, prove_one_statement
from backend.metadata.source_statements import (
    SourceStatementRejected,
    execute_source_statement,
)

_SCRIPTS = (
    "SELECT 1; SELECT 2",
    "CREATE TABLE t (id int); INSERT INTO t VALUES (1)",
    "",
    "   ",
    ";",
    "SELECT (",
    "SELECT 'unterminated",
)
_ONE_STATEMENT = (
    "SELECT 1",
    "SELECT 1;",
    "SELECT 'a;b' AS label",
    "INSERT INTO t VALUES (1)",
)


class _Result:
    def __init__(
        self, *, returns_rows: bool, rowcount: int, rows: list[tuple[object, ...]]
    ) -> None:
        self.returns_rows = returns_rows
        self.rowcount = rowcount
        self._rows = rows

    def keys(self) -> list[str]:
        return ["code"]

    def __iter__(self):
        return iter(self._rows)


def test_consume_statement_keeps_a_write_rowcount() -> None:
    page = consume_statement(
        _Result(returns_rows=False, rowcount=2, rows=[]), max_rows=10
    )
    assert page.rows == []
    assert page.rowcount == 2
    assert page.truncated is False


def test_consume_statement_marks_a_truncated_result_set() -> None:
    page = consume_statement(
        _Result(returns_rows=True, rowcount=-1, rows=[("A",), ("B",)]),
        max_rows=1,
    )
    assert page.rows == [["A"]]
    assert page.rowcount is None
    assert page.truncated is True


def test_one_statement_count_agrees_for_each_source_engine() -> None:
    for engine in ("postgresql", "mssql", "oracle"):
        for sql in _SCRIPTS:
            with pytest.raises(SqlNotOneStatement):
                prove_one_statement(sql, engine=engine)
        for sql in _ONE_STATEMENT:
            prove_one_statement(sql, engine=engine)
    with pytest.raises(SqlNotOneStatement):
        prove_one_statement("SELECT 1", engine="unknown")


def test_entity_statement_stops_a_script_before_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    def engine() -> None:
        calls["n"] += 1
        raise AssertionError("engine")

    monkeypatch.setattr("backend.entity.statements.get_entity_engine", engine)
    for sql in _SCRIPTS:
        with pytest.raises(EntityStatementRejected):
            execute_entity_statement(sql, timeout_sec=1, max_rows=1)
    assert calls["n"] == 0
    for sql in _ONE_STATEMENT:
        with pytest.raises(AssertionError, match="engine"):
            execute_entity_statement(sql, timeout_sec=1, max_rows=1)
    assert calls["n"] == len(_ONE_STATEMENT)


def test_source_statement_stops_a_script_before_the_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []

    def prepare(*, engine: str, access: dict[str, object]) -> PreparedEngine:
        del engine, access
        endpoint = SourceEndpoint(
            engine="postgresql",
            host="db.example",
            port=5432,
            username="reader",
            password="secret",
            database_name="app",
            schema_filter="public",
        )

        class _Connector:
            engine = "postgresql"

            def run_statement(
                self,
                endpoint: SourceEndpoint,
                sql: str,
                *,
                max_rows: int,
                timeout_sec: int,
            ) -> StatementResult:
                del endpoint, max_rows, timeout_sec
                sent.append(sql)
                return StatementResult(columns=[], rows=[], rowcount=1, truncated=False)

        return PreparedEngine(connector=_Connector(), endpoint=endpoint)

    def decrypt(blob: bytes) -> dict[str, object]:
        del blob
        return {}

    record = SimpleNamespace(
        status="active", engine="mssql", access_ciphertext=b"cipher"
    )

    class _Store:
        def get_source(self, source_id: str) -> SimpleNamespace:
            del source_id
            return record

    monkeypatch.setattr(
        "backend.metadata.source_statements.get_source_store", lambda: _Store()
    )
    monkeypatch.setattr(
        "backend.metadata.source_statements.decrypt_access_blob", decrypt
    )
    monkeypatch.setattr("backend.metadata.source_statements.prepare", prepare)
    for sql in _SCRIPTS:
        with pytest.raises(SourceStatementRejected):
            execute_source_statement("src_live", sql, timeout_sec=1, max_rows=1)
    assert sent == []
    for sql in _ONE_STATEMENT:
        execute_source_statement("src_live", sql, timeout_sec=1, max_rows=1)
    assert sent == list(_ONE_STATEMENT)


def test_run_channel_sql_reports_a_script_before_either_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def engine() -> None:
        raise AssertionError("engine")

    monkeypatch.setattr("backend.entity.statements.get_entity_engine", engine)
    with pytest.raises(SqlReadError) as entity_raised:
        run_channel_sql(
            "CREATE TABLE t (id int); INSERT INTO t VALUES (1)",
            source={"kind": "entity"},
            statement_timeout_sec=30,
        )
    assert entity_raised.value.code == "CHANNEL_SQL_NOT_ONE_STATEMENT"

    def execute(
        source_id: str, sql: str, *, timeout_sec: int, max_rows: int
    ) -> StatementResult:
        del source_id, sql, timeout_sec, max_rows
        raise SourceStatementRejected()

    monkeypatch.setattr("backend.channel.sql_read.execute_source_statement", execute)
    with pytest.raises(SqlReadError) as source_raised:
        run_channel_sql(
            "SELECT 1; SELECT 2",
            source={"kind": "source", "source_id": "src_live"},
            statement_timeout_sec=30,
        )
    assert source_raised.value.code == "CHANNEL_SQL_NOT_ONE_STATEMENT"


def test_source_sql_returns_the_driver_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    def execute(
        source_id: str, sql: str, *, timeout_sec: int, max_rows: int
    ) -> StatementResult:
        assert source_id == "src_live"
        assert sql == "SELECT code FROM t"
        assert timeout_sec == 30
        assert max_rows == 100_000
        return StatementResult(
            columns=["code"], rows=[["A"]], rowcount=None, truncated=False
        )

    monkeypatch.setattr("backend.channel.sql_read.execute_source_statement", execute)
    assert run_channel_sql(
        "SELECT code FROM t",
        source={"kind": "source", "source_id": "src_live"},
        statement_timeout_sec=30,
    ) == {"rows": [{"code": "A"}], "count": 1, "rowcount": None}


def test_source_sql_fails_when_the_result_does_not_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def execute(
        source_id: str, sql: str, *, timeout_sec: int, max_rows: int
    ) -> StatementResult:
        del source_id, sql, timeout_sec, max_rows
        return StatementResult(columns=["n"], rows=[[1]], rowcount=None, truncated=True)

    monkeypatch.setattr("backend.channel.sql_read.execute_source_statement", execute)
    with pytest.raises(SqlReadError) as raised:
        run_channel_sql(
            "SELECT 1",
            source={"kind": "source", "source_id": "src_live"},
            statement_timeout_sec=30,
        )
    assert raised.value.code == "CHANNEL_ITEM_LIMIT_EXCEEDED"
    assert raised.value.message == "Use Dataset Query, then Batch Read."


def test_source_sql_decodes_utf8_and_fails_on_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def execute(
        source_id: str, sql: str, *, timeout_sec: int, max_rows: int
    ) -> StatementResult:
        del source_id, sql, timeout_sec, max_rows
        return StatementResult(
            columns=["blob"], rows=[[b"A"], [b"\xff"]], rowcount=None, truncated=False
        )

    monkeypatch.setattr("backend.channel.sql_read.execute_source_statement", execute)
    with pytest.raises(SqlReadError) as raised:
        run_channel_sql(
            "SELECT blob FROM t",
            source={"kind": "source", "source_id": "src_live"},
            statement_timeout_sec=30,
        )
    assert raised.value.code == "CHANNEL_NODE_FAILED"
    assert raised.value.message == "SQL value is not valid UTF-8 text"

    def text_only(
        source_id: str, sql: str, *, timeout_sec: int, max_rows: int
    ) -> StatementResult:
        del source_id, sql, timeout_sec, max_rows
        return StatementResult(
            columns=["blob"], rows=[[b"A"]], rowcount=None, truncated=False
        )

    monkeypatch.setattr("backend.channel.sql_read.execute_source_statement", text_only)
    assert run_channel_sql(
        "SELECT blob FROM t",
        source={"kind": "source", "source_id": "src_live"},
        statement_timeout_sec=30,
    )["rows"] == [{"blob": "A"}]


def test_source_sql_renders_driver_values_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def execute(
        source_id: str, sql: str, *, timeout_sec: int, max_rows: int
    ) -> StatementResult:
        del source_id, sql, timeout_sec, max_rows
        return StatementResult(
            columns=["n", "qty", "when", "id", "blob"],
            rows=[
                [
                    7,
                    Decimal("10.50"),
                    datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
                    UUID("12345678-1234-5678-1234-567812345678"),
                    memoryview(b"hi"),
                ]
            ],
            rowcount=1,
            truncated=False,
        )

    monkeypatch.setattr("backend.channel.sql_read.execute_source_statement", execute)
    assert run_channel_sql(
        "SELECT n FROM t",
        source={"kind": "source", "source_id": "src_live"},
        statement_timeout_sec=30,
    )["rows"] == [
        {
            "n": 7,
            "qty": "10.50",
            "when": "2020-01-02T03:04:05Z",
            "id": "12345678-1234-5678-1234-567812345678",
            "blob": "hi",
        }
    ]
