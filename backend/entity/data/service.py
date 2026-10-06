"""Entity Data API orchestration (check order, batch uniqueness)."""

from __future__ import annotations

from typing import Any

from backend.entity.data.capabilities import ROW_WRITE_LIMIT, upsert_key_for
from backend.entity.data.filters import compile_filters
from backend.entity.data.head import HeadTarget, resolve_head
from backend.entity.data.paging import resolve_keyset_query, resolve_offset_query
from backend.entity.data.schema import build_schema
from backend.entity.data import sql as data_sql
from backend.entity.data.values import encode_inbound, encode_inbound_map
from backend.entity.errors import (
    EntityRequestInvalid,
    EntityRowConflict,
    EntityRowInvalid,
)
from backend.entity.reference_binding import business_key_attr

__all__ = [
    "create_many_rows",
    "create_row",
    "delete_row",
    "delete_where_rows",
    "get_row",
    "query_rows",
    "schema_for",
    "update_row",
    "update_where_rows",
    "upsert_one",
]


def schema_for(table_name: str, body: dict[str, Any]) -> dict[str, Any]:
    # Contract §10: resolve head / lifecycle before request structure.
    target = resolve_head(table_name, for_write=False)
    if body:
        raise EntityRequestInvalid("schema body must be an empty object")
    return build_schema(target)


def create_row(table_name: str, body: dict[str, Any]) -> dict[str, Any]:
    target = resolve_head(table_name, for_write=True)
    _forbid_keys(body, allowed={"values"}, verb="create")
    values_raw = _require_object(body.get("values"), "values")
    encoded = encode_inbound_map(values_raw, target, partial=False)
    with data_sql.entity_connection() as conn:
        return data_sql.insert_one(conn, target, encoded)


def create_many_rows(table_name: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    target = resolve_head(table_name, for_write=True)
    _forbid_keys(body, allowed={"items"}, verb="create-many")
    items = body.get("items")
    if not isinstance(items, list):
        raise EntityRequestInvalid("items must be an array")
    if not items or len(items) > ROW_WRITE_LIMIT:
        raise EntityRequestInvalid(
            f"items length must be between 1 and {ROW_WRITE_LIMIT}"
        )
    encoded_items: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise EntityRequestInvalid(f"items[{index}] must be an object")
        if set(item.keys()) != {"values"}:
            raise EntityRequestInvalid(
                f"items[{index}] must be an object with only values"
            )
        values_raw = _require_object(item.get("values"), f"items[{index}].values")
        encoded_items.append(
            encode_inbound_map(values_raw, target, partial=False)
        )
    _reject_batch_unique_dups(target, encoded_items)
    with data_sql.entity_connection() as conn:
        return [
            data_sql.insert_one(conn, target, values) for values in encoded_items
        ]


def get_row(table_name: str, body: dict[str, Any]) -> dict[str, Any]:
    target = resolve_head(table_name, for_write=False)
    column, value = _locator(body, target, verb="get")
    with data_sql.entity_connection() as conn:
        return data_sql.select_by_column(conn, target, column, value)


def update_row(table_name: str, body: dict[str, Any]) -> dict[str, Any]:
    target = resolve_head(table_name, for_write=True)
    if "filters" in body:
        raise EntityRequestInvalid("update must not include filters")
    column, value = _locator(body, target, verb="update", extra={"values"})
    values_raw = _require_object(body.get("values"), "values")
    if not values_raw:
        raise EntityRowInvalid("values must not be empty")
    _reject_business_key_write(values_raw, target)
    encoded = encode_inbound_map(values_raw, target, partial=True)
    with data_sql.entity_connection() as conn:
        return data_sql.update_by_column(conn, target, column, value, encoded)


def delete_row(table_name: str, body: dict[str, Any]) -> None:
    target = resolve_head(table_name, for_write=True)
    column, value = _locator(body, target, verb="delete")
    with data_sql.entity_connection() as conn:
        data_sql.delete_by_column(conn, target, column, value)


def query_rows(table_name: str, body: dict[str, Any]) -> dict[str, Any]:
    target = resolve_head(table_name, for_write=False)
    if "cursor" in body:
        raise EntityRequestInvalid("cursor is not supported")
    if "sort" in body or "keys" in body:
        raise EntityRequestInvalid("unknown top-level key")
    known = {
        "filters",
        "fields",
        "limit",
        "offset",
        "include_total",
        "after_row_id",
    }
    unknown = set(body.keys()) - known
    if unknown:
        raise EntityRequestInvalid(
            f"Unknown top-level key(s): {', '.join(sorted(unknown))}"
        )
    keyset = "after_row_id" in body
    if keyset and ("offset" in body or "include_total" in body):
        raise EntityRequestInvalid(
            "after_row_id cannot be combined with offset or include_total"
        )
    fields = _resolve_fields(body.get("fields"), target)
    compiled = compile_filters(body.get("filters"), target, require_leaf=False)
    if keyset:
        limit, after = resolve_keyset_query(body)
        with data_sql.entity_connection() as conn:
            items, next_after = data_sql.query_keyset(
                conn,
                target,
                fields=fields,
                compiled=compiled,
                limit=limit,
                after_row_id=after,
            )
        return {
            "items": items,
            "limit": limit,
            "next_after_row_id": next_after,
        }
    limit, offset, include_total = resolve_offset_query(body)
    with data_sql.entity_connection() as conn:
        items, total = data_sql.query_offset(
            conn,
            target,
            fields=fields,
            compiled=compiled,
            limit=limit,
            offset=offset,
            include_total=include_total,
        )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def update_where_rows(table_name: str, body: dict[str, Any]) -> dict[str, Any]:
    target = resolve_head(table_name, for_write=True)
    _forbid_keys(body, allowed={"filters", "set"}, verb="update-where")
    set_raw = _require_object(body.get("set"), "set")
    if not set_raw:
        raise EntityRowInvalid("set must not be empty")
    _reject_business_key_write(set_raw, target)
    compiled = compile_filters(body.get("filters"), target, require_leaf=True)
    assert compiled is not None
    encoded = encode_inbound_map(set_raw, target, partial=True)
    with data_sql.entity_connection() as conn:
        affected = data_sql.update_where(
            conn, target, compiled=compiled, values=encoded
        )
    return {"affected": affected}


def delete_where_rows(table_name: str, body: dict[str, Any]) -> dict[str, Any]:
    target = resolve_head(table_name, for_write=True)
    _forbid_keys(body, allowed={"filters"}, verb="delete-where")
    compiled = compile_filters(body.get("filters"), target, require_leaf=True)
    assert compiled is not None
    with data_sql.entity_connection() as conn:
        affected = data_sql.delete_where(conn, target, compiled=compiled)
    return {"affected": affected}


def upsert_one(table_name: str, body: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    target = resolve_head(table_name, for_write=True)
    _forbid_keys(body, allowed={"key", "values"}, verb="upsert")
    if "key" not in body:
        marked = business_key_attr(target.attributes)
        if marked is None:
            raise EntityRequestInvalid(
                "key is required when the entity has no business_key"
            )
        key_name = marked.name
    else:
        key_name = body.get("key")
        if not isinstance(key_name, str) or not key_name:
            raise EntityRequestInvalid("key must be a non-empty string")
    values_raw = _require_object(body.get("values"), "values")
    by_name = {attr.name: attr for attr in target.attributes}
    attr = by_name.get(key_name)
    if attr is None or not upsert_key_for(attr):
        raise EntityRowInvalid(f"Attribute '{key_name}' is not an upsert_key")
    if key_name not in values_raw or values_raw[key_name] is None:
        raise EntityRowInvalid("values must include a non-null upsert key")
    encoded = encode_inbound_map(values_raw, target, partial=False)
    key_value = encoded[key_name]
    update_values = {name: value for name, value in encoded.items() if name != key_name}
    with data_sql.entity_connection() as conn:
        return data_sql.upsert_row(
            conn,
            target,
            key_name=key_name,
            key_value=key_value,
            values=update_values,
        )


def _reject_batch_unique_dups(
    target: object, items: list[dict[str, Any]]
) -> None:
    from backend.entity.data.head import HeadTarget

    assert isinstance(target, HeadTarget)
    unique_attrs = [attr.name for attr in target.attributes if attr.unique]
    for name in unique_attrs:
        seen: dict[Any, int] = {}
        for index, item in enumerate(items):
            value = item.get(name)
            if value is None:
                continue
            if value in seen:
                raise EntityRowConflict(
                    f"Duplicate unique value for '{name}' at items "
                    f"{seen[value]} and {index}"
                )
            seen[value] = index


def _resolve_fields(raw: Any, target: object) -> list[str]:
    from backend.entity.data.head import HeadTarget

    assert isinstance(target, HeadTarget)
    allowed = {"row_id", *[attr.name for attr in target.attributes]}
    if raw is None:
        return ["row_id", *[attr.name for attr in target.attributes]]
    if not isinstance(raw, list) or not raw:
        raise EntityRequestInvalid("fields must be a non-empty array")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or item not in allowed:
            raise EntityRowInvalid(f"Unknown field '{item}'")
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _forbid_keys(
    body: dict[str, Any], *, allowed: set[str], verb: str
) -> None:
    unknown = set(body.keys()) - allowed
    if unknown:
        raise EntityRequestInvalid(
            f"Unknown top-level key(s) for {verb}: {', '.join(sorted(unknown))}"
        )


def _require_object(raw: Any, name: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise EntityRequestInvalid(f"{name} must be an object")
    return raw


def _require_row_id(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise EntityRequestInvalid("row_id must be an integer >= 1")
    return raw


def _locator(
    body: dict[str, Any],
    target: HeadTarget,
    *,
    verb: str,
    extra: set[str] | None = None,
) -> tuple[str, Any]:
    allowed = {"row_id", "business_key"}
    if extra:
        allowed |= extra
    _forbid_keys(body, allowed=allowed, verb=verb)
    has_row = "row_id" in body
    has_key = "business_key" in body
    if has_row == has_key:
        raise EntityRequestInvalid(
            "exactly one of row_id or business_key is required"
        )
    if has_row:
        return "row_id", _require_row_id(body.get("row_id"))
    marked = business_key_attr(target.attributes)
    if marked is None:
        raise EntityRequestInvalid("business_key is not declared on this entity")
    try:
        encoded = encode_inbound(marked, body.get("business_key"), target)
    except EntityRowInvalid as exc:
        raise EntityRequestInvalid(exc.message) from exc
    if encoded is None:
        raise EntityRequestInvalid("business_key must not be null")
    return marked.name, encoded


def _reject_business_key_write(values: dict[str, Any], target: HeadTarget) -> None:
    marked = business_key_attr(target.attributes)
    if marked is not None and marked.name in values:
        raise EntityRowInvalid(
            f"Attribute '{marked.name}' is the business key and cannot be changed"
        )
