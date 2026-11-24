"""Offset and keyset paging helpers for Entity Data API query."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.entity.data.capabilities import PAGE_LIMIT_DEFAULT
from backend.entity.data.head import HeadTarget
from backend.entity.ddl import ROW_ID_COLUMN, ident
from backend.entity.errors import EntityRequestInvalid, EntityRowInvalid

__all__ = [
    "RowSort",
    "resolve_limit",
    "resolve_offset_query",
    "resolve_keyset_query",
    "resolve_sort",
]


@dataclass(frozen=True, slots=True)
class RowSort:
    field: str = ROW_ID_COLUMN
    descending: bool = False

    def order_sql(self) -> str:
        direction = "DESC" if self.descending else "ASC"
        column = f"{ident(self.field)} {direction}"
        if self.field == ROW_ID_COLUMN:
            return column
        return f"{column} NULLS LAST, {ident(ROW_ID_COLUMN)} ASC"


def resolve_sort(body: dict[str, Any], target: HeadTarget) -> RowSort:
    if "sort" not in body:
        return RowSort()
    raw = body["sort"]
    if not isinstance(raw, dict) or raw.keys() != {"field", "direction"}:
        raise EntityRequestInvalid("sort must be an object with field and direction")
    field = raw["field"]
    direction = raw["direction"]
    if not isinstance(field, str) or not field:
        raise EntityRequestInvalid("sort field must be a non-empty string")
    if direction not in ("asc", "desc"):
        raise EntityRequestInvalid("sort direction must be asc or desc")
    if field != ROW_ID_COLUMN:
        attr = next((attr for attr in target.attributes if attr.name == field), None)
        if attr is None:
            raise EntityRowInvalid(f"Unknown sort field '{field}'")
        if attr.type == "json":
            raise EntityRowInvalid(f"Sorting is not supported for field '{field}'")
    return RowSort(field, descending=direction == "desc")


def resolve_limit(raw: Any, *, maximum: int) -> int:
    if raw is None:
        return PAGE_LIMIT_DEFAULT
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise EntityRequestInvalid("limit must be an integer >= 1")
    if raw > maximum:
        raise EntityRequestInvalid(f"limit must be <= {maximum}")
    return raw


def resolve_offset_query(
    body: dict[str, Any], *, maximum: int
) -> tuple[int, int, bool]:
    limit = resolve_limit(body.get("limit"), maximum=maximum)
    offset_raw = body.get("offset", 0)
    if offset_raw is None:
        offset_raw = 0
    if isinstance(offset_raw, bool) or not isinstance(offset_raw, int) or offset_raw < 0:
        raise EntityRequestInvalid("offset must be an integer >= 0")
    include_total = body.get("include_total", True)
    if not isinstance(include_total, bool):
        raise EntityRequestInvalid("include_total must be a boolean")
    return limit, offset_raw, include_total


def resolve_keyset_query(
    body: dict[str, Any], *, maximum: int
) -> tuple[int, int | None]:
    limit = resolve_limit(body.get("limit"), maximum=maximum)
    after = body.get("after_row_id")
    if after is not None:
        if isinstance(after, bool) or not isinstance(after, int) or after < 1:
            raise EntityRequestInvalid(
                "after_row_id must be null or an integer >= 1"
            )
    return limit, after
