"""Shared Entity Data API capability constants (operators, limits, upsert_key)."""

from __future__ import annotations

from backend.entity.attribute_type import resolve
from backend.entity.records import AttributeRecord

__all__ = [
    "FILTER_DEPTH_MAX",
    "FILTER_IN_VALUES_MAX",
    "FILTER_LEAVES_MAX",
    "OFFSET_MAX",
    "PAGE_LIMIT_DEFAULT",
    "PAGE_LIMIT_MAX",
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

def upsert_key_for(attr: AttributeRecord) -> bool:
    return bool(attr.unique) and resolve(attr.type).allows_upsert_key
