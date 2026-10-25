"""Run-scoped dataset tables in the entity database.

Channel reaches these tables only through this module. The tables live in
schema ``channel_dataset``, not ``entity_data``, and are not wrapped in
row-level security.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from backend.entity.data.sql import set_write_timeouts
from backend.entity.ddl import (
    CHANNEL_DATASET_SCHEMA,
    ENTITY_DATA_SCHEMA,
    ident,
    qualified_table,
)
from backend.entity.entity_db import get_entity_engine

__all__ = [
    "CHANNEL_DATASET_SCHEMA",
    "ORD_COLUMN",
    "any_row_exists",
    "column_types",
    "copy_chunks",
    "create_table_from_query",
    "drop_relation",
    "format_type_declaration",
    "iter_dataset_chunks",
    "list_dataset_relations",
    "normalized_type_of",
    "physical_relation",
    "postgres_type",
    "read_keyset_page",
    "temporal_target_conflict",
    "temporal_value_conflict",
]

ORD_COLUMN = "_ord"
_IDENT_MAX_BYTES = 63
_RELATION_RE = re.compile(r'^"channel_dataset"\."(ds_[A-Za-z_][A-Za-z0-9_]*)"$')
_PHYSICAL_TO_NORMALIZED = {
    "text": "string",
    "smallint": "integer",
    "integer": "integer",
    "bigint": "integer",
    "real": "number",
    "double precision": "number",
    "boolean": "boolean",
    "date": "date",
    "timestamp with time zone": "timestamp",
    "timestamp without time zone": "timestamp",
    "time with time zone": "time",
    "time without time zone": "time",
    "interval": "interval",
    "bytea": "binary",
    "json": "json",
    "jsonb": "json",
}
_VARYING_PHYSICAL_RE = re.compile(r"^(?:character varying(?:\(\d+\))?|varchar\(\d+\))$")
_NUMERIC_PHYSICAL_RE = re.compile(r"^numeric(?:\(\d+(?:,\d+)?\))?$")
_TEMPORAL_PHYSICAL_RE = re.compile(
    r"^(?:timestamp|time)\(\d+\) (?:with|without) time zone$"
)
_PHYSICAL_TYPE_RE = re.compile(
    r"^(?:text|bigint|double precision|boolean|date|interval|bytea|jsonb|"
    r"numeric(?:\(\d+(?:,\d+)?\))?|"
    r"timestamp(?:\([0-6]\))? (?:with|without) time zone|"
    r"time(?:\([0-6]\))? (?:with|without) time zone)$"
)

_BASE_TYPES = {
    "string": "text",
    "integer": "bigint",
    "number": "double precision",
    "boolean": "boolean",
    "date": "date",
    "interval": "interval",
    "binary": "bytea",
    "json": "jsonb",
    "array": "jsonb",
    "unknown": "text",
}
_NUMERIC_MAX_PRECISION = 1000


def physical_relation(dataset_id: str) -> str:
    """Qualified name ``"channel_dataset"."ds_<id>"``.

    ``dataset_id`` must be an identifier. The table name must fit PostgreSQL's
    63-byte identifier limit. Callers store this string; they do not read it
    from a dataset reference.
    """
    ident(dataset_id)
    table = f"ds_{dataset_id}"
    if len(table.encode("utf-8")) > _IDENT_MAX_BYTES:
        raise ValueError("dataset table name exceeds 63 bytes")
    return qualified_table(CHANNEL_DATASET_SCHEMA, table)


def create_table_from_query(relation: str, query: str) -> tuple[int, int]:
    """CTAS an UNLOGGED table with ``_ord`` as primary key. Returns row count and size.

    The query runs with ``search_path`` set to ``entity_data`` for that transaction.
    The table name stays schema-qualified. Capacity is not checked here.
    """
    _require_relation(relation)
    body = _one_select(query)
    ordinal = ident(ORD_COLUMN)
    # The body sits on its own line so a trailing `--` comment cannot swallow the wrapper.
    create_sql = (
        f"CREATE UNLOGGED TABLE {relation} AS "
        f"SELECT row_number() OVER () AS {ordinal}, q.* FROM (\n{body}\n) AS q"
    )
    with get_entity_engine().begin() as conn:
        conn.execute(
            text("SELECT set_config('search_path', :path, true)"),
            {"path": ENTITY_DATA_SCHEMA},
        )
        result = conn.exec_driver_sql(create_sql)
        row_count = int(result.rowcount)
        conn.exec_driver_sql(f"ALTER TABLE {relation} ADD PRIMARY KEY ({ordinal})")
        conn.exec_driver_sql(f"ANALYZE {relation}")
        size = _relation_size(conn, relation)
    return row_count, int(size)


def copy_chunks(
    relation: str,
    columns: Sequence[tuple[str, str]],
    chunks: Iterable[Sequence[Sequence[Any]]],
    on_chunk_size: Callable[[int], None] | None = None,
) -> tuple[int, int]:
    """Create an UNLOGGED table and COPY each chunk. Returns row count and size.

    ``on_chunk_size`` receives ``pg_total_relation_size`` after every chunk. If it
    raises, the transaction rolls back and the table is gone.
    """
    _require_relation(relation)
    if not columns:
        raise ValueError("dataset table needs at least one column")
    ordinal = ident(ORD_COLUMN)
    definitions = [f"{ordinal} bigint PRIMARY KEY"]
    names: list[str] = []
    for name, pg_type in columns:
        ident(name)
        if _PHYSICAL_TYPE_RE.fullmatch(pg_type) is None:
            raise ValueError(f"unsupported dataset column type: {pg_type}")
        definitions.append(f"{ident(name)} {pg_type}")
        names.append(name)
    copy_columns = ", ".join([ordinal, *[ident(name) for name in names]])
    with get_entity_engine().begin() as conn:
        conn.exec_driver_sql(
            f"CREATE UNLOGGED TABLE {relation} ({', '.join(definitions)})"
        )
        raw = conn.connection.driver_connection
        total = 0
        for chunk in chunks:
            rows = list(chunk)
            if rows:
                with raw.cursor() as cursor:
                    with cursor.copy(
                        f"COPY {relation} ({copy_columns}) FROM STDIN"
                    ) as copy:
                        for offset, row in enumerate(rows, start=total + 1):
                            copy.write_row((offset, *row))
                total += len(rows)
            if on_chunk_size is not None:
                on_chunk_size(_relation_size(conn, relation))
        conn.exec_driver_sql(f"ANALYZE {relation}")
        size = _relation_size(conn, relation)
    return total, size


def column_types(relation: str) -> list[dict[str, str]]:
    """Column name and PostgreSQL type, excluding ``_ord``, in table order."""
    _require_relation(relation)
    statement = text(
        """
        SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type
        FROM pg_attribute AS a
        WHERE a.attrelid = cast(:relation AS regclass)
          AND a.attnum > 0
          AND NOT a.attisdropped
          AND a.attname <> :ordinal
        ORDER BY a.attnum
        """
    )
    with get_entity_engine().connect() as conn:
        rows = conn.execute(
            statement, {"relation": relation, "ordinal": ORD_COLUMN}
        ).mappings()
        return [{"name": str(row["name"]), "type": str(row["type"])} for row in rows]


def read_keyset_page(relation: str, *, after_ord: int, limit: int) -> list[dict[str, Any]]:
    """Rows with ``_ord`` greater than ``after_ord``, in ``_ord`` order."""
    _require_relation(relation)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if isinstance(after_ord, bool) or not isinstance(after_ord, int):
        raise ValueError("after_ord must be an integer")
    with get_entity_engine().connect() as conn:
        return _select_keyset_page(conn, relation, after_ord=after_ord, limit=limit)


def iter_dataset_chunks(
    relation: str,
    *,
    chunk_size: int,
    timeout_ms: int | None = None,
) -> Iterator[list[tuple[int, dict[str, Any]]]]:
    """Page ``relation`` by ``_ord`` on one read-only owner connection.

    The caller resolves the table name and the page size. This function does
    not read the dataset registry. The transaction is not the write transaction.
    One page is in memory at a time. ``timeout_ms`` is the write budget, applied
    after read-only is set so a long write does not drop this connection.
    """
    _require_relation(relation)
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer")
    conn = get_entity_engine().connect()
    transaction = conn.begin()
    try:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        if timeout_ms is not None:
            set_write_timeouts(conn, max(1, int(timeout_ms)))
        after = 0
        while True:
            page: list[tuple[int, dict[str, Any]]] = []
            for item in _select_keyset_page(conn, relation, after_ord=after, limit=chunk_size):
                order = int(item.pop(ORD_COLUMN))
                page.append((order, item))
            if not page:
                break
            yield page
            after = page[-1][0]
            if len(page) < chunk_size:
                break
        transaction.commit()
    finally:
        # A closed read must not hide the caller's error, including GeneratorExit
        # after the connection is already gone.
        if transaction.is_active:
            try:
                transaction.rollback()
            except Exception:  # noqa: BLE001
                pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _select_keyset_page(
    conn: Any, relation: str, *, after_ord: int, limit: int
) -> list[dict[str, Any]]:
    """Rows with ``_ord`` greater than ``after_ord``. The caller checked ``relation``."""
    ordinal = ident(ORD_COLUMN)
    statement = text(
        f"SELECT * FROM {relation} WHERE {ordinal} > :after ORDER BY {ordinal} LIMIT :limit"
    )
    rows = conn.execute(statement, {"after": after_ord, "limit": limit}).mappings()
    return [dict(row) for row in rows]


def any_row_exists(relation: str) -> bool:
    """Whether the table has any row. Uses EXISTS, not ``count(*)``."""
    _require_relation(relation)
    statement = text(f"SELECT EXISTS (SELECT 1 FROM {relation})")
    with get_entity_engine().connect() as conn:
        return bool(conn.execute(statement).scalar_one())


def drop_relation(relation: str) -> None:
    """Drop the dataset table if it is still there."""
    _require_relation(relation)
    with get_entity_engine().begin() as conn:
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {relation}")


def list_dataset_relations() -> list[str]:
    """Qualified names of ordinary ``ds_*`` tables in ``channel_dataset``.

    The underscore is literal. Tables in other schemas, and tables in this
    schema whose names do not start with ``ds_``, are not listed.
    """
    statement = text(
        """
        SELECT c.relname
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = :schema
          AND c.relkind = 'r'
          AND c.relname LIKE :prefix ESCAPE :escape
        ORDER BY c.relname
        """
    )
    with get_entity_engine().connect() as conn:
        names = conn.execute(
            statement,
            {"schema": CHANNEL_DATASET_SCHEMA, "prefix": r"ds\_%", "escape": "\\"},
        ).scalars()
        return [qualified_table(CHANNEL_DATASET_SCHEMA, str(name)) for name in names]


def _require_relation(relation: str) -> None:
    match = _RELATION_RE.match(relation)
    if match is None:
        raise ValueError("relation is not a dataset table")
    if len(match.group(1).encode("utf-8")) > _IDENT_MAX_BYTES:
        raise ValueError("dataset table name exceeds 63 bytes")


def _one_select(query: str) -> str:
    body = query.strip()
    while body.endswith(";"):
        body = body[:-1].strip()
    if not body:
        raise ValueError("dataset query must be one SELECT")
    try:
        statements = [item for item in parse(body, read="postgres") if item is not None]
    except SqlglotError as exc:
        raise ValueError("dataset query must be one SELECT") from exc
    if len(statements) != 1:
        raise ValueError("dataset query must be one SELECT")
    statement = statements[0]
    if statement.find(exp.Insert, exp.Update, exp.Delete, exp.Merge) is not None:
        raise ValueError("dataset query must be one SELECT")
    if not isinstance(statement, (exp.Query, exp.Values)):
        raise ValueError("dataset query must be one SELECT")
    return body


def _relation_size(conn: Any, relation: str) -> int:
    value = conn.execute(
        text("SELECT pg_total_relation_size(cast(:relation AS regclass))"),
        {"relation": relation},
    ).scalar_one()
    return int(value)


_FORMAT_PRECISION = re.compile(r"\((\d+)\)")
_FORMAT_KINDS = {
    "date": "date",
    "timestamp without time zone": "local_datetime",
    "timestamp with time zone": "timestamp_with_time_zone",
    "time without time zone": "time",
    "time with time zone": "time_with_offset",
    "interval": "interval",
    "interval year to month": "interval_calendar",
    "interval day to second": "interval_fixed",
}
_PRECISION_KINDS = frozenset(
    {
        "local_datetime",
        "timestamp_with_time_zone",
        "time",
        "time_with_offset",
        "interval_fixed",
    }
)


def format_type_declaration(physical_type: str) -> tuple[str | None, int | None]:
    """Temporal kind and fractional precision of a PostgreSQL ``format_type`` string.

    The string is the type after materialization. It is not an Oracle declaration,
    so TIMESTAMP WITH LOCAL TIME ZONE is not recognized here.
    """
    text = " ".join(str(physical_type).strip().lower().split())
    match = _FORMAT_PRECISION.search(text)
    precision = int(match.group(1)) if match is not None else None
    base = " ".join(_FORMAT_PRECISION.sub("", text).split())
    kind = _FORMAT_KINDS.get(base)
    if kind is None:
        return None, None
    if kind not in _PRECISION_KINDS:
        return kind, None
    return kind, precision


def normalized_type_of(physical_type: str) -> str:
    """Fold a ``format_type`` string back to a Normalized Type.

    Precision and time zone are dropped. ``jsonb`` lands on ``json`` because
    the physical type does not say whether the value was an array. Anything
    this table does not list is ``unknown``.
    """
    mapped = _PHYSICAL_TO_NORMALIZED.get(physical_type)
    if mapped is not None:
        return mapped
    if _VARYING_PHYSICAL_RE.fullmatch(physical_type):
        return "string"
    if _NUMERIC_PHYSICAL_RE.fullmatch(physical_type):
        return "decimal"
    if _TEMPORAL_PHYSICAL_RE.fullmatch(physical_type):
        if physical_type.startswith("timestamp"):
            return "timestamp"
        return "time"
    return "unknown"


_LTZ_TARGET_LIMIT = (
    "PostgreSQL has no type that preserves TIMESTAMP WITH LOCAL TIME ZONE"
)
_POSTGRES_FRACTIONAL_LIMIT = 6


def temporal_target_conflict(
    *,
    temporal_kind: str | None,
    precision: int | None,
) -> dict[str, Any] | None:
    """Return Problem Details members when PostgreSQL cannot store the declaration."""
    if temporal_kind is None:
        return None
    declaration = {"temporal_kind": temporal_kind, "precision": precision}
    if temporal_kind == "timestamp_with_local_time_zone":
        return {
            "declaration": declaration,
            "value": None,
            "target_limit": _LTZ_TARGET_LIMIT,
        }
    if (
        precision is not None
        and isinstance(precision, int)
        and not isinstance(precision, bool)
        and precision > _POSTGRES_FRACTIONAL_LIMIT
    ):
        return {
            "declaration": declaration,
            "value": None,
            "target_limit": _POSTGRES_FRACTIONAL_LIMIT,
        }
    return None


_FRACTION_DIGITS = re.compile(r"\.(\d+)")


def temporal_value_conflict(
    *,
    temporal_kind: str | None,
    precision: int | None,
    value: Any,
) -> dict[str, Any] | None:
    """Return a conflict when a cell has more fractional digits than declared.

    Trailing zeros do not count. An unknown precision, or a value this function
    cannot read, is not a conflict.
    """
    if temporal_kind is None or value is None:
        return None
    if isinstance(precision, bool) or not isinstance(precision, int):
        return None
    text = _fraction_text(value)
    if text is None:
        return None
    digits = _fraction_digits(value, text).rstrip("0")
    if len(digits) <= precision:
        return None
    return {
        "declaration": {"temporal_kind": temporal_kind, "precision": precision},
        "value": text,
        "target_limit": precision,
    }


def _fraction_text(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None


def _fraction_digits(value: Any, text: str) -> str:
    if isinstance(value, datetime):
        return f"{value.microsecond:06d}"
    match = _FRACTION_DIGITS.search(text)
    if match is None:
        return ""
    return match.group(1)


def postgres_type(
    normalized_type: str,
    *,
    precision: int | None = None,
    scale: int | None = None,
    with_time_zone: bool = False,
    temporal_kind: str | None = None,
) -> str:
    """PostgreSQL type for one Normalized Type, refined by precision, scale, and time zone.

    Fractional precision 0–6 is a typmod. ``timestamp_with_local_time_zone`` has
    no PostgreSQL type; callers reject that declaration before SQL.
    """
    if temporal_kind == "timestamp_with_local_time_zone":
        raise ValueError("postgresql cannot preserve timestamp with local time zone")
    if normalized_type == "decimal":
        return _numeric(precision, scale)
    if normalized_type == "timestamp" or temporal_kind in {
        "local_datetime",
        "timestamp_with_time_zone",
    }:
        zoned = _zoned(temporal_kind, with_time_zone, zoned_kind="timestamp_with_time_zone")
        base = "timestamp with time zone" if zoned else "timestamp without time zone"
        return _temporal_typmod(base, precision)
    if normalized_type == "time" or temporal_kind in {"time", "time_with_offset"}:
        zoned = _zoned(temporal_kind, with_time_zone, zoned_kind="time_with_offset")
        base = "time with time zone" if zoned else "time without time zone"
        return _temporal_typmod(base, precision)
    physical = _BASE_TYPES.get(normalized_type)
    if physical is None:
        raise ValueError(f"unknown normalized type: {normalized_type!r}")
    return physical


def _zoned(temporal_kind: str | None, with_time_zone: bool, *, zoned_kind: str) -> bool:
    if temporal_kind == zoned_kind:
        return True
    if temporal_kind is None:
        return with_time_zone
    return False


def _temporal_typmod(base: str, precision: int | None) -> str:
    if precision is None:
        return base
    if isinstance(precision, bool) or not isinstance(precision, int):
        raise ValueError("temporal precision must be an integer")
    if precision < 0 or precision > _POSTGRES_FRACTIONAL_LIMIT:
        raise ValueError("temporal precision is out of range")
    name, _, rest = base.partition(" ")
    return f"{name}({precision}) {rest}"


def _numeric(precision: int | None, scale: int | None) -> str:
    if precision is None and scale is None:
        return "numeric"
    if precision is None or isinstance(precision, bool) or not isinstance(precision, int):
        raise ValueError("decimal precision is required when scale is set")
    if precision < 1 or precision > _NUMERIC_MAX_PRECISION:
        raise ValueError("decimal precision is out of range")
    if scale is None:
        scale = 0
    if isinstance(scale, bool) or not isinstance(scale, int):
        raise ValueError("decimal scale must be an integer")
    if scale < 0 or scale > precision:
        raise ValueError("decimal scale is out of range")
    return f"numeric({precision},{scale})"
