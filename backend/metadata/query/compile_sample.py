"""Compile Catalog Sample filter DSL to dialect SQL via sqlglot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from sqlglot import exp, parse_one

from backend.metadata.errors import SampleColumnUnknown, SampleFilterInvalid
from backend.metadata.query.guards import dialect_for_engine

SampleFilterOp = Literal[
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "starts_with",
    "ends_with",
    "is_null",
    "is_not_null",
]
SampleMatch = Literal["all", "any"]
OrderDirection = Literal["asc", "desc"]

_VALID_DIRS: frozenset[str] = frozenset({"asc", "desc"})
_VALID_MATCH: frozenset[str] = frozenset({"all", "any"})
_SAMPLE_IN_VALUES_MAX = 100
_NUMERIC_TYPES: frozenset[str] = frozenset(
    {
        "integer",
        "number",
        "decimal",
        "int",
        "bigint",
        "smallint",
        "tinyint",
        "mediumint",
        "int2",
        "int4",
        "int8",
        "numeric",
        "float",
        "double",
        "double precision",
        "real",
        "float4",
        "float8",
        "binary_float",
        "binary_double",
    }
)


@dataclass(frozen=True)
class SampleFilterSpec:
    column: str | None
    op: str
    value: str | list[str] | None = ""


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


def _literal(value: str, *, numeric: bool) -> exp.Expression:
    if not numeric:
        return exp.Literal.string(value)
    clean = value.strip()
    if not clean:
        raise SampleFilterInvalid("Numeric filter value must not be empty")
    try:
        dec = Decimal(clean)
    except InvalidOperation as exc:
        raise SampleFilterInvalid(f"Invalid numeric filter value: {value}") from exc
    if not dec.is_finite():
        raise SampleFilterInvalid(f"Invalid numeric filter value: {value}")
    return exp.Literal.number(clean)


def _require_scalar(value: str | list[str] | None, *, op: str) -> str:
    if not isinstance(value, str):
        raise SampleFilterInvalid(f"Filter operator '{op}' requires a string value")
    return value


def _require_list(value: str | list[str] | None, *, op: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SampleFilterInvalid(f"Filter operator '{op}' requires a list of strings")
    return value


def _predicate(
    *,
    engine: str,
    dialect: str,
    column: str,
    op: str,
    value: str | list[str] | None,
    numeric: bool,
) -> exp.Expression:
    normalized_op = "ne" if op == "neq" else op
    col = exp.column(column)
    if normalized_op == "is_null":
        return exp.Is(this=col, expression=exp.Null())
    if normalized_op == "is_not_null":
        return exp.Not(this=exp.Is(this=col, expression=exp.Null()))
    if normalized_op == "eq":
        return exp.EQ(this=col, expression=_literal(_require_scalar(value, op=normalized_op), numeric=numeric))
    if normalized_op == "ne":
        return exp.NEQ(this=col, expression=_literal(_require_scalar(value, op=normalized_op), numeric=numeric))
    if normalized_op == "gt":
        return exp.GT(this=col, expression=_literal(_require_scalar(value, op=normalized_op), numeric=numeric))
    if normalized_op == "gte":
        return exp.GTE(this=col, expression=_literal(_require_scalar(value, op=normalized_op), numeric=numeric))
    if normalized_op == "lt":
        return exp.LT(this=col, expression=_literal(_require_scalar(value, op=normalized_op), numeric=numeric))
    if normalized_op == "lte":
        return exp.LTE(this=col, expression=_literal(_require_scalar(value, op=normalized_op), numeric=numeric))
    if normalized_op == "between":
        items = _require_list(value, op=normalized_op)
        if len(items) != 2:
            raise SampleFilterInvalid("between filter requires exactly 2 values")
        return exp.Between(
            this=col,
            low=_literal(items[0], numeric=numeric),
            high=_literal(items[1], numeric=numeric),
        )
    if normalized_op in ("in", "not_in"):
        items = _require_list(value, op=normalized_op)
        if not items:
            raise SampleFilterInvalid(f"{normalized_op} filter requires at least one value")
        if len(items) > _SAMPLE_IN_VALUES_MAX:
            raise SampleFilterInvalid(f"{normalized_op} value count exceeds {_SAMPLE_IN_VALUES_MAX}")
        expr: exp.Expression = exp.In(
            this=col,
            expressions=[_literal(item, numeric=numeric) for item in items],
        )
        return expr if normalized_op == "in" else exp.Not(this=expr)
    if normalized_op in ("contains", "not_contains", "starts_with", "ends_with"):
        raw = _require_scalar(value, op=normalized_op)
        if raw == "":
            raise SampleFilterInvalid(f"{normalized_op} value must not be empty")
        escaped = _escape_like_literal(raw)
        if normalized_op == "starts_with":
            pattern = f"{escaped}%"
        elif normalized_op == "ends_with":
            pattern = f"%{escaped}"
        else:
            pattern = f"%{escaped}%"
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
            parsed = parse_one(fragment, read=dialect)
        except Exception as exc:  # noqa: BLE001
            raise SampleFilterInvalid(f"Failed to compile {normalized_op} filter") from exc
        return parsed if normalized_op != "not_contains" else exp.Not(this=parsed)
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
    match: SampleMatch = "all",
    column_types: Mapping[str, str] | None = None,
) -> str:
    dialect = dialect_for_engine(engine)
    if match not in _VALID_MATCH:
        raise SampleFilterInvalid(f"Invalid filter match: {match}")

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
        col_type = (column_types or {}).get(item.column, "").strip().lower()
        numeric = col_type in _NUMERIC_TYPES
        predicates.append(
            _predicate(
                engine=engine,
                dialect=dialect,
                column=item.column,
                op=item.op,
                value=item.value,
                numeric=numeric,
            )
        )
    if predicates:
        combined = predicates[0]
        joiner = exp.And if match == "all" else exp.Or
        for extra in predicates[1:]:
            combined = joiner(this=combined, expression=extra)
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

    return statement.sql(dialect=dialect, identify=engine == "mysql")
