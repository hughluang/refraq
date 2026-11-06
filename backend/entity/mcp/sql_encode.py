"""Encode PostgreSQL cells for an Entity SQL result.

``type_name`` is ``pg_type.typname`` for the cursor column OID. Arrays use the
catalog name with one leading underscore. JSON values pass through as decoded
Python objects.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from backend.core.time import format_instant

_INTEGERS = frozenset({"int2", "int4", "int8"})
_FLOATS = frozenset({"float4", "float8"})
_JSON = frozenset({"json", "jsonb"})


def encode_sql_value(value: Any, type_name: str) -> Any:
    """One cell. ``None`` stays null. Arrays encode each element."""

    if value is None:
        return None
    if type_name in _JSON:
        return value
    if isinstance(value, (list, tuple)):
        element = type_name[1:] if type_name.startswith("_") else type_name
        return [encode_sql_value(item, element) for item in value]
    if type_name.startswith("_"):
        return _text(value)
    if type_name == "bool":
        return bool(value)
    if type_name in _INTEGERS:
        return int(value)
    if type_name == "numeric":
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        return format(decimal, "f")
    if type_name in _FLOATS:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    if type_name == "timestamptz":
        return _instant(value)
    if type_name == "date":
        return _date_text(value)
    if type_name in {"timestamp", "time", "timetz"}:
        return _iso(value)
    return _text(value)


def _instant(value: Any) -> str:
    if not isinstance(value, datetime):
        return str(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    spec = "microseconds" if value.microsecond else "seconds"
    return format_instant(value, timespec=spec)


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _iso(value: Any) -> str:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", "replace")
    return str(value)
