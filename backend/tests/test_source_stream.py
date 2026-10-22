"""Stream one statement from a Source engine. Driver fakes stand in for the network."""

from __future__ import annotations

from backend.metadata.connectors.base import SourceEndpoint


class _Cursor:
    def __init__(self, raw: "_Raw", name: str | None) -> None:
        self.raw = raw
        self.name = name
        self.itersize: int | None = None
        self.closed = False
        self._rows: list[tuple[object, ...]] = []
        self._one: tuple[object, ...] | None = None

    def execute(self, sql: str, params: object = None) -> None:
        self.raw.statements.append((sql, params))
        if params is not None and "format_type" in sql:
            oid = params[0]
            self._one = (_Raw.FORMAT[oid],)
            return
        if sql == _Raw.AUTHOR:
            self._rows = list(_Raw.ROWS)

    def fetchone(self) -> tuple[object, ...] | None:
        return self._one

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self.raw.fetches.append(size)
        chunk = self._rows[:size]
        self._rows = self._rows[size:]
        return chunk

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> bool:
        self.close()
        return False

    @property
    def description(self) -> list["_Column"]:
        return [_Column(name) for name, _oid, _mod in _Raw.FIELDS]

    @property
    def pgresult(self) -> "_Result":
        return _Result()


class _Column:
    def __init__(self, name: str) -> None:
        self.name = name


class _Result:
    def ftype(self, index: int) -> int:
        return _Raw.FIELDS[index][1]

    def fmod(self, index: int) -> int:
        return _Raw.FIELDS[index][2]


class _Raw:
    AUTHOR = "SELECT n, qty FROM generate_series(1, 3) AS n"
    FIELDS = (("n", 23, -1), ("qty", 1700, 786434))
    FORMAT = {23: "integer", 1700: "numeric(12,2)"}
    ROWS = ((1, "1.50"), (2, "2.50"), (3, "3.50"))

    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []
        self.fetches: list[int] = []
        self.cursors: list[_Cursor] = []

    def cursor(self, name: str | None = None) -> _Cursor:
        cursor = _Cursor(self, name)
        self.cursors.append(cursor)
        return cursor


class _Connection:
    def __init__(self, raw: _Raw) -> None:
        self.connection = self
        self.driver_connection = raw
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Engine:
    def __init__(self, raw: _Raw) -> None:
        self.raw = raw
        self.connection = _Connection(raw)
        self.disposed = False

    def connect(self) -> _Connection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


def _endpoint() -> SourceEndpoint:
    return SourceEndpoint(
        engine="postgresql",
        host="db.example",
        port=5432,
        username="reader",
        password="secret",
        database_name="app",
        schema_filter="public",
    )


def test_postgresql_stream_is_read_only_and_yields_chunks(monkeypatch) -> None:
    from backend.metadata.connectors.postgresql import PostgresqlConnector

    raw = _Raw()
    engine = _Engine(raw)
    monkeypatch.setattr(PostgresqlConnector, "_engine", lambda self, endpoint: engine)
    monkeypatch.setattr("time.monotonic", lambda: 10.0)
    streamed = PostgresqlConnector().stream_statement(
        _endpoint(),
        _Raw.AUTHOR,
        chunk_rows=2,
        deadline=12.5,
    )
    try:
        assert [column.native_type for column in streamed.columns] == [
            "integer",
            "numeric(12,2)",
        ]
        assert [column.name for column in streamed.columns] == ["n", "qty"]
        assert list(streamed.chunks) == [
            [[1, "1.50"], [2, "2.50"]],
            [[3, "3.50"]],
        ]
    finally:
        streamed.close()

    sql = [item[0] for item in raw.statements]
    assert sql[0] == "SET TRANSACTION READ ONLY"
    timeout_at = sql.index("SET LOCAL statement_timeout = 2500")
    author_at = sql.index(_Raw.AUTHOR)
    assert timeout_at < author_at
    assert [item[1] for item in raw.statements if item[1] is not None] == [
        (23, -1),
        (1700, 786434),
    ]
    named = [cursor for cursor in raw.cursors if cursor.name]
    assert len(named) == 1
    assert named[0].itersize == 2
    assert raw.fetches == [2, 2, 2]
    assert engine.disposed is True


class _OracleType:
    def __init__(self, name: str) -> None:
        self.name = name


class _OracleCursor:
    def __init__(self, raw: "_OracleRaw") -> None:
        self.raw = raw
        self.arraysize = 0
        self.prefetchrows = 0
        self._rows: list[tuple[object, ...]] = []

    def execute(self, sql: str, params: object = None) -> None:
        del params
        self.raw.statements.append(sql)
        self.raw.arrays_at_execute.append((self.arraysize, self.prefetchrows))
        if sql == _OracleRaw.AUTHOR:
            self._rows = list(_OracleRaw.ROWS)

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self.raw.fetches.append(size)
        chunk = self._rows[:size]
        self._rows = self._rows[size:]
        return chunk

    def close(self) -> None:
        return None

    @property
    def description(self) -> list[tuple[object, ...]]:
        return [("qty", _OracleType("DB_TYPE_NUMBER"), None, None, 12, 2, True)]


class _OracleRaw:
    AUTHOR = "SELECT CAST(1 AS NUMBER(12,2)) AS qty FROM dual CONNECT BY LEVEL <= 3"
    ROWS = ((1,), (2,), (3,))

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.fetches: list[int] = []
        self.arrays_at_execute: list[tuple[int, int]] = []
        self.call_timeouts: list[int] = []
        self._call_timeout = 0

    @property
    def call_timeout(self) -> int:
        return self._call_timeout

    @call_timeout.setter
    def call_timeout(self, value: int) -> None:
        self._call_timeout = value
        self.call_timeouts.append(value)

    def cursor(self) -> _OracleCursor:
        return _OracleCursor(self)


def test_oracle_stream_is_read_only_and_prefetches(monkeypatch) -> None:
    from backend.metadata.connectors.oracle import OracleConnector

    raw = _OracleRaw()
    engine = _Engine(raw)  # type: ignore[arg-type]
    monkeypatch.setattr(OracleConnector, "_engine", lambda self, endpoint, timeout_sec=None: engine)
    monkeypatch.setattr("time.monotonic", lambda: 10.0)
    endpoint = SourceEndpoint(
        engine="oracle",
        host="db.example",
        port=1521,
        username="reader",
        password="secret",
        database_name="app",
        schema_filter="APP",
        ssl_mode="disable",
    )
    streamed = OracleConnector().stream_statement(
        endpoint,
        _OracleRaw.AUTHOR,
        chunk_rows=2,
        deadline=12.5,
    )
    try:
        assert [(column.name, column.native_type) for column in streamed.columns] == [
            ("qty", "NUMBER(12,2)")
        ]
        assert list(streamed.chunks) == [[[1], [2]], [[3]]]
    finally:
        streamed.close()
    assert raw.statements[0] == "SET TRANSACTION READ ONLY"
    assert raw.statements[1] == _OracleRaw.AUTHOR
    assert raw.arrays_at_execute[1] == (2, 2)
    assert raw.fetches == [2, 2, 2]
    assert raw.call_timeouts[0] == 2500
    assert "ISOLATION" not in " ".join(raw.statements).upper()


class _MssqlTimeout:
    def __init__(self) -> None:
        self.value = 7
        self.history: list[int] = [7]

    @property
    def query_timeout(self) -> int:
        return self.value

    @query_timeout.setter
    def query_timeout(self, value: int) -> None:
        self.value = value
        self.history.append(value)


class _MssqlCursor:
    def __init__(self, raw: "_MssqlRaw") -> None:
        self.raw = raw
        self._rows: list[tuple[object, ...]] = []
        self._meta = False

    def execute(self, sql: str, params: object = None) -> None:
        self.raw.statements.append((sql, params))
        self._meta = "sp_describe_first_result_set" in sql
        if sql == _MssqlRaw.AUTHOR:
            self._rows = list(_MssqlRaw.ROWS)

    def fetchall(self) -> list[tuple[object, ...]]:
        if self._meta:
            return [("n", "int"), ("qty", "decimal(12,2)")]
        return []

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        self.raw.fetches.append(size)
        chunk = self._rows[:size]
        self._rows = self._rows[size:]
        return chunk

    def close(self) -> None:
        return None

    @property
    def description(self) -> list[tuple[str]]:
        return [("name",), ("system_type_name",)]


class _MssqlRaw:
    AUTHOR = (
        "SELECT TOP 3 ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS n, "
        "CAST(1 AS decimal(12,2)) AS qty FROM sys.all_columns a CROSS JOIN sys.all_columns b"
    )
    ROWS = ((1, "1.50"), (2, "2.50"), (3, "3.50"))

    def __init__(self) -> None:
        self._conn = _MssqlTimeout()
        self.statements: list[tuple[str, object]] = []
        self.fetches: list[int] = []

    def cursor(self) -> _MssqlCursor:
        return _MssqlCursor(self)


def test_mssql_stream_fetches_in_chunks_and_restores_timeout(monkeypatch) -> None:
    import backend.metadata.connectors.mssql as mssql

    assert mssql.__doc__ is not None
    assert "dbsettime" in mssql.__doc__
    raw = _MssqlRaw()
    engine = _Engine(raw)  # type: ignore[arg-type]
    monkeypatch.setattr(
        mssql.MssqlConnector, "_engine", lambda self, endpoint, timeout_sec=None: engine
    )
    monkeypatch.setattr("time.monotonic", lambda: 10.0)
    endpoint = SourceEndpoint(
        engine="mssql",
        host="db.example",
        port=1433,
        username="reader",
        password="secret",
        database_name="app",
        schema_filter="dbo",
        ssl_mode="disable",
    )
    streamed = mssql.MssqlConnector().stream_statement(
        endpoint, _MssqlRaw.AUTHOR, chunk_rows=2, deadline=12.5
    )
    try:
        assert [(column.name, column.native_type) for column in streamed.columns] == [
            ("n", "int"),
            ("qty", "decimal(12,2)"),
        ]
        assert list(streamed.chunks) == [
            [[1, "1.50"], [2, "2.50"]],
            [[3, "3.50"]],
        ]
    finally:
        streamed.close()
    described = [item for item in raw.statements if "sp_describe_first_result_set" in item[0]]
    assert described
    assert described[0][1] == (_MssqlRaw.AUTHOR,)
    assert raw.fetches == [2, 2, 2]
    assert 2 in raw._conn.history
    assert raw._conn.query_timeout == 7
    joined = " ".join(item[0] for item in raw.statements).upper()
    assert "ISOLATION" not in joined
    assert "SET TRANSACTION" not in joined
