"""Entity Data API filter parse, Core SQL fragments, and Kernel IR lowering."""

from __future__ import annotations

import json
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from backend.core.time import format_instant
from backend.entity.attribute_type import resolve, resolve_operator
from backend.entity.data.capabilities import (
    FILTER_DEPTH_MAX,
    FILTER_IN_VALUES_MAX,
    FILTER_LEAVES_MAX,
)
from backend.entity.data.head import HeadTarget
from backend.entity.data.values import encode_inbound, reference_value_attr
from backend.entity.ddl import ident
from backend.entity.errors import EntityRequestInvalid, EntityRowInvalid
from backend.entity.records import AttributeRecord

__all__ = [
    "CompiledFilter",
    "compile_filters",
    "escape_like",
]

# Comparisons PostgreSQL marks leakproof. numeric and jsonb are not; LIKE/lower are not.
_LEAKPROOF_COMPARISON_TYPES = frozenset(
    {
        "string",
        "text",
        "dictionary",
        "user",
        "integer",
        "number",
        "boolean",
        "date",
        "timestamp",
        "time",
    }
)

_CMP_SQL = {
    "eq": "=",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}


@dataclass(frozen=True, slots=True)
class CompiledFilter:
    sql: str
    params: dict[str, Any]
    profile_json: str
    leakproof: bool
    fields: frozenset[str]


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def compile_filters(
    filters: Any,
    target: HeadTarget,
    *,
    require_leaf: bool = False,
    allowed_fields: AbstractSet[str] | None = None,
) -> CompiledFilter | None:
    if filters is None or filters == {}:
        if require_leaf:
            raise EntityRowInvalid("filters must include at least one leaf")
        return None
    if filters == []:
        if require_leaf:
            raise EntityRowInvalid("filters must include at least one leaf")
        raise EntityRowInvalid("filters must be an object when present")
    counter = _ParamCounter()
    leaves = [0]
    in_values = [0]
    fields: set[str] = set()
    sql, profile_ir, leakproof = _compile_node(
        filters,
        target,
        counter=counter,
        depth=1,
        leaves=leaves,
        in_values=in_values,
        fields=fields,
        allowed_fields=allowed_fields,
    )
    if require_leaf and leaves[0] == 0:
        raise EntityRowInvalid("filters must include at least one leaf")
    return CompiledFilter(
        sql=sql,
        params=counter.params,
        profile_json=json.dumps(profile_ir, separators=(",", ":")),
        leakproof=leakproof,
        fields=frozenset(fields),
    )


class _ParamCounter:
    def __init__(self) -> None:
        self.params: dict[str, Any] = {}
        self._n = 0

    def add(self, value: Any) -> str:
        self._n += 1
        key = f"f{self._n}"
        self.params[key] = value
        return key


def _compile_node(
    node: Any,
    target: HeadTarget,
    *,
    counter: _ParamCounter,
    depth: int,
    leaves: list[int],
    in_values: list[int],
    fields: set[str],
    allowed_fields: AbstractSet[str] | None,
) -> tuple[str, dict[str, Any], bool]:
    if depth > FILTER_DEPTH_MAX:
        raise EntityRowInvalid("filter depth exceeds limit")
    if not isinstance(node, dict):
        raise EntityRowInvalid("filter node must be an object")
    keys = set(node.keys())
    if keys == {"all"} or keys == {"any"}:
        group_key = "all" if "all" in keys else "any"
        joiner = " AND " if group_key == "all" else " OR "
        items = node[group_key]
        if not isinstance(items, list) or not items:
            raise EntityRowInvalid("all/any must be a non-empty array")
        parts: list[str] = []
        ir_items: list[dict[str, Any]] = []
        all_leakproof = True
        for item in items:
            part_sql, part_ir, part_lp = _compile_node(
                item,
                target,
                counter=counter,
                depth=depth + 1,
                leaves=leaves,
                in_values=in_values,
                fields=fields,
                allowed_fields=allowed_fields,
            )
            parts.append(part_sql)
            ir_items.append(part_ir)
            all_leakproof = all_leakproof and part_lp
        return "(" + joiner.join(parts) + ")", {group_key: ir_items}, all_leakproof
    if keys == {"not"}:
        child_sql, child_ir, child_lp = _compile_node(
            node["not"],
            target,
            counter=counter,
            depth=depth + 1,
            leaves=leaves,
            in_values=in_values,
            fields=fields,
            allowed_fields=allowed_fields,
        )
        return f"(NOT COALESCE({child_sql}, false))", {"not": child_ir}, child_lp
    if "field" in keys and "op" in keys and keys <= {"field", "op", "value"}:
        return _compile_leaf(
            node,
            target,
            counter=counter,
            leaves=leaves,
            in_values=in_values,
            fields=fields,
            allowed_fields=allowed_fields,
        )
    raise EntityRowInvalid("filter node must be a leaf or all/any/not group")


def _compile_leaf(
    node: dict[str, Any],
    target: HeadTarget,
    *,
    counter: _ParamCounter,
    leaves: list[int],
    in_values: list[int],
    fields: set[str],
    allowed_fields: AbstractSet[str] | None,
) -> tuple[str, dict[str, Any], bool]:
    leaves[0] += 1
    if leaves[0] > FILTER_LEAVES_MAX:
        raise EntityRowInvalid("filter leaf count exceeds limit")
    field = node.get("field")
    op = node.get("op")
    if not isinstance(field, str) or not field:
        raise EntityRowInvalid("filter field must be a non-empty string")
    if not isinstance(op, str) or not op:
        raise EntityRowInvalid("filter op must be a non-empty string")
    if allowed_fields is not None and (
        field == "__withheld" or (field not in allowed_fields and field != "row_id")
    ):
        raise EntityRowInvalid(f"Unknown filter field '{field}'")
    if field == "row_id":
        allowed = resolve("integer").operators
        column = ident("row_id")
        attr = None
        comp_type = "integer"
    else:
        by_name = {item.name: item for item in target.attributes}
        attr = by_name.get(field)
        if attr is None:
            raise EntityRowInvalid(f"Unknown filter field '{field}'")
        allowed = _operators(attr, target)
        column = ident(field)
        comp_type = _comparison_type(attr, target)
    if op not in allowed:
        raise EntityRowInvalid(
            f"Operator '{op}' is not allowed for field '{field}'"
        )
    fields.add(field)
    spec = resolve_operator(op)
    assert spec is not None
    leakproof = spec.always_leakproof or (
        spec.btree_leakproof and comp_type in _LEAKPROOF_COMPARISON_TYPES
    )

    if spec.arity == "none":
        if "value" in node and node["value"] is not None:
            raise EntityRowInvalid(f"{op} must not carry a value")
        sql_null = "IS NULL" if op == "is_null" else "IS NOT NULL"
        return f"{column} {sql_null}", {"field": field, "op": op}, leakproof

    if "value" not in node:
        raise EntityRowInvalid(f"Operator '{op}' requires value")
    raw = node["value"]

    if op == "between":
        return _compile_between(
            field, column, attr, raw, target, counter, leakproof
        )
    if op in ("in", "not_in"):
        return _compile_set(
            field, op, column, attr, raw, target, counter, in_values, leakproof
        )
    if op in ("contains", "not_contains", "starts_with", "ends_with"):
        return _compile_pattern(field, op, column, raw, counter, leakproof)
    if op == "ieq":
        if not isinstance(raw, str) or "\x00" in raw:
            raise EntityRowInvalid("ieq value must be a string without NUL")
        key = counter.add(raw)
        return (
            f"LOWER({column}) = LOWER(:{key})",
            {"field": field, "op": "ieq", "value": raw},
            leakproof,
        )
    if op == "json_contains":
        key = counter.add(Jsonb(raw))
        return (
            f"{column} @> :{key}",
            {"field": field, "op": "json_contains", "value": raw},
            leakproof,
        )
    if op == "has_key":
        if not isinstance(raw, str) or raw == "" or "\x00" in raw:
            raise EntityRowInvalid("has_key value must be a non-empty string")
        key = counter.add(raw)
        return (
            f"{column} ? :{key}",
            {"field": field, "op": "has_key", "value": raw},
            leakproof,
        )
    if op in ("has_any_keys", "has_all_keys"):
        return _compile_json_keys(field, op, column, raw, counter, in_values, leakproof)

    bound = _bound_value(attr, raw, target)
    if op in ("gt", "gte", "lt", "lte") and bound is None:
        raise EntityRowInvalid(f"Operator '{op}' value must not be null")
    key = counter.add(bound)
    ir_leaf = {"field": field, "op": op, "value": _ir_value(bound)}
    if op == "ne":
        return f"{column} IS DISTINCT FROM :{key}", ir_leaf, leakproof
    return f"{column} {_CMP_SQL[op]} :{key}", ir_leaf, leakproof


def _compile_between(
    field: str,
    column: str,
    attr: AttributeRecord | None,
    raw: Any,
    target: HeadTarget,
    counter: _ParamCounter,
    leakproof: bool,
) -> tuple[str, dict[str, Any], bool]:
    if not isinstance(raw, list) or len(raw) != 2:
        raise EntityRowInvalid("between value must be a 2-element array [low, high]")
    low = _bound_value(attr, raw[0], target)
    high = _bound_value(attr, raw[1], target)
    if low is None or high is None:
        raise EntityRowInvalid("between bounds must not be null")
    k_low = counter.add(low)
    k_high = counter.add(high)
    sql = f"({column} >= :{k_low} AND {column} <= :{k_high})"
    ir = {
        "all": [
            {"field": field, "op": "gte", "value": _ir_value(low)},
            {"field": field, "op": "lte", "value": _ir_value(high)},
        ]
    }
    return sql, ir, leakproof


def _compile_set(
    field: str,
    op: str,
    column: str,
    attr: AttributeRecord | None,
    raw: Any,
    target: HeadTarget,
    counter: _ParamCounter,
    in_values: list[int],
    leakproof: bool,
) -> tuple[str, dict[str, Any], bool]:
    if not isinstance(raw, list) or not raw:
        raise EntityRowInvalid(f"{op} value must be a non-empty array")
    in_values[0] += len(raw)
    if in_values[0] > FILTER_IN_VALUES_MAX:
        raise EntityRowInvalid("in value count exceeds limit")
    keys: list[str] = []
    ir_values: list[Any] = []
    for item in raw:
        bound = _bound_value(attr, item, target)
        if op == "not_in" and bound is None:
            raise EntityRowInvalid("not_in values must not be null")
        keys.append(f":{counter.add(bound)}")
        ir_values.append(_ir_value(bound))
    joined = ", ".join(keys)
    in_ir = {"field": field, "op": "in", "value": ir_values}
    if op == "in":
        return f"{column} IN ({joined})", in_ir, leakproof
    sql = f"({column} IS NULL OR {column} NOT IN ({joined}))"
    ir = {"any": [{"field": field, "op": "is_null"}, {"not": in_ir}]}
    return sql, ir, leakproof


def _compile_pattern(
    field: str,
    op: str,
    column: str,
    raw: Any,
    counter: _ParamCounter,
    leakproof: bool,
) -> tuple[str, dict[str, Any], bool]:
    if not isinstance(raw, str) or raw == "":
        raise EntityRowInvalid(f"{op} value must be a non-empty string")
    if "\x00" in raw:
        raise EntityRowInvalid(f"{op} value must not contain NUL")
    escaped = escape_like(raw)
    if op == "starts_with":
        key = counter.add(f"{escaped}%")
        return (
            f"{column} ILIKE :{key} ESCAPE '\\'",
            {"field": field, "op": "starts_with", "value": raw},
            leakproof,
        )
    if op == "ends_with":
        key = counter.add(f"%{escaped}")
        return (
            f"{column} ILIKE :{key} ESCAPE '\\'",
            {"field": field, "op": "ends_with", "value": raw},
            leakproof,
        )
    key = counter.add(f"%{escaped}%")
    if op == "contains":
        return (
            f"{column} ILIKE :{key} ESCAPE '\\'",
            {"field": field, "op": "contains", "value": raw},
            leakproof,
        )
    sql = f"({column} IS NULL OR {column} NOT ILIKE :{key} ESCAPE '\\')"
    ir = {
        "any": [
            {"field": field, "op": "is_null"},
            {"not": {"field": field, "op": "contains", "value": raw}},
        ]
    }
    return sql, ir, leakproof


def _compile_json_keys(
    field: str,
    op: str,
    column: str,
    raw: Any,
    counter: _ParamCounter,
    in_values: list[int],
    leakproof: bool,
) -> tuple[str, dict[str, Any], bool]:
    if not isinstance(raw, list) or not raw:
        raise EntityRowInvalid(f"{op} value must be a non-empty array")
    in_values[0] += len(raw)
    if in_values[0] > FILTER_IN_VALUES_MAX:
        raise EntityRowInvalid("in value count exceeds limit")
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str) or item == "" or "\x00" in item:
            raise EntityRowInvalid(f"{op} items must be non-empty strings")
        cleaned.append(item)
    key = counter.add(cleaned)
    pg_op = "?|" if op == "has_any_keys" else "?&"
    return (
        f"{column} {pg_op} CAST(:{key} AS text[])",
        {"field": field, "op": op, "value": cleaned},
        leakproof,
    )


def _comparison_type(attr: AttributeRecord, target: HeadTarget) -> str:
    if attr.type != "reference":
        return attr.type
    return str(target.head.reference_snapshots[attr.name]["type"])


def _operators(attr: AttributeRecord, target: HeadTarget) -> tuple[str, ...]:
    if attr.type != "reference":
        return resolve(attr.type).operators
    return resolve(reference_value_attr(attr, target).type).operators


def _snapshot_codes(attr: AttributeRecord, target: HeadTarget) -> frozenset[str]:
    snapshot = target.head.dictionary_snapshots.get(attr.name)
    if not isinstance(snapshot, dict):
        return frozenset()
    return frozenset(str(code) for code in (snapshot.get("codes") or []))


def _bound_value(
    attr: AttributeRecord | None,
    raw: Any,
    target: HeadTarget,
) -> Any:
    if attr is None:
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            raise EntityRequestInvalid("row_id filter value must be an integer >= 1")
        return raw
    spec = resolve(attr.type)
    if "dictionary" in spec.reads:
        return spec.encode(
            attr, raw, codes=_snapshot_codes(attr, target), as_filter=True
        )
    return encode_inbound(attr, raw, target)


def _ir_value(bound: Any) -> Any:
    if isinstance(bound, Decimal):
        return format(bound, "f")
    if isinstance(bound, datetime):
        return format_instant(bound)
    if isinstance(bound, (date, time)):
        return bound.isoformat()
    if isinstance(bound, Jsonb):
        return bound.obj
    return bound
