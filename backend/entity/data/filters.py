"""Entity Data API filter parse and Core SQL fragments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.entity.attribute_type import resolve
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


@dataclass(frozen=True, slots=True)
class CompiledFilter:
    sql: str
    params: dict[str, Any]


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def compile_filters(
    filters: Any,
    target: HeadTarget,
    *,
    require_leaf: bool = False,
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
    sql = _compile_node(
        filters,
        target,
        counter=counter,
        depth=1,
        leaves=leaves,
        in_values=in_values,
    )
    if require_leaf and leaves[0] == 0:
        raise EntityRowInvalid("filters must include at least one leaf")
    return CompiledFilter(sql=sql, params=counter.params)


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
) -> str:
    if depth > FILTER_DEPTH_MAX:
        raise EntityRowInvalid("filter depth exceeds limit")
    if not isinstance(node, dict):
        raise EntityRowInvalid("filter node must be an object")
    keys = set(node.keys())
    if keys == {"all"} or keys == {"any"}:
        joiner = " AND " if "all" in keys else " OR "
        items = node["all"] if "all" in keys else node["any"]
        if not isinstance(items, list) or not items:
            raise EntityRowInvalid("all/any must be a non-empty array")
        parts = [
            _compile_node(
                item,
                target,
                counter=counter,
                depth=depth + 1,
                leaves=leaves,
                in_values=in_values,
            )
            for item in items
        ]
        return "(" + joiner.join(parts) + ")"
    if "field" in keys and "op" in keys and keys <= {"field", "op", "value"}:
        return _compile_leaf(
            node, target, counter=counter, leaves=leaves, in_values=in_values
        )
    raise EntityRowInvalid("filter node must be a leaf or all/any group")


def _compile_leaf(
    node: dict[str, Any],
    target: HeadTarget,
    *,
    counter: _ParamCounter,
    leaves: list[int],
    in_values: list[int],
) -> str:
    leaves[0] += 1
    if leaves[0] > FILTER_LEAVES_MAX:
        raise EntityRowInvalid("filter leaf count exceeds limit")
    field = node.get("field")
    op = node.get("op")
    if not isinstance(field, str) or not field:
        raise EntityRowInvalid("filter field must be a non-empty string")
    if not isinstance(op, str) or not op:
        raise EntityRowInvalid("filter op must be a non-empty string")
    if field == "row_id":
        allowed = resolve("integer").operators
        column = ident("row_id")
        attr = None
    else:
        by_name = {item.name: item for item in target.attributes}
        attr = by_name.get(field)
        if attr is None:
            raise EntityRowInvalid(f"Unknown filter field '{field}'")
        allowed = _operators(attr, target)
        column = ident(field)
    if op not in allowed:
        raise EntityRowInvalid(
            f"Operator '{op}' is not allowed for field '{field}'"
        )
    if op == "is_null":
        if "value" in node and node["value"] is not None:
            raise EntityRowInvalid("is_null must not carry a value")
        return f"{column} IS NULL"
    if "value" not in node:
        raise EntityRowInvalid(f"Operator '{op}' requires value")
    raw = node["value"]
    if op == "in":
        return _compile_in(column, attr, raw, target, counter, in_values)
    if op == "contains":
        return _compile_contains(column, attr, raw, counter)
    if op == "ne":
        bound = _bound_value(attr, raw, target)
        key = counter.add(bound)
        return f"{column} IS DISTINCT FROM :{key}"
    bound = _bound_value(attr, raw, target)
    key = counter.add(bound)
    sql_op = {"eq": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
    return f"{column} {sql_op} :{key}"


def _compile_in(
    column: str,
    attr: AttributeRecord | None,
    raw: Any,
    target: HeadTarget,
    counter: _ParamCounter,
    in_values: list[int],
) -> str:
    if not isinstance(raw, list) or not raw:
        raise EntityRowInvalid("in value must be a non-empty array")
    in_values[0] += len(raw)
    if in_values[0] > FILTER_IN_VALUES_MAX:
        raise EntityRowInvalid("in value count exceeds limit")
    keys: list[str] = []
    for item in raw:
        bound = _bound_value(attr, item, target)
        keys.append(f":{counter.add(bound)}")
    return f"{column} IN ({', '.join(keys)})"


def _compile_contains(
    column: str,
    attr: AttributeRecord | None,
    raw: Any,
    counter: _ParamCounter,
) -> str:
    if not isinstance(raw, str) or raw == "":
        raise EntityRowInvalid("contains value must be a non-empty string")
    if isinstance(raw, str) and "\x00" in raw:
        raise EntityRowInvalid("contains value must not contain NUL")
    key = counter.add(f"%{escape_like(raw)}%")
    return f"{column} ILIKE :{key} ESCAPE '\\'"


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
