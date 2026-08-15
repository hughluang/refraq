"""EngineConnector protocol and collected structure DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


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
    object_type: str  # table | view | materialized_view
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


class EngineConnector(Protocol):
    engine: str

    def test_connection(self, endpoint: SourceEndpoint) -> None:
        """Raise on failure; return None on success."""

    def collect_structure(self, endpoint: SourceEndpoint) -> CollectedStructure:
        """Return complete structure for the Source scope, or raise."""

    def run_readonly(
        self,
        endpoint: SourceEndpoint,
        sql: str,
        *,
        max_rows: int,
        timeout_sec: int,
    ) -> QueryResult:
        """Execute a single read-only statement with engine timeout + row cap."""


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
