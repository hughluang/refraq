"""Inbound and outbound value encoding for Entity Data API."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.entity.data.head import HeadTarget
from backend.entity.dictionaries.store import get_dictionary_store
from backend.entity.errors import EntityRowInvalid
from backend.entity.records import AttributeRecord
from psycopg.types.json import Jsonb

__all__ = [
    "decode_row",
    "encode_inbound",
    "encode_inbound_map",
    "writable_dictionary_codes",
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(
    r"^([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d)(?:\.(\d{1,6}))?)?$"
)
_BIGINT_MIN = -(2**63)
_BIGINT_MAX = 2**63 - 1


def encode_inbound_map(
    values: dict[str, Any],
    target: HeadTarget,
    *,
    partial: bool,
) -> dict[str, Any]:
    if "row_id" in values:
        raise EntityRowInvalid("row_id is not an authorable attribute")
    by_name = {attr.name: attr for attr in target.attributes}
    unknown = [key for key in values if key not in by_name]
    if unknown:
        raise EntityRowInvalid(
            f"Unknown attribute(s): {', '.join(sorted(unknown))}"
        )
    if not values:
        raise EntityRowInvalid("values must not be empty")
    encoded: dict[str, Any] = {}
    for name, raw in values.items():
        encoded[name] = encode_inbound(by_name[name], raw, target)
    if not partial:
        for attr in target.attributes:
            if attr.required and attr.name not in encoded:
                raise EntityRowInvalid(
                    f"Attribute '{attr.name}' is required"
                )
            if attr.required and encoded.get(attr.name) is None:
                raise EntityRowInvalid(
                    f"Attribute '{attr.name}' is required"
                )
    return encoded


def encode_inbound(
    attr: AttributeRecord, raw: Any, target: HeadTarget
) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str) and "\x00" in raw:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' must not contain NUL"
        )
    if attr.type == "string":
        return _string(attr, raw)
    if attr.type == "text":
        return _text(attr, raw)
    if attr.type in ("integer", "reference"):
        return _integer(attr, raw)
    if attr.type == "decimal":
        return _decimal(attr, raw)
    if attr.type == "number":
        return _number(attr, raw)
    if attr.type == "boolean":
        return _boolean(attr, raw)
    if attr.type == "date":
        return _date(attr, raw)
    if attr.type == "timestamp":
        return _timestamp(attr, raw)
    if attr.type == "time":
        return _time(attr, raw)
    if attr.type == "json":
        return Jsonb(raw)
    if attr.type == "dictionary":
        return _dictionary(attr, raw, target)


def decode_row(
    columns: list[str],
    values: tuple[Any, ...],
    target: HeadTarget,
) -> dict[str, Any]:
    by_name = {attr.name: attr for attr in target.attributes}
    out: dict[str, Any] = {}
    for col, value in zip(columns, values, strict=True):
        if col == "row_id":
            out["row_id"] = int(value) if value is not None else None
            continue
        attr = by_name[col]
        out[col] = _decode_value(attr, value)
    return out


def writable_dictionary_codes(
    attr: AttributeRecord, target: HeadTarget
) -> frozenset[str]:
    snapshot = target.head.dictionary_snapshots.get(attr.name)
    if not isinstance(snapshot, dict):
        return frozenset()
    snap = {str(code) for code in (snapshot.get("codes") or [])}
    found = get_dictionary_store().get(attr.dictionary_id or "")
    if found is None:
        return frozenset()
    active = {entry.code for entry in found.entries if entry.active}
    return frozenset(snap & active)


def _decode_value(attr: AttributeRecord, value: Any) -> Any:
    if value is None:
        return None
    if attr.type == "decimal":
        return format(Decimal(str(value)), "f")
    if attr.type == "number":
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return None
        return num
    if attr.type in ("integer", "reference"):
        return int(value)
    if attr.type == "boolean":
        return bool(value)
    if attr.type == "date":
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        return str(value)[:10]
    if attr.type == "timestamp":
        if isinstance(value, datetime):
            return (
                value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            )
        return str(value)
    if attr.type == "time":
        if isinstance(value, time):
            text = value.isoformat()
            return text
        return str(value)
    if attr.type == "json":
        return value
    return str(value)


def _string(attr: AttributeRecord, raw: Any) -> str:
    if not isinstance(raw, str):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be a string")
    assert attr.max_length is not None
    if len(raw) > attr.max_length:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' exceeds max_length {attr.max_length}"
        )
    return raw


def _text(attr: AttributeRecord, raw: Any) -> str:
    if not isinstance(raw, str):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be a string")
    return raw


def _integer(attr: AttributeRecord, raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be an integer")
    if raw < _BIGINT_MIN or raw > _BIGINT_MAX:
        raise EntityRowInvalid(f"Attribute '{attr.name}' is out of BIGINT range")
    return raw


def _decimal(attr: AttributeRecord, raw: Any) -> Decimal:
    assert attr.precision is not None and attr.scale is not None
    try:
        if isinstance(raw, bool):
            raise InvalidOperation
        if isinstance(raw, str):
            value = Decimal(raw)
        elif isinstance(raw, (int, float, Decimal)):
            value = Decimal(str(raw))
        else:
            raise InvalidOperation
    except (InvalidOperation, ValueError) as exc:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' must be a decimal"
        ) from exc
    if not value.is_finite():
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be finite")
    tuple_digits = value.as_tuple()
    digits = len(tuple_digits.digits)
    exp = tuple_digits.exponent
    scale = -exp if isinstance(exp, int) and exp < 0 else 0
    precision = digits if exp >= 0 else digits
    if scale > attr.scale or precision > attr.precision:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' exceeds precision/scale"
        )
    return value.quantize(Decimal(1).scaleb(-attr.scale))


def _number(attr: AttributeRecord, raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be a number")
    num = float(raw)
    if math.isnan(num) or math.isinf(num):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be finite")
    return num


def _boolean(attr: AttributeRecord, raw: Any) -> bool:
    if not isinstance(raw, bool):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be a boolean")
    return raw


def _date(attr: AttributeRecord, raw: Any) -> date:
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' must be YYYY-MM-DD"
        )
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' must be YYYY-MM-DD"
        ) from exc


def _timestamp(attr: AttributeRecord, raw: Any) -> datetime:
    if not isinstance(raw, str):
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' must be an RFC 3339 timestamp"
        )
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' must be an RFC 3339 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' timestamp must include an offset"
        )
    return parsed.astimezone(timezone.utc)


def _time(attr: AttributeRecord, raw: Any) -> time:
    if not isinstance(raw, str) or not _TIME_RE.match(raw):
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' must be HH:MM[:SS[.ffffff]]"
        )
    try:
        return time.fromisoformat(raw)
    except ValueError as exc:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' must be HH:MM[:SS[.ffffff]]"
        ) from exc


def _dictionary(
    attr: AttributeRecord, raw: Any, target: HeadTarget
) -> str:
    if not isinstance(raw, str):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be a string code")
    allowed = writable_dictionary_codes(attr, target)
    if raw not in allowed:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' code is not writable"
        )
    return raw
