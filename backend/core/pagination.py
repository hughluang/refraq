"""Offset Page query params and response envelope.

See docs/conventions-pagination.md and docs/adr/0029-offset-page-as-platform-list-envelope.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")
S = TypeVar("S")


@dataclass(frozen=True, slots=True)
class PageParams:
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class PageBounds:
    default_limit: int
    max_limit: int

    def clamp(self, value: int | None) -> int:
        if value is None:
            return self.default_limit
        return max(1, min(self.max_limit, int(value)))


CATALOG_OBJECT_LIST = PageBounds(default_limit=100, max_limit=500)
CATALOG_SEARCH = PageBounds(default_limit=20, max_limit=100)
JOIN_LIST = PageBounds(default_limit=50, max_limit=200)
SOURCE_LIST = PageBounds(default_limit=100, max_limit=500)
SOURCE_SEARCH = PageBounds(default_limit=50, max_limit=200)
BUSINESS_DOMAIN_LIST = PageBounds(default_limit=100, max_limit=500)
SEMANTICS_CHANGE_LIST = PageBounds(default_limit=50, max_limit=200)


class OffsetPage(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def page_params(
    bounds: PageBounds | None = None,
    *,
    default_limit: int | None = None,
    max_limit: int | None = None,
) -> Callable[..., PageParams]:
    """FastAPI dependency factory for Offset Page `limit` / `offset`.

    Pass a named ``PageBounds`` or explicit ``default_limit`` / ``max_limit``.
    """
    if bounds is not None:
        if default_limit is not None or max_limit is not None:
            raise TypeError("pass PageBounds or default_limit/max_limit, not both")
        lo, hi = bounds.default_limit, bounds.max_limit
    elif default_limit is None or max_limit is None:
        raise TypeError("page_params requires PageBounds or default_limit and max_limit")
    else:
        lo, hi = default_limit, max_limit

    def dependency(
        limit: int = Query(default=lo, ge=1, le=hi),
        offset: int = Query(default=0, ge=0),
    ) -> PageParams:
        return PageParams(limit=limit, offset=offset)

    return dependency


def apply_offset_page(
    items: list[T], *, limit: int | None, offset: int = 0
) -> tuple[list[T], int]:
    """Slice an already-filtered, already-ordered in-memory set."""
    total = len(items)
    start = max(0, offset)
    if limit is None:
        return items[start:], total
    return items[start : start + max(0, limit)], total


def apply_sql_page(stmt: S, *, limit: int | None, offset: int = 0) -> S:
    """Apply offset/limit to a SQLAlchemy select. `limit=None` is unbounded."""
    start = max(0, offset)
    if start:
        stmt = stmt.offset(start)
    if limit is not None:
        stmt = stmt.limit(max(0, limit))
    return stmt
