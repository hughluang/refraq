"""Shared Entity Data API capability constants (operators, limits, upsert_key)."""

from __future__ import annotations

from backend.entity.records import AttributeRecord

__all__ = [
    "FILTER_DEPTH_MAX",
    "FILTER_IN_VALUES_MAX",
    "FILTER_LEAVES_MAX",
    "OFFSET_MAX",
    "OPERATORS_BY_TYPE",
    "PAGE_LIMIT_DEFAULT",
    "PAGE_LIMIT_MAX",
    "ROW_ID_OPERATORS",
    "ROW_WRITE_LIMIT",
    "upsert_key_for",
]

ROW_WRITE_LIMIT = 1000
PAGE_LIMIT_DEFAULT = 50
PAGE_LIMIT_MAX = 200
OFFSET_MAX = 10_000
FILTER_LEAVES_MAX = 20
FILTER_DEPTH_MAX = 8
FILTER_IN_VALUES_MAX = 1000

_EQ_NE_NULL = ("eq", "ne", "is_null")
_EQ_NE_IN_NULL = ("eq", "ne", "in", "is_null")
_EQ_NE_IN_CONTAINS_NULL = ("eq", "ne", "in", "contains", "is_null")
_CMP = ("eq", "ne", "in", "gt", "gte", "lt", "lte", "is_null")

OPERATORS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "string": _EQ_NE_IN_CONTAINS_NULL,
    "text": _EQ_NE_IN_CONTAINS_NULL,
    "integer": _CMP,
    "number": _CMP,
    "decimal": _CMP,
    "date": _CMP,
    "timestamp": _CMP,
    "time": _CMP,
    "reference": _CMP,
    "boolean": _EQ_NE_NULL,
    "dictionary": _EQ_NE_IN_NULL,
    "json": _EQ_NE_NULL,
}

ROW_ID_OPERATORS: tuple[str, ...] = _CMP

_UPSERT_EXCLUDED = frozenset({"number", "json"})


def upsert_key_for(attr: AttributeRecord) -> bool:
    return bool(attr.unique) and attr.type not in _UPSERT_EXCLUDED
