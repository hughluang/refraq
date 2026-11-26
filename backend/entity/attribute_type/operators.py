"""Declarative Entity Query operator specifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "OPERATOR_SPECS",
    "OperatorArity",
    "OperatorSpec",
    "OperatorValueDomain",
    "resolve_operator",
]

OperatorArity = Literal["none", "scalar", "range", "array"]
OperatorValueDomain = Literal["field", "string", "json"]


@dataclass(frozen=True, slots=True)
class OperatorSpec:
    name: str
    arity: OperatorArity
    value_domain: OperatorValueDomain
    btree_leakproof: bool
    always_leakproof: bool = False


OPERATOR_SPECS: dict[str, OperatorSpec] = {
    "eq": OperatorSpec("eq", "scalar", "field", btree_leakproof=True),
    "ne": OperatorSpec("ne", "scalar", "field", btree_leakproof=True),
    "ieq": OperatorSpec("ieq", "scalar", "string", btree_leakproof=False),
    "gt": OperatorSpec("gt", "scalar", "field", btree_leakproof=True),
    "gte": OperatorSpec("gte", "scalar", "field", btree_leakproof=True),
    "lt": OperatorSpec("lt", "scalar", "field", btree_leakproof=True),
    "lte": OperatorSpec("lte", "scalar", "field", btree_leakproof=True),
    "between": OperatorSpec("between", "range", "field", btree_leakproof=True),
    "in": OperatorSpec("in", "array", "field", btree_leakproof=True),
    "not_in": OperatorSpec("not_in", "array", "field", btree_leakproof=True),
    "contains": OperatorSpec("contains", "scalar", "string", btree_leakproof=False),
    "not_contains": OperatorSpec(
        "not_contains", "scalar", "string", btree_leakproof=False
    ),
    "starts_with": OperatorSpec(
        "starts_with", "scalar", "string", btree_leakproof=False
    ),
    "ends_with": OperatorSpec("ends_with", "scalar", "string", btree_leakproof=False),
    "is_null": OperatorSpec(
        "is_null", "none", "field", btree_leakproof=False, always_leakproof=True
    ),
    "is_not_null": OperatorSpec(
        "is_not_null", "none", "field", btree_leakproof=False, always_leakproof=True
    ),
    "json_contains": OperatorSpec(
        "json_contains", "scalar", "json", btree_leakproof=False
    ),
    "has_key": OperatorSpec("has_key", "scalar", "string", btree_leakproof=False),
    "has_any_keys": OperatorSpec(
        "has_any_keys", "array", "string", btree_leakproof=False
    ),
    "has_all_keys": OperatorSpec(
        "has_all_keys", "array", "string", btree_leakproof=False
    ),
}


def resolve_operator(name: str) -> OperatorSpec | None:
    return OPERATOR_SPECS.get(name)
