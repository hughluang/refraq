"""Run-scoped dataset tables in the entity database.

Channel reaches these tables only through this module. The tables live in
schema ``channel_dataset``, not ``entity_data``, and are not wrapped in
row-level security.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any

from sqlalchemy import text
from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from backend.entity.data.sql import set_write_timeouts
from backend.entity.ddl import ENTITY_DATA_SCHEMA, ident, qualified_table
from backend.entity.entity_db import get_entity_engine

__all__ = [
    "CHANNEL_DATASET_SCHEMA",
    "ORD_COLUMN",
    "any_row_exists",
    "column_types",
    "copy_chunks",
    "create_table_from_query",
    "drop_relation",
    "iter_dataset_chunks",
    "list_dataset_relations",
    "normalized_type_of",
    "physical_relation",
    "postgres_type",
    "read_keyset_page",
]

CHANNEL_DATASET_SCHEMA = "channel_dataset"
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
    r"timestamp (?:with|without) time zone|"
    r"time (?:with|without) time zone)$"
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


def postgres_type(
    normalized_type: str,
    *,
    precision: int | None = None,
    scale: int | None = None,
    with_time_zone: bool = False,
) -> str:
    """PostgreSQL type for one Normalized Type, refined by precision, scale, and time zone."""
    if normalized_type == "decimal":
        return _numeric(precision, scale)
    if normalized_type == "timestamp":
        if with_time_zone:
            return "timestamp with time zone"
        return "timestamp without time zone"
    if normalized_type == "time":
        if with_time_zone:
            return "time with time zone"
        return "time without time zone"
    physical = _BASE_TYPES.get(normalized_type)
    if physical is None:
        raise ValueError(f"unknown normalized type: {normalized_type!r}")
    return physical


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
