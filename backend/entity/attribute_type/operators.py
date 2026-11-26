"""Declarative Entity Query operator specifications."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "OperatorSpec",
    "resolve_operator",
]


@dataclass(frozen=True, slots=True)
class OperatorSpec:
    btree_leakproof: bool
    always_leakproof: bool = False
    is_nullary: bool = False


_OPERATOR_SPECS: dict[str, OperatorSpec] = {
    "eq": OperatorSpec(btree_leakproof=True),
    "ne": OperatorSpec(btree_leakproof=True),
    "ieq": OperatorSpec(btree_leakproof=False),
    "gt": OperatorSpec(btree_leakproof=True),
    "gte": OperatorSpec(btree_leakproof=True),
    "lt": OperatorSpec(btree_leakproof=True),
    "lte": OperatorSpec(btree_leakproof=True),
    "between": OperatorSpec(btree_leakproof=True),
    "in": OperatorSpec(btree_leakproof=True),
    "not_in": OperatorSpec(btree_leakproof=True),
    "contains": OperatorSpec(btree_leakproof=False),
    "not_contains": OperatorSpec(btree_leakproof=False),
    "starts_with": OperatorSpec(btree_leakproof=False),
    "ends_with": OperatorSpec(btree_leakproof=False),
    "is_null": OperatorSpec(btree_leakproof=False, always_leakproof=True, is_nullary=True),
    "is_not_null": OperatorSpec(btree_leakproof=False, always_leakproof=True, is_nullary=True),
    "json_contains": OperatorSpec(btree_leakproof=False),
    "has_key": OperatorSpec(btree_leakproof=False),
    "has_any_keys": OperatorSpec(btree_leakproof=False),
    "has_all_keys": OperatorSpec(btree_leakproof=False),
}


def resolve_operator(name: str) -> OperatorSpec | None:
    return _OPERATOR_SPECS.get(name)
