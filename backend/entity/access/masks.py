"""Presentation modes: validation and SQL."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from backend.entity.access.facts import AttrFact

__all__ = [
    "CLEAR",
    "mask_sql",
    "validate_levels",
]

CLEAR = "clear"
_KEY_MAX = 63
_MASK_TYPES = frozenset(
    {"partial", "email", "hash", "truncate_date", "bucket", "redact", "null"}
)
_PARTIAL_TYPES = frozenset({"string", "text"})
_TEXTISH = frozenset({"string", "text", "dictionary", "user"})
_DATE_TYPES = frozenset({"date", "timestamp"})
_NUMBER_TYPES = frozenset({"integer", "decimal", "number"})
_UNITS = frozenset({"year", "month", "day"})


class ModeError(ValueError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def validate_levels(
    levels: Any, attr: AttrFact
) -> tuple[tuple[str, str | dict[str, Any]], ...]:
    if not isinstance(levels, list) or not levels:
        raise ModeError("levels must be a non-empty list")
    seen: set[str] = set()
    out: list[tuple[str, str | dict[str, Any]]] = []
    for index, item in enumerate(levels):
        if not isinstance(item, dict):
            raise ModeError(f"levels[{index}] must be an object")
        extra = set(item) - {"key", "mode"}
        if extra:
            raise ModeError(f"levels[{index}] has unknown fields")
        key = item.get("key")
        if not isinstance(key, str) or not _level_key(key):
            raise ModeError(f"levels[{index}].key is invalid")
        if key in seen:
            raise ModeError(f"level key '{key}' is duplicated")
        seen.add(key)
        mode = _validate_mode(item.get("mode"), attr, index=index, first=index == 0)
        if index == 0 and (key != CLEAR or mode != CLEAR):
            raise ModeError("the first level must be clear")
        if index > 0 and mode == CLEAR:
            raise ModeError("only the first level may be clear")
        out.append((key, mode))
    return tuple(out)


def mask_sql(
    expr: str,
    mode: str | dict[str, Any],
    attr: AttrFact,
    *,
    acl: bool,
) -> str:
    if mode == CLEAR:
        return expr
    assert isinstance(mode, dict)
    kind = str(mode["type"])
    cast = f"({expr})::text"
    if kind == "null":
        return f"CAST(NULL AS {attr.pg_type()})"
    if kind == "partial":
        keep_first = int(mode["keep_first"])
        keep_last = int(mode["keep_last"])
        if acl:
            return f"acl.mask_partial({cast}, {keep_first}, {keep_last})"
        return (
            f"CASE WHEN {expr} IS NULL THEN NULL "
            f"WHEN length({cast}) <= {keep_first} + {keep_last} "
            f"THEN repeat('*', length({cast})) "
            f"ELSE left({cast}, {keep_first}) || "
            f"repeat('*', length({cast}) - {keep_first} - {keep_last}) || "
            f"right({cast}, {keep_last}) END"
        )
    if kind == "email":
        if acl:
            return f"acl.mask_email({cast})"
        return (
            f"CASE WHEN {expr} IS NULL THEN NULL "
            f"WHEN strpos({cast}, '@') = 0 THEN left({cast}, 1) || '***' "
            f"ELSE left(split_part({cast}, '@', 1), 1) || '***@' || "
            f"substr({cast}, strpos({cast}, '@') + 1) END"
        )
    if kind == "hash":
        return f"acl.mask_hash({cast})"
    if kind == "redact":
        if acl:
            return f"acl.mask_redact({cast})"
        return f"CASE WHEN {expr} IS NULL THEN NULL ELSE '[redacted]' END"
    if kind == "truncate_date":
        unit = str(mode["unit"])
        if acl:
            return f"acl.mask_truncate_date({expr}, '{unit}')"
        return (
            f"CASE WHEN {expr} IS NULL THEN NULL "
            f"ELSE date_trunc('{unit}', {expr})::{attr.pg_type()} END"
        )
    if kind == "bucket":
        width = _width_literal(mode["width"])
        if acl:
            return f"acl.mask_bucket({expr}, {width})"
        return _bucket_inline(expr, attr, width)
    raise ModeError(f"unknown mask type '{kind}'")


def _validate_mode(
    mode: Any, attr: AttrFact, *, index: int, first: bool
) -> str | dict[str, Any]:
    if first:
        if mode != CLEAR:
            raise ModeError("the first level mode must be clear")
        return CLEAR
    if not isinstance(mode, dict):
        raise ModeError(f"levels[{index}].mode must be a mask object")
    kind = mode.get("type")
    if not isinstance(kind, str) or kind not in _MASK_TYPES:
        raise ModeError(f"levels[{index}].mode.type is not a mask")
    params = {key: value for key, value in mode.items() if key != "type"}
    _accepts(kind, attr, index)
    if kind == "partial":
        return {"type": "partial", **_partial_params(params, index)}
    if kind == "truncate_date":
        return {"type": "truncate_date", "unit": _unit_param(params, index)}
    if kind == "bucket":
        return {"type": "bucket", "width": _width_param(params, index)}
    if params:
        raise ModeError(f"levels[{index}].mode has unknown parameters")
    return {"type": kind}


def _accepts(kind: str, attr: AttrFact, index: int) -> None:
    value_type = attr.value_type()
    ok = True
    if kind == "partial" or kind == "email":
        ok = value_type in _PARTIAL_TYPES
    elif kind in {"hash", "redact"}:
        ok = value_type in _TEXTISH or (
            attr.type == "reference" and attr.reference_key_type == "string"
        )
    elif kind == "truncate_date":
        ok = value_type in _DATE_TYPES
    elif kind == "bucket":
        ok = value_type in _NUMBER_TYPES
    if not ok:
        raise ModeError(
            f"levels[{index}] mask '{kind}' is not accepted by type {attr.type}"
        )


def _partial_params(params: dict[str, Any], index: int) -> dict[str, int]:
    if set(params) != {"keep_first", "keep_last"}:
        raise ModeError(f"levels[{index}].mode partial parameters are invalid")
    return {
        "keep_first": _bounded_int(params["keep_first"], index, "keep_first"),
        "keep_last": _bounded_int(params["keep_last"], index, "keep_last"),
    }


def _unit_param(params: dict[str, Any], index: int) -> str:
    if set(params) != {"unit"} or params["unit"] not in _UNITS:
        raise ModeError(f"levels[{index}].mode unit must be year, month, or day")
    return str(params["unit"])


def _width_param(params: dict[str, Any], index: int) -> int | float:
    if set(params) != {"width"}:
        raise ModeError(f"levels[{index}].mode bucket requires width")
    width = params["width"]
    if isinstance(width, bool) or not isinstance(width, (int, float)):
        raise ModeError(f"levels[{index}].mode width must be a positive number")
    if isinstance(width, float) and not math.isfinite(width):
        raise ModeError(f"levels[{index}].mode width must be a positive number")
    if width <= 0:
        raise ModeError(f"levels[{index}].mode width must be positive")
    if isinstance(width, float) and width.is_integer():
        return int(width)
    return width


def _bounded_int(value: Any, index: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 64:
        raise ModeError(f"levels[{index}].mode {name} must be an integer from 0 to 64")
    return value


def _level_key(key: str) -> bool:
    if not key or len(key) > _KEY_MAX or not key[0].islower() or not key[0].isascii():
        return False
    return all(ch.islower() or ch.isdigit() or ch == "_" for ch in key) and all(
        ch.isascii() for ch in key
    )


def _width_literal(width: Any) -> str:
    if isinstance(width, int) and not isinstance(width, bool):
        return str(width)
    return format(Decimal(str(width)), "f")


def _bucket_inline(expr: str, attr: AttrFact, width: str) -> str:
    kind = attr.value_type()
    if kind == "integer":
        return (
            f"CASE WHEN {expr} IS NULL OR ({width}) <= 0 THEN NULL "
            f"ELSE (floor(({expr})::numeric / ({width})) * ({width}))::bigint END"
        )
    if kind == "number":
        return (
            f"CASE WHEN {expr} IS NULL OR ({width}) <= 0 "
            f"OR {expr} IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8) "
            f"THEN NULL ELSE (floor(({expr})::numeric / ({width})) * ({width}))::float8 END"
        )
    return (
        f"CASE WHEN {expr} IS NULL OR ({width}) <= 0 OR {expr} = 'NaN'::numeric "
        f"THEN NULL ELSE floor({expr} / ({width})) * ({width}) END"
    )


