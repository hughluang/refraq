"""Occurred-at bounds shared by the change-log list and historical reads."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from backend.core.time import parse_instant
from backend.entity.errors import EntityRequestInvalid

_FRACTIONAL_INSTANT = re.compile(r"\.\d+")


def _blank(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value


def _parse_bound(value: str) -> datetime:
    try:
        return parse_instant(value)
    except ValueError as exc:
        raise EntityRequestInvalid("occurred_at bound must be an Instant") from exc


def _bound(value: str | None) -> datetime | None:
    cleaned = _blank(value)
    if cleaned is None:
        return None
    return _parse_bound(cleaned)


def _occurred_to_bound(value: str | None) -> datetime | None:
    """Inclusive end. A fraction-less Instant names that whole second.

    The wire Instant drops fractional seconds, so the published value is the
    start of the second that was stored. A fraction-less upper bound includes
    the rest of that second. A fractional Instant stays that exact moment.
    """
    cleaned = _blank(value)
    if cleaned is None:
        return None
    parsed = _parse_bound(cleaned)
    if _FRACTIONAL_INSTANT.search(cleaned):
        return parsed
    return parsed + timedelta(seconds=1) - timedelta(microseconds=1)
