"""Channel SQL result mapping. No database."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.channel.nodes import list_node_types
from backend.channel.sql_read import SqlReadError, run_channel_sql
from backend.tests.channel_hooks_fake import FakeHooks
from backend.entity.statements import (
    EntityStatement,
    EntityStatementRejected,
    execute_entity_statement,
)
from backend.metadata.connectors.base import (
    SourceEndpoint,
    StatementResult,
    consume_statement,
)
from backend.metadata.connectors.mssql import MssqlConnector
from backend.metadata.connectors.oracle import OracleConnector
from backend.metadata.connectors.postgresql import PostgresqlConnector
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


def test_one_statement_count_accepts_engine_placeholders() -> None:
    accepted = (
        ("postgresql", "INSERT INTO t (code) VALUES (%s)"),
        ("mssql", "INSERT INTO t (code) VALUES (%s)"),
        ("oracle", "INSERT INTO t (a, b) VALUES (:1, :2)"),
        ("oracle", "SELECT 'a;b' FROM t WHERE id = :1"),
        ("mssql", "SELECT %s FROM t -- ; SELECT 2"),
        ("oracle", "SELECT :1 FROM t /* ; SELECT :2 FROM t */"),
        ("mssql", "IF 1=1 SELECT %s ELSE SELECT 2"),
    )
    rejected = (
        ("postgresql", "SELECT %s; SELECT %s"),
        ("mssql", "IF 1=1 SELECT %s; DROP TABLE t"),
        ("mssql", "WHILE 1=1 SELECT %s; DROP TABLE t"),
        ("mssql", "INSERT INTO t (code) VALUES (%s); DROP TABLE t"),
        ("mssql", "SELECT '%s'; SELECT %s"),
        ("oracle", "INSERT INTO t (a, b) VALUES (:1, :2); DROP TABLE t"),
        ("oracle", "SELECT ':1' FROM t; SELECT :2 FROM t"),
        ("postgresql", "SELECT 1; SELECT 2"),
        ("mssql", "SELECT 1; SELECT 2"),
        ("oracle", "SELECT 1; SELECT 2"),
    )
    for engine, sql in accepted:
        prove_one_statement(sql, engine=engine)
    for engine, sql in rejected:
        with pytest.raises(SqlNotOneStatement):
            prove_one_statement(sql, engine=engine)


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


class _BoundResult:
    returns_rows = False
    rowcount = 1


class _BoundConn:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def execute(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def exec_driver_sql(self, sql: str, *args: object) -> _BoundResult:
        self.calls.append((sql, args))
        return _BoundResult()


class _BoundBegin:
    def __init__(self, conn: _BoundConn) -> None:
        self._conn = conn

    def __enter__(self) -> _BoundConn:
        return self._conn

    def __exit__(self, *args: object) -> bool:
        del args
        return False


class _BoundEngine:
    def __init__(self, conn: _BoundConn) -> None:
        self._conn = conn

    def begin(self) -> _BoundBegin:
        return _BoundBegin(self._conn)


def test_entity_statement_binds_values_and_leaves_an_absent_list_off_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _BoundConn()
    monkeypatch.setattr(
        "backend.entity.statements.get_entity_engine", lambda: _BoundEngine(conn)
    )
    sql = "INSERT INTO t (code) VALUES (%s)"
    execute_entity_statement(sql, timeout_sec=1, max_rows=1)
    assert conn.calls == [(sql, ())]
    value = "O'Brien; DROP TABLE t"
    execute_entity_statement(sql, timeout_sec=1, max_rows=1, params=(value, None))
    assert conn.calls[-1] == (sql, ((value, None),))
    execute_entity_statement("SELECT 1", timeout_sec=1, max_rows=1, params=())
    assert conn.calls[-1] == ("SELECT 1", ((),))


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
                params: object = None,
            ) -> StatementResult:
                del endpoint, max_rows, timeout_sec, params
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


def test_source_statement_passes_bound_values_for_each_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str, object]] = []
    value = "O'Brien; DROP TABLE t"

    def prepare(*, engine: str, access: dict[str, object]) -> PreparedEngine:
        del access
        endpoint = SourceEndpoint(
            engine=engine,
            host="db.example",
            port=5432,
            username="reader",
            password="secret",
            database_name="app",
            schema_filter="public",
            ssl_mode="disable",
        )

        class _Connector:
            def run_statement(
                self,
                endpoint: SourceEndpoint,
                sql: str,
                *,
                max_rows: int,
                timeout_sec: int,
                params: object = None,
            ) -> StatementResult:
                del endpoint, max_rows, timeout_sec
                seen.append((engine, sql, params))
                return StatementResult(columns=[], rows=[], rowcount=1, truncated=False)

        return PreparedEngine(connector=_Connector(), endpoint=endpoint)

    monkeypatch.setattr(
        "backend.metadata.source_statements.get_source_store",
        lambda: _Store(),
    )
    monkeypatch.setattr(
        "backend.metadata.source_statements.decrypt_access_blob",
        lambda blob: {},
    )
    monkeypatch.setattr("backend.metadata.source_statements.prepare", prepare)

    cases = (
        ("postgresql", "INSERT INTO t (code) VALUES (%s)", (value,)),
        ("mssql", "INSERT INTO t (code) VALUES (%s)", (value, None)),
        ("oracle", "INSERT INTO t (a, b) VALUES (:1, :2)", (value, 2)),
    )
    for engine, sql, params in cases:
        _install_source(monkeypatch, engine)
        execute_source_statement(
            "src_live", sql, timeout_sec=1, max_rows=1, params=params
        )
    assert seen == [
        ("postgresql", "INSERT INTO t (code) VALUES (%s)", (value,)),
        ("mssql", "INSERT INTO t (code) VALUES (%s)", (value, None)),
        ("oracle", "INSERT INTO t (a, b) VALUES (:1, :2)", (value, 2)),
    ]
    assert value not in seen[0][1]
    _install_source(monkeypatch, "postgresql")
    execute_source_statement(
        "src_live", "SELECT 1", timeout_sec=1, max_rows=1
    )
    assert seen[-1] == ("postgresql", "SELECT 1", None)


class _Store:
    def __init__(self, engine: str = "postgresql") -> None:
        self.record = SimpleNamespace(
            status="active", engine=engine, access_ciphertext=b"cipher"
        )

    def get_source(self, source_id: str) -> SimpleNamespace:
        del source_id
        return self.record


def _install_source(monkeypatch: pytest.MonkeyPatch, engine: str) -> None:
    monkeypatch.setattr(
        "backend.metadata.source_statements.get_source_store",
        lambda: _Store(engine),
    )


class _DriverResult:
    returns_rows = False
    rowcount = 0


class _DriverConn:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def __enter__(self) -> _DriverConn:
        return self

    def __exit__(self, *args: object) -> bool:
        del args
        return False

    def execute(self, *args: object, **kwargs: object) -> _DriverResult:
        del args, kwargs
        return _DriverResult()

    def exec_driver_sql(self, sql: str, *args: object) -> _DriverResult:
        self.calls.append((sql, args))
        return _DriverResult()

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class _DriverEngine:
    def __init__(self, conn: _DriverConn) -> None:
        self._conn = conn

    def connect(self) -> _DriverConn:
        return self._conn

    def dispose(self) -> None:
        return None


def test_each_connector_binds_values_and_omits_an_absent_parameter_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = "O'Brien; DROP TABLE t"
    cases = (
        (PostgresqlConnector(), "postgresql", "INSERT INTO t (code) VALUES (%s)", (value,)),
        (MssqlConnector(), "mssql", "INSERT INTO t (code) VALUES (%s)", (value, None)),
        (OracleConnector(), "oracle", "INSERT INTO t (a, b) VALUES (:1, :2)", (value, 2)),
    )
    for connector, engine, sql, params in cases:
        conn = _DriverConn()
        monkeypatch.setattr(connector, "_engine", lambda *args, **kwargs: _DriverEngine(conn))
        endpoint = SourceEndpoint(
            engine=engine,
            host="db.example",
            port=5432,
            username="reader",
            password="secret",
            database_name="app",
            schema_filter="public",
            ssl_mode="disable",
        )
        connector.run_statement(endpoint, sql, max_rows=10, timeout_sec=5)
        assert conn.calls == [(sql, ())]
        connector.run_statement(
            endpoint, sql, max_rows=10, timeout_sec=5, params=params
        )
        assert conn.calls[-1] == (sql, (tuple(params),))
        assert value not in conn.calls[-1][0]


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


def test_sql_node_renders_scalar_parameters_and_rejects_structured_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    def run(
        statement: str,
        *,
        source: dict[str, object],
        statement_timeout_sec: int,
        params: object = None,
    ) -> dict[str, object]:
        del source, statement_timeout_sec
        seen.append((statement, params))
        return {"rows": [], "count": 0, "rowcount": 1}

    monkeypatch.setattr("backend.channel.nodes.read.sql.run_channel_sql", run)
    execute = next(item.execute for item in list_node_types() if item.type_id == "read.sql")
    values = {
        "name": "O'Brien; DROP TABLE t",
        "flag": True,
        "empty": None,
        "blob": {"a": 1},
        "items": [1],
    }
    hooks = FakeHooks(evaluate=lambda expression: values[expression])
    sql = "INSERT INTO t (code, flag, note) VALUES (%s, %s, %s)"
    result = execute(
        {
            "id": "nd_sql",
            "type": "read.sql",
            "config": {
                "source": {"kind": "entity"},
                "sql": sql,
                "params": ["{{ name }}", "{{ flag }}", "{{ empty }}"],
            },
        },
        hooks,
    )
    assert result.status == "succeeded", result.error_message
    assert seen == [(sql, ["O'Brien; DROP TABLE t", True, None])]

    seen.clear()
    literal = execute(
        {
            "id": "nd_sql",
            "type": "read.sql",
            "config": {
                "source": {"kind": "entity"},
                "sql": "SELECT %s AS n",
                "params": ["42"],
            },
        },
        hooks,
    )
    assert literal.status == "succeeded", literal.error_message
    assert seen == [("SELECT %s AS n", [42])]

    seen.clear()
    for expression in ("{{ blob }}", "{{ items }}"):
        failed = execute(
            {
                "id": "nd_sql",
                "type": "read.sql",
                "config": {
                    "source": {"kind": "entity"},
                    "sql": "SELECT %s",
                    "params": [expression],
                },
            },
            hooks,
        )
        assert failed.status == "failed"
        assert failed.error_code == "CHANNEL_VALUE_TYPE_MISMATCH"
    assert seen == []

    seen.clear()
    omitted = execute(
        {
            "id": "nd_sql",
            "type": "read.sql",
            "config": {"source": {"kind": "entity"}, "sql": "SELECT 1"},
        },
        hooks,
    )
    assert omitted.status == "succeeded", omitted.error_message
    assert seen == [("SELECT 1", None)]


def test_publish_does_not_inspect_statement_placeholders() -> None:
    from backend.channel.graph import validate

    class _Resolver:
        def entity_head(self, entity_id: str) -> None:
            del entity_id
            return None

        def channel_exists(self, channel_id: str) -> bool:
            del channel_id
            return False

        def published_trigger_type(self, channel_id: str) -> None:
            del channel_id
            return None

        def source_exists(self, source_id: str) -> bool:
            del source_id
            return False

    graph = {
        "nodes": [
            {
                "id": "nd_trigger",
                "ref": "trigger",
                "type": "trigger.manual",
                "name": "Run",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_read",
                "ref": "read",
                "type": "read.sql",
                "name": "Read",
                "position": {"x": 0, "y": 0},
                "config": {
                    "source": {"kind": "entity"},
                    "sql": "INSERT INTO t (code) VALUES (%s); DROP TABLE t",
                    "params": ['"O\'Brien; DROP TABLE t"'],
                },
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "ed_1",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_read", "port": "main"},
            }
        ],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }
    problems = validate(graph, _Resolver())
    assert [item for item in problems if item.severity == "error"] == []


def test_run_channel_sql_forwards_bound_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str, object]] = []
    value = "O'Brien; DROP TABLE t"

    def entity(
        sql: str,
        *,
        timeout_sec: int,
        max_rows: int,
        params: object = None,
    ) -> EntityStatement:
        del timeout_sec, max_rows
        seen.append(("entity", sql, params))
        return EntityStatement(rows=[], rowcount=1)

    def source(
        source_id: str,
        sql: str,
        *,
        timeout_sec: int,
        max_rows: int,
        params: object = None,
    ) -> StatementResult:
        del source_id, timeout_sec, max_rows
        seen.append(("source", sql, params))
        return StatementResult(columns=[], rows=[], rowcount=1, truncated=False)

    monkeypatch.setattr("backend.channel.sql_read.execute_entity_statement", entity)
    monkeypatch.setattr("backend.channel.sql_read.execute_source_statement", source)
    run_channel_sql(
        "INSERT INTO t (code) VALUES (%s)",
        source={"kind": "entity"},
        statement_timeout_sec=30,
        params=(value, None),
    )
    run_channel_sql(
        "SELECT 1",
        source={"kind": "entity"},
        statement_timeout_sec=30,
    )
    run_channel_sql(
        "INSERT INTO t (a, b) VALUES (:1, :2)",
        source={"kind": "source", "source_id": "src_live"},
        statement_timeout_sec=30,
        params=(value, 2),
    )
    assert seen == [
        ("entity", "INSERT INTO t (code) VALUES (%s)", (value, None)),
        ("entity", "SELECT 1", None),
        ("source", "INSERT INTO t (a, b) VALUES (:1, :2)", (value, 2)),
    ]
    assert value not in seen[0][1]


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
