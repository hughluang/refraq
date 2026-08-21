"""Portable catalog search ranking and pagination helpers.

Ranking and paging happen in Python for both adapters. Candidate narrowing
(source_id, object_type, include_absent) stays with the adapter so SQL can
push those predicates into WHERE. Do not move those filters here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypeVar

T = TypeVar("T")


def _search_rank(
    query: str,
    *,
    locator_key: str,
    name: str,
    schema_name: str | None = None,
    business_name: str | None = None,
    business_description: str | None = None,
) -> int | None:
    """Portable ranking: exact → prefix → name/locator/schema substring → business."""
    q = query.lower().strip()
    if not q:
        return None
    loc = (locator_key or "").lower()
    nm = (name or "").lower()
    schema = (schema_name or "").lower()
    bn = (business_name or "").lower()
    bd = (business_description or "").lower()
    if loc == q or nm == q:
        return 0
    if loc.startswith(q) or nm.startswith(q) or (schema and schema.startswith(q)):
        return 1
    if q in nm or q in loc or (schema and q in schema):
        return 2
    if (bn and q in bn) or (bd and q in bd):
        return 3
    return None


def _paginate(items: list[Any], *, limit: int | None, offset: int) -> list[Any]:
    start = max(0, offset)
    if limit is None:
        return items[start:]
    return items[start : start + max(0, limit)]


def rank_and_page(
    items: Iterable[T],
    *,
    rank_of: Callable[[T], int | None],
    tiebreak: Callable[[T], tuple[Any, ...]],
    limit: int,
    offset: int,
) -> tuple[list[T], int]:
    ranked: list[tuple[int, T]] = []
    for item in items:
        rank = rank_of(item)
        if rank is None:
            continue
        ranked.append((rank, item))
    ranked.sort(key=lambda t: (t[0], *tiebreak(t[1])))
    total = len(ranked)
    page = [item for _, item in _paginate(ranked, limit=limit, offset=offset)]
    return page, total
