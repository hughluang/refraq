"""Compile Catalog Sample filter DSL to dialect SQL via sqlglot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlglot import exp

from backend.metadata.errors import SampleColumnUnknown, SampleFilterInvalid
from backend.metadata.query.guards import dialect_for_engine

SampleFilterOp = Literal["eq", "neq", "contains", "is_null"]
OrderDirection = Literal["asc", "desc"]

_VALID_DIRS: frozenset[str] = frozenset({"asc", "desc"})


@dataclass(frozen=True)
class SampleFilterSpec:
    column: str | None
    op: SampleFilterOp
    value: str = ""


@dataclass(frozen=True)
class SampleOrderSpec:
    column: str
    direction: OrderDirection = "asc"


def _escape_like_literal(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _require_column(name: str, *, known: set[str]) -> None:
    if name not in known:
        raise SampleColumnUnknown(f"Unknown column: {name}")


def _predicate(
    *,
    engine: str,
    dialect: str,
    column: str,
    op: SampleFilterOp,
    value: str,
) -> exp.Expression:
    col = exp.column(column)
    if op == "is_null":
        return exp.Is(this=col, expression=exp.Null())
    if op == "eq":
        return exp.EQ(this=col, expression=exp.Literal.string(value))
    if op == "neq":
        return exp.NEQ(this=col, expression=exp.Literal.string(value))
    if op == "contains":
        pattern = f"%{_escape_like_literal(value)}%"
        col_sql = exp.column(column).sql(dialect=dialect)
        lit_sql = exp.Literal.string(pattern).sql(dialect=dialect)
        escape_sql = exp.Literal.string("\\").sql(dialect=dialect)
        like_op = (
            "ILIKE"
            if (engine or "").strip().lower() == "postgresql"
            else "LIKE"
        )
        fragment = f"{col_sql} {like_op} {lit_sql} ESCAPE {escape_sql}"
        try:
            from sqlglot import parse_one

            return parse_one(fragment, read=dialect)
        except Exception as exc:  # noqa: BLE001
            raise SampleFilterInvalid("Failed to compile contains filter") from exc
    raise SampleFilterInvalid(f"Unsupported filter op: {op}")


def compile_sample_sql(
    *,
    engine: str,
    schema_name: str,
    object_name: str,
    known_columns: set[str],
    columns: list[str] | None,
    filters: list[SampleFilterSpec],
    order_by: list[SampleOrderSpec],
    offset: int,
    limit: int,
) -> str:
    dialect = dialect_for_engine(engine)

    select_exprs: list[exp.Expression]
    if columns is None:
        select_exprs = [exp.Star()]
    else:
        if not columns:
            raise SampleFilterInvalid("columns must be non-empty when provided")
        for name in columns:
            _require_column(name, known=known_columns)
        select_exprs = [exp.column(name) for name in columns]

    table = exp.Table(
        this=exp.to_identifier(object_name),
        db=exp.to_identifier(schema_name),
    )
    statement: exp.Select = exp.select(*select_exprs).from_(table)

    predicates: list[exp.Expression] = []
    for item in filters:
        if not item.column:
            continue
        _require_column(item.column, known=known_columns)
        predicates.append(
            _predicate(
                engine=engine,
                dialect=dialect,
                column=item.column,
                op=item.op,
                value=item.value,
            )
        )
    if predicates:
        combined = predicates[0]
        for extra in predicates[1:]:
            combined = exp.And(this=combined, expression=extra)
        statement = statement.where(combined)

    for order in order_by:
        if order.direction not in _VALID_DIRS:
            raise SampleFilterInvalid(f"Invalid order direction: {order.direction}")
        _require_column(order.column, known=known_columns)
        statement = statement.order_by(
            exp.Ordered(
                this=exp.column(order.column),
                desc=order.direction == "desc",
            ),
            append=True,
        )

    statement = statement.limit(limit)
    if offset > 0:
        statement = statement.offset(offset)

    return statement.sql(dialect=dialect)
