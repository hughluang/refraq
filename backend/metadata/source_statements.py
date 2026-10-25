"""Execute or stream one author statement on a registered Source.

This is not Controlled Query. The statement is sent as written. Streaming does
not decrypt until the text is exactly one statement for the Source engine.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from backend.metadata.catalog.normalized_type import canonicalize_native_type
from backend.metadata.connectors.base import ConnectorError, StatementResult
from backend.metadata.connectors.runtime import prepare
from backend.metadata.query.guards import (
    SqlNotOneStatement,
    prove_one_statement,
)
from backend.metadata.sources.access import decrypt_access_blob
from backend.metadata.sources.store import get_source_store
from backend.metadata.type_mappings.service import resolve_normalized_type

__all__ = [
    "SourceStatementRejected",
    "SourceStream",
    "SourceStreamColumn",
    "execute_source_statement",
    "source_exists",
    "stream_source_statement",
]

_STREAM_ENGINES = frozenset({"postgresql", "oracle", "mssql"})
_TRAILING_ARGS = re.compile(r"\(([^()]*)\)\s*$")
_ZONE_NAMES = frozenset({"timestamptz", "timetz", "datetimeoffset"})
_FRACTIONAL_PRECISION = re.compile(
    r"^(?:timestamp|timestamptz|datetime2|datetimeoffset|time|timetz)\s*\((\d+)(?:,\s*0)?\)",
    re.IGNORECASE,
)
_SECOND_PRECISION = re.compile(r"second\s*\((\d+)\)", re.IGNORECASE)
_OFFSET_KINDS = frozenset({"timestamp_with_time_zone", "time_with_offset"})
_LOCAL_DATETIME_NAMES = frozenset(
    {
        "timestamp",
        "timestamp without time zone",
        "datetime",
        "datetime2",
        "smalldatetime",
    }
)


class SourceStatementRejected(Exception):
    """The author text is not exactly one statement for the Source engine."""

    def __init__(self) -> None:
        super().__init__("SQL must be exactly one statement")


def source_exists(source_id: str) -> bool:
    return get_source_store().get_source(source_id) is not None


def _source_for_statement(source_id: str, sql: str):
    """Load the Source and reject text that is not one statement.

    Does not decrypt credentials or open a connection.
    """
    record = _require_source(source_id)
    engine = record.engine or ""
    try:
        prove_one_statement(sql, engine=engine)
    except SqlNotOneStatement as exc:
        raise SourceStatementRejected() from exc
    return record, engine


@dataclass(frozen=True)
class SourceStreamColumn:
    """One streamed column after Type Mapping. Precision is not part of the key."""

    name: str
    normalized_type: str
    precision: int | None = None
    scale: int | None = None
    with_time_zone: bool = False
    temporal_kind: str | None = None
    nullable: bool | None = None


@dataclass
class SourceStream:
    """Resolved columns and a chunk iterator. Close it to release the Source connection."""

    columns: list[SourceStreamColumn]
    chunks: Iterator[Sequence[Sequence[Any]]]

    def close(self) -> None:
        closer = getattr(self.chunks, "close", None)
        if closer is not None:
            closer()


def stream_source_statement(
    source_id: str,
    sql: str,
    *,
    chunk_rows: int,
    deadline: float,
) -> SourceStream:
    """Stream ``sql`` from the Source. Raises ``ConnectorError`` on failure.

    ``deadline`` is a monotonic timestamp. The connector uses the time remaining
    as the driver timeout. The caller checks that deadline between chunks.
    """
    record, engine = _source_for_statement(source_id, sql)
    if engine not in _STREAM_ENGINES:
        raise ConnectorError(
            "QUERY_ENDPOINT_FAILED",
            f"Dataset Query cannot stream engine {engine}",
        )
    access = decrypt_access_blob(record.access_ciphertext or "")
    prepared = prepare(engine=engine, access=access)
    streamed = prepared.connector.stream_statement(
        prepared.endpoint,
        sql,
        chunk_rows=chunk_rows,
        deadline=deadline,
    )
    try:
        columns = [
            _resolved_column(
                engine,
                column.name,
                column.native_type,
                nullable=_column_nullable(column),
            )
            for column in streamed.columns
        ]
    except Exception:  # noqa: BLE001 — release the open stream, then keep the original error
        streamed.close()
        raise
    return SourceStream(columns=columns, chunks=streamed.chunks)


def _resolved_column(
    engine: str,
    name: str,
    native_type: str,
    *,
    nullable: bool | None,
) -> SourceStreamColumn:
    normalized = resolve_normalized_type(engine=engine, data_type=native_type)
    precision, scale, with_time_zone = _type_facts(native_type, normalized)
    temporal_kind, fractional = _temporal_declaration(engine, native_type)
    if temporal_kind is not None:
        precision = fractional
        scale = None
        with_time_zone = temporal_kind in _OFFSET_KINDS
    return SourceStreamColumn(
        name=name,
        normalized_type=normalized,
        precision=precision,
        scale=scale,
        with_time_zone=with_time_zone,
        temporal_kind=temporal_kind,
        nullable=nullable,
    )


def _column_nullable(column: object) -> bool | None:
    """Use a nullable fact only when the driver supplied a boolean."""
    if not hasattr(column, "nullable"):
        return None
    value = getattr(column, "nullable")
    if isinstance(value, bool):
        return value
    return None


def _temporal_declaration(engine: str, native_type: str) -> tuple[str | None, int | None]:
    folded = canonicalize_native_type(native_type)
    kind = _temporal_kind(engine, folded)
    if kind is None:
        return None, None
    return kind, _fractional_precision(native_type, kind)


def _temporal_kind(engine: str, folded: str) -> str | None:
    if folded == "timestamp with local time zone":
        return "timestamp_with_local_time_zone"
    if folded in {"timestamp with time zone", "timestamptz", "datetimeoffset"}:
        return "timestamp_with_time_zone"
    if folded in {"time with time zone", "timetz"}:
        return "time_with_offset"
    if folded == "interval year to month":
        return "interval_calendar"
    if folded == "interval day to second":
        return "interval_fixed"
    if folded == "interval":
        return "interval"
    if folded in {"time", "time without time zone"}:
        return "time"
    if engine == "oracle" and folded == "date":
        return "local_datetime"
    if folded == "date":
        return "date"
    if engine == "mssql" and folded == "timestamp":
        return None
    if folded in _LOCAL_DATETIME_NAMES:
        return "local_datetime"
    return None


def _fractional_precision(native_type: str, kind: str) -> int | None:
    text = str(native_type).strip()
    if kind == "interval_fixed":
        match = _SECOND_PRECISION.search(text)
    elif kind in {
        "local_datetime",
        "timestamp_with_time_zone",
        "timestamp_with_local_time_zone",
        "time",
        "time_with_offset",
    }:
        match = _FRACTIONAL_PRECISION.search(text)
    else:
        return None
    if match is None:
        return None
    return int(match.group(1))


def _type_facts(native_type: str, normalized: str) -> tuple[int | None, int | None, bool]:
    folded = canonicalize_native_type(native_type)
    with_time_zone = "without time zone" not in folded and (
        "with time zone" in folded or folded in _ZONE_NAMES
    )
    if normalized != "decimal":
        return None, None, with_time_zone
    match = _TRAILING_ARGS.search(str(native_type).strip())
    if match is None:
        return None, None, with_time_zone
    numbers: list[int] = []
    for part in match.group(1).split(","):
        text = part.strip()
        if not text.isdigit():
            return None, None, with_time_zone
        numbers.append(int(text))
    if len(numbers) == 1:
        return numbers[0], None, with_time_zone
    if len(numbers) == 2:
        return numbers[0], numbers[1], with_time_zone
    return None, None, with_time_zone


def execute_source_statement(
    source_id: str,
    sql: str,
    *,
    timeout_sec: int,
    max_rows: int,
) -> StatementResult:
    """Run ``sql`` on the Source connection. Raises ``ConnectorError`` on failure."""
    record, engine = _source_for_statement(source_id, sql)
    access = decrypt_access_blob(record.access_ciphertext or "")
    prepared = prepare(engine=engine, access=access)
    return prepared.connector.run_statement(
        prepared.endpoint,
        sql,
        max_rows=max_rows,
        timeout_sec=timeout_sec,
    )


def _require_source(source_id: str):
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
    return record
