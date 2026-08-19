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


class OffsetPage(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


def page_params(
    *, default_limit: int, max_limit: int
) -> Callable[..., PageParams]:
    """FastAPI dependency factory for Offset Page `limit` / `offset`."""

    def dependency(
        limit: int = Query(default=default_limit, ge=1, le=max_limit),
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
