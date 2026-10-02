"""Row encode and decode shared by Attribute Type objects.

Callers pass already-resolved dictionary codes. This module does not import a store.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.entity.errors import EntityRowInvalid
from psycopg.types.json import Jsonb

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(
    r"^([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d)(?:\.(\d{1,6}))?)?$"
)
_BIGINT_MIN = -(2**63)
_BIGINT_MAX = 2**63 - 1


def encode_string(attr: Any, raw: Any, **_unused: Any) -> str:
    if not isinstance(raw, str):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be a string")
    assert attr.max_length is not None
    if len(raw) > attr.max_length:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' exceeds max_length {attr.max_length}"
        )
    return raw


def encode_text(attr: Any, raw: Any, **_unused: Any) -> str:
    if not isinstance(raw, str):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be a string")
    return raw


def encode_bigint(attr: Any, raw: Any, **_unused: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be an integer")
    if raw < _BIGINT_MIN or raw > _BIGINT_MAX:
        raise EntityRowInvalid(f"Attribute '{attr.name}' is out of BIGINT range")
    return raw


def encode_decimal(attr: Any, raw: Any, **_unused: Any) -> Decimal:
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


def encode_number(attr: Any, raw: Any, **_unused: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be a number")
    num = float(raw)
    if math.isnan(num) or math.isinf(num):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be finite")
    return num


def encode_boolean(attr: Any, raw: Any, **_unused: Any) -> bool:
    if not isinstance(raw, bool):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be a boolean")
    return raw


def encode_date(attr: Any, raw: Any, **_unused: Any) -> date:
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise EntityRowInvalid(
            f"Attribute '{attr.name}' must be YYYY-MM-DD"
        ) from exc


def encode_timestamp(attr: Any, raw: Any, **_unused: Any) -> datetime:
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


def encode_time(attr: Any, raw: Any, **_unused: Any) -> time:
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


def encode_json(attr: Any, raw: Any, **_unused: Any) -> Jsonb:
    del attr
    return Jsonb(raw)


def encode_dictionary(
    attr: Any,
    raw: Any,
    *,
    codes: Any = None,
    as_filter: bool = False,
) -> str:
    if not isinstance(raw, str):
        if as_filter:
            raise EntityRowInvalid(
                f"Attribute '{attr.name}' filter value must be a string"
            )
        raise EntityRowInvalid(f"Attribute '{attr.name}' must be a string code")
    allowed = frozenset(codes or ())
    if raw not in allowed:
        if as_filter:
            raise EntityRowInvalid(
                f"Attribute '{attr.name}' filter code is not in the head snapshot"
            )
        raise EntityRowInvalid(f"Attribute '{attr.name}' code is not writable")
    return raw


def decode_text(_attr: Any, value: Any) -> str:
    return str(value)


def decode_bigint(_attr: Any, value: Any) -> int:
    return int(value)


def decode_decimal(_attr: Any, value: Any) -> str:
    return format(Decimal(str(value)), "f")


def decode_number(_attr: Any, value: Any) -> float | None:
    num = float(value)
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def decode_boolean(_attr: Any, value: Any) -> bool:
    return bool(value)


def decode_date(_attr: Any, value: Any) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    return str(value)[:10]


def decode_timestamp(_attr: Any, value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def decode_time(_attr: Any, value: Any) -> str:
    if isinstance(value, time):
        return value.isoformat()
    return str(value)


def decode_json(_attr: Any, value: Any) -> Any:
    return value
