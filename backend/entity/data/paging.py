"""Offset and keyset paging helpers for Entity Data API query."""

from __future__ import annotations

from typing import Any

from backend.entity.data.capabilities import (
    OFFSET_MAX,
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
)
from backend.entity.errors import EntityRequestInvalid

__all__ = [
    "resolve_limit",
    "resolve_offset_query",
    "resolve_keyset_query",
]


def resolve_limit(raw: Any) -> int:
    if raw is None:
        return PAGE_LIMIT_DEFAULT
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise EntityRequestInvalid("limit must be an integer >= 1")
    if raw > PAGE_LIMIT_MAX:
        raise EntityRequestInvalid(f"limit must be <= {PAGE_LIMIT_MAX}")
    return raw


def resolve_offset_query(body: dict[str, Any]) -> tuple[int, int, bool]:
    limit = resolve_limit(body.get("limit"))
    offset_raw = body.get("offset", 0)
    if offset_raw is None:
        offset_raw = 0
    if isinstance(offset_raw, bool) or not isinstance(offset_raw, int) or offset_raw < 0:
        raise EntityRequestInvalid("offset must be an integer >= 0")
    if offset_raw > OFFSET_MAX:
        raise EntityRequestInvalid(f"offset must be <= {OFFSET_MAX}")
    include_total = body.get("include_total", True)
    if not isinstance(include_total, bool):
        raise EntityRequestInvalid("include_total must be a boolean")
    return limit, offset_raw, include_total


def resolve_keyset_query(body: dict[str, Any]) -> tuple[int, int | None]:
    limit = resolve_limit(body.get("limit"))
    after = body.get("after_row_id")
    if after is not None:
        if isinstance(after, bool) or not isinstance(after, int) or after < 1:
            raise EntityRequestInvalid(
                "after_row_id must be null or an integer >= 1"
            )
    return limit, after
