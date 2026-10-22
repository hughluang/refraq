"""EngineConnector protocol and collected structure DTOs."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SourceEndpoint:
    engine: str
    host: str
    port: int
    username: str
    password: str
    database_name: str
    schema_filter: str
    ssl_mode: str = "require"
    ssl_root_cert: str | None = None
    ssl_client_cert: str | None = None
    ssl_client_key: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class CollectedColumn:
    name: str
    ordinal: int
    data_type: str
    nullable: bool
    default_value: str | None = None
    comment: str | None = None


@dataclass
class CollectedForeignKey:
    name: str
    columns: list[str]
    ref_schema: str
    ref_table: str
    ref_columns: list[str]


@dataclass
class CollectedIndex:
    name: str
    columns: list[str]
    is_unique: bool


@dataclass
class CollectedObject:
    schema_name: str
    name: str
    object_type: str  # table | view | materialized_view | procedure | function
    columns: list[CollectedColumn] = field(default_factory=list)
    ddl: str | None = None
    comment: str | None = None
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[CollectedForeignKey] = field(default_factory=list)
    indexes: list[CollectedIndex] = field(default_factory=list)


@dataclass
class CollectedStructure:
    objects: list[CollectedObject] = field(default_factory=list)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool


@dataclass
class StatementResult:
    """Driver result of one author statement. ``truncated`` means another row existed."""

    columns: list[str]
    rows: list[list[Any]]
    rowcount: int | None
    truncated: bool


@dataclass(frozen=True)
class StreamColumn:
    """One result column. ``native_type`` is the engine's own type description."""

    name: str
    native_type: str


@dataclass
class StreamedStatement:
    """Column metadata plus a chunk iterator. Closing the iterator releases the connection."""

    columns: list[StreamColumn]
    chunks: Iterator[list[list[Any]]]

    def close(self) -> None:
        closer = getattr(self.chunks, "close", None)
        if closer is not None:
            closer()


class ChunkIterator:
    """Pull chunks until one is empty. ``close`` releases the driver even if nothing was pulled.

    A generator's ``close`` does not run ``finally`` until the generator has started.
    The connection is already open before the first fetch, so cleanup cannot live
    only in that ``finally``.
    """

    def __init__(self, pull: Callable[[], Any], cleanup: Callable[[], None]) -> None:
        self._pull = pull
        self._cleanup = cleanup
        self._closed = False

    def __iter__(self) -> ChunkIterator:
        return self

    def __next__(self) -> list[list[Any]]:
        if self._closed:
            raise StopIteration
        try:
            fetched = self._pull()
        except BaseException:
            self.close()
            raise
        if not fetched:
            self.close()
            raise StopIteration
        return [list(row) for row in fetched]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cleanup()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001 — GC must not raise
            pass


def release_stream(cursor: object, conn: object, eng: object) -> None:
    """Close a driver cursor, connection, and engine. Errors while releasing are ignored."""
    if cursor is not None:
        try:
            cursor.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    try:
        conn.close()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    try:
        eng.dispose()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def remaining_millis(deadline: float) -> int:
    """Milliseconds left until a monotonic ``deadline``. Zero remaining is a timeout."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ConnectorError("QUERY_TIMEOUT", "statement timeout")
    return max(1, int(remaining * 1000))


def remaining_seconds(deadline: float) -> int:
    """Whole seconds left until a monotonic ``deadline``. Zero remaining is a timeout."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ConnectorError("QUERY_TIMEOUT", "statement timeout")
    return max(1, int(remaining))


@runtime_checkable
class CollectProgress(Protocol):
    """Observer for collect_structure. Implementations must not live in connectors."""

    def listing_objects(self, schema: str) -> None:
        """Object-list query is about to run for this catalog scope."""

    def listed_objects(self, total: int) -> None:
        """Object-list query returned ``total`` objects to collect."""

    def fetched(self, part: str, rows: int) -> None:
        """Finished one schema-scoped fetch; ``part`` names the result set."""

    def assembled(self, total: int) -> None:
        """Finished grouping the six fetches into ``total`` collected objects."""


class EngineConnector(Protocol):
    engine: str

    def test_connection(self, endpoint: SourceEndpoint) -> None:
        """Prove the live endpoint and declared catalog scope exist, or raise."""

    def collect_structure(
        self,
        endpoint: SourceEndpoint,
        progress: CollectProgress | None = None,
    ) -> CollectedStructure:
        """Prove catalog scope, then return complete structure for it, or raise.

        A missing schema/owner is ``JOB_ENDPOINT_FAILED`` before object listing.
        A proven empty scope is a complete collect (zero objects), not a failure.
        """

    def run_readonly(
        self,
        endpoint: SourceEndpoint,
        sql: str,
        *,
        max_rows: int,
        timeout_sec: int,
    ) -> QueryResult:
        """Execute a single read-only statement with engine timeout + row cap."""

    def run_statement(
        self,
        endpoint: SourceEndpoint,
        sql: str,
        *,
        max_rows: int,
        timeout_sec: int,
    ) -> StatementResult:
        """Execute one author statement and return the driver result.

        Commits when the result fits in ``max_rows``. Rolls back when it does not.
        """

    def stream_statement(
        self,
        endpoint: SourceEndpoint,
        sql: str,
        *,
        chunk_rows: int,
        deadline: float,
    ) -> StreamedStatement:
        """Stream one statement. ``deadline`` is a monotonic timestamp.

        The driver timeout is the time remaining until ``deadline``.
        PostgreSQL and Oracle begin with ``SET TRANSACTION READ ONLY``.
        """


class ConnectorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_TIMEOUT_MARKERS = (
    "statement timeout",
    "querycanceled",
    "query canceled",
    "canceling statement",
    "cancelling statement",
    "timed out",
    "timeout expired",
    "execution timeout",
    "call timeout",
    "dpi-1067",
    "hyt00",
)


def is_query_timeout_error(exc: BaseException) -> bool:
    """True when a driver/SQLAlchemy error indicates statement/call timeout."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = f"{type(current).__name__} {current}".lower()
        if any(marker in text for marker in _TIMEOUT_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False


def query_endpoint_error(exc: BaseException) -> ConnectorError:
    """Map a driver failure to QUERY_TIMEOUT or QUERY_ENDPOINT_FAILED."""
    code = "QUERY_TIMEOUT" if is_query_timeout_error(exc) else "QUERY_ENDPOINT_FAILED"
    return ConnectorError(code, str(exc))


def fetch_query_result(result: Any, *, max_rows: int) -> QueryResult:
    """Consume a SQLAlchemy Result with max_rows cap and truncated flag."""
    columns = list(result.keys())
    rows: list[list[Any]] = []
    truncated = False
    for i, row in enumerate(result):
        if i >= max_rows:
            truncated = True
            break
        rows.append([value for value in row])
    return QueryResult(columns=columns, rows=rows, truncated=truncated)


def statement_rowcount(result: Any) -> int | None:
    count = getattr(result, "rowcount", None)
    if count is None or count < 0:
        return None
    return int(count)


def finish_statement(conn: Any, result: Any, *, max_rows: int) -> StatementResult:
    """Commit a statement that fits. Roll back when another row was waiting."""
    outcome = consume_statement(result, max_rows=max_rows)
    if outcome.truncated:
        conn.rollback()
    else:
        conn.commit()
    return outcome


def consume_statement(result: Any, *, max_rows: int) -> StatementResult:
    """Read one driver result. A non-row statement leaves ``rows`` empty."""
    rowcount = statement_rowcount(result)
    if not getattr(result, "returns_rows", False):
        return StatementResult(columns=[], rows=[], rowcount=rowcount, truncated=False)
    fetched = fetch_query_result(result, max_rows=max_rows)
    return StatementResult(
        columns=fetched.columns,
        rows=fetched.rows,
        rowcount=rowcount,
        truncated=fetched.truncated,
    )
