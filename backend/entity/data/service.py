"""Entity Data API orchestration (check order, batch uniqueness)."""

from __future__ import annotations

from typing import Any

from backend.admin.user_store import UserRecord
from backend.entity.access.enforce import (
    DataAccess,
    begin_data,
    read_context,
    read_view,
    require_write_grant,
    row_visible,
    writable_names,
    write_locator_target,
)
from backend.entity.data.capabilities import ROW_WRITE_LIMIT, upsert_key_for
from backend.entity.data.filters import compile_filters
from backend.entity.data.head import HeadTarget
from backend.entity.data.paging import resolve_keyset_query, resolve_offset_query
from backend.entity.data.schema import build_schema
from backend.entity.data import sql as data_sql
from backend.entity.data.values import (
    encode_inbound,
    encode_inbound_map,
    require_business_key_value,
)
from backend.entity.errors import (
    EntityRequestInvalid,
    EntityRowConflict,
    EntityRowInvalid,
    EntityRowNotFound,
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


def schema_for(
    table_name: str, body: dict[str, Any], user: UserRecord
) -> dict[str, Any]:
    access = begin_data(table_name, user, body, action="read", for_write=False)
    try:
        unknown = set(body) - {"narrow"}
        if unknown:
            raise EntityRequestInvalid(
                f"Unknown top-level key(s): {', '.join(sorted(unknown))}"
            )
        schema = build_schema(access.target)
        _annotate_schema(schema, access)
        access.log(row_count=None, outcome_code="ok", verb="schema")
        return schema
    except Exception as exc:
        access.log(row_count=None, outcome_code=_code(exc), verb="schema")
        raise


def create_row(
    table_name: str, body: dict[str, Any], user: UserRecord
) -> dict[str, Any]:
    access = begin_data(table_name, user, body, action="write", for_write=True)
    try:
        _forbid_keys(body, allowed={"values"}, verb="create")
        values_raw = _require_object(body.get("values"), "values")
        encoded = encode_inbound_map(values_raw, access.target, partial=False)
        require_write_grant(
            access, written=set(encoded), before=[], after=[encoded]
        )
        with data_sql.entity_connection() as conn:
            row_id = data_sql.insert_row(conn, access.target, encoded)
        row = _present(access, [row_id])[0]
        access.log(row_count=1, outcome_code="ok", verb="create")
        return row
    except Exception as exc:
        access.log(row_count=None, outcome_code=_code(exc), verb="create")
        raise


def create_many_rows(
    table_name: str, body: dict[str, Any], user: UserRecord
) -> list[dict[str, Any]]:
    access = begin_data(table_name, user, body, action="write", for_write=True)
    target = access.target
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
    try:
        written = set().union(*(set(item) for item in encoded_items))
        require_write_grant(
            access, written=written, before=[], after=encoded_items
        )
        with data_sql.entity_connection() as conn:
            row_ids = [
                data_sql.insert_row(conn, target, values) for values in encoded_items
            ]
        rows = _present(access, row_ids)
        access.log(row_count=len(rows), outcome_code="ok", verb="create-many")
        return rows
    except Exception as exc:
        access.log(row_count=None, outcome_code=_code(exc), verb="create-many")
        raise


def get_row(
    table_name: str, body: dict[str, Any], user: UserRecord
) -> dict[str, Any]:
    access = begin_data(table_name, user, body, action="read", for_write=False)
    try:
        column, value = _locator(body, access.target, verb="get")
        with data_sql.entity_read_connection(read_context(access)) as conn:
            row = data_sql.select_by_column(conn, access.target, column, value)
        access.log(row_count=1, outcome_code="ok", verb="get")
        return row
    except Exception as exc:
        access.log(row_count=None, outcome_code=_code(exc), verb="get")
        raise


def update_row(
    table_name: str, body: dict[str, Any], user: UserRecord
) -> dict[str, Any]:
    access = begin_data(table_name, user, body, action="write", for_write=True)
    target = access.target
    if "filters" in body:
        raise EntityRequestInvalid("update must not include filters")
    column, value = _locator(
        body, write_locator_target(access), verb="update", extra={"values"}
    )
    values_raw = _require_object(body.get("values"), "values")
    if not values_raw:
        raise EntityRowInvalid("values must not be empty")
    _reject_business_key_write(values_raw, target)
    encoded = encode_inbound_map(values_raw, target, partial=True)
    try:
        with data_sql.entity_connection() as conn:
            pre = data_sql.select_by_column(conn, access.full, column, value, lock=True)
            if not row_visible(access, pre):
                raise EntityRowNotFound()
            post = {**pre, **encoded}
            require_write_grant(
                access, written=set(encoded), before=[pre], after=[post]
            )
            row_id = int(pre["row_id"])
            data_sql.update_ids(conn, target, [row_id], encoded)
        row = _present(access, [row_id])[0]
        access.log(row_count=1, outcome_code="ok", verb="update")
        return row
    except Exception as exc:
        access.log(row_count=None, outcome_code=_code(exc), verb="update")
        raise


def delete_row(table_name: str, body: dict[str, Any], user: UserRecord) -> None:
    access = begin_data(table_name, user, body, action="write", for_write=True)
    try:
        column, value = _locator(body, write_locator_target(access), verb="delete")
        with data_sql.entity_connection() as conn:
            pre = data_sql.select_by_column(conn, access.full, column, value, lock=True)
            if not row_visible(access, pre):
                raise EntityRowNotFound()
            require_write_grant(
                access, written=set(), before=[pre], after=[]
            )
            data_sql.delete_ids(conn, access.target, [int(pre["row_id"])])
        access.log(row_count=1, outcome_code="ok", verb="delete")
    except Exception as exc:
        access.log(row_count=None, outcome_code=_code(exc), verb="delete")
        raise


def query_rows(
    table_name: str, body: dict[str, Any], user: UserRecord
) -> dict[str, Any]:
    access = begin_data(table_name, user, body, action="read", for_write=False)
    target = access.target
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
        "narrow",
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
    try:
        ctx = read_context(access)
        if keyset:
            limit, after = resolve_keyset_query(body)
            with data_sql.entity_read_connection(ctx) as conn:
                items, next_after = data_sql.query_keyset(
                    conn,
                    target,
                    fields=fields,
                    compiled=compiled,
                    limit=limit,
                    after_row_id=after,
                )
            access.log(row_count=len(items), outcome_code="ok", verb="query")
            return {
                "items": items,
                "limit": limit,
                "next_after_row_id": next_after,
            }
        limit, offset, include_total = resolve_offset_query(body)
        with data_sql.entity_read_connection(ctx) as conn:
            items, total = data_sql.query_offset(
                conn,
                target,
                fields=fields,
                compiled=compiled,
                limit=limit,
                offset=offset,
                include_total=include_total,
            )
        access.log(row_count=len(items), outcome_code="ok", verb="query")
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except Exception as exc:
        access.log(row_count=None, outcome_code=_code(exc), verb="query")
        raise


def update_where_rows(
    table_name: str, body: dict[str, Any], user: UserRecord
) -> dict[str, Any]:
    access = begin_data(table_name, user, body, action="write", for_write=True)
    target = access.target
    try:
        _forbid_keys(body, allowed={"filters", "set"}, verb="update-where")
        set_raw = _require_object(body.get("set"), "set")
        if not set_raw:
            raise EntityRowInvalid("set must not be empty")
        _reject_business_key_write(set_raw, target)
        compiled = compile_filters(
            body.get("filters"), write_locator_target(access), require_leaf=True
        )
        assert compiled is not None
        encoded = encode_inbound_map(set_raw, target, partial=True)
        with data_sql.entity_connection() as conn:
            rows = data_sql.select_matching(conn, access.full, compiled)
            visible = [row for row in rows if row_visible(access, row)]
            posts = [{**row, **encoded} for row in visible]
            require_write_grant(
                access, written=set(encoded), before=visible, after=posts
            )
            affected = data_sql.update_ids(
                conn,
                target,
                [int(row["row_id"]) for row in visible],
                encoded,
            )
        access.log(row_count=affected, outcome_code="ok", verb="update-where")
        return {"affected": affected}
    except Exception as exc:
        access.log(row_count=None, outcome_code=_code(exc), verb="update-where")
        raise


def delete_where_rows(
    table_name: str, body: dict[str, Any], user: UserRecord
) -> dict[str, Any]:
    access = begin_data(table_name, user, body, action="write", for_write=True)
    target = access.target
    try:
        _forbid_keys(body, allowed={"filters"}, verb="delete-where")
        compiled = compile_filters(
            body.get("filters"), write_locator_target(access), require_leaf=True
        )
        assert compiled is not None
        with data_sql.entity_connection() as conn:
            rows = data_sql.select_matching(conn, access.full, compiled)
            visible = [row for row in rows if row_visible(access, row)]
            require_write_grant(
                access, written=set(), before=visible, after=[]
            )
            affected = data_sql.delete_ids(
                conn, target, [int(row["row_id"]) for row in visible]
            )
        access.log(row_count=affected, outcome_code="ok", verb="delete-where")
        return {"affected": affected}
    except Exception as exc:
        access.log(row_count=None, outcome_code=_code(exc), verb="delete-where")
        raise


def upsert_one(
    table_name: str, body: dict[str, Any], user: UserRecord
) -> tuple[dict[str, Any], bool]:
    access = begin_data(table_name, user, body, action="write", for_write=True)
    target = access.target
    try:
        row_id, created = _upsert_body(access, target, body)
        row = _present(access, [row_id])[0]
        access.log(row_count=1, outcome_code="ok", verb="upsert")
        return row, created
    except Exception as exc:
        access.log(row_count=None, outcome_code=_code(exc), verb="upsert")
        raise


def _upsert_body(
    access: DataAccess, target: HeadTarget, body: dict[str, Any]
) -> tuple[int, bool]:
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
    if (
        attr is None
        or not upsert_key_for(attr)
        or key_name not in writable_names(access)
    ):
        raise EntityRowInvalid(f"Attribute '{key_name}' is not an upsert_key")
    if key_name not in values_raw or values_raw[key_name] is None:
        raise EntityRowInvalid("values must include a non-null upsert key")
    encoded = encode_inbound_map(values_raw, target, partial=False)
    key_value = encoded[key_name]
    update_values = {name: value for name, value in encoded.items() if name != key_name}
    with data_sql.entity_connection() as conn:
        try:
            pre = data_sql.select_by_column(
                conn, access.full, key_name, key_value, lock=True
            )
        except EntityRowNotFound:
            pre = None
        if pre is not None and not row_visible(access, pre):
            raise EntityRowConflict()
        if pre is None:
            require_write_grant(
                access, written=set(encoded), before=[], after=[encoded]
            )
            return data_sql.insert_row(conn, target, encoded), True
        post = {**pre, **update_values}
        require_write_grant(
            access, written=set(update_values), before=[pre], after=[post]
        )
        row_id = int(pre["row_id"])
        if update_values:
            data_sql.update_ids(conn, target, [row_id], update_values)
        return row_id, False


def _present(access: DataAccess, row_ids: list[int]) -> list[dict[str, Any]]:
    """Written rows through the caller's read view; a row it does not show is only ``row_id``."""
    reader = read_view(access)
    if reader is None:
        return [{"row_id": row_id} for row_id in row_ids]
    with data_sql.entity_read_connection(read_context(reader)) as conn:
        found = data_sql.select_ids(conn, reader.target, row_ids)
    return [found.get(row_id, {"row_id": row_id}) for row_id in row_ids]


def _reject_batch_unique_dups(
    target: HeadTarget, items: list[dict[str, Any]]
) -> None:
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


def _resolve_fields(raw: Any, target: HeadTarget) -> list[str]:
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
        require_business_key_value(marked, body.get("business_key"))
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


def _code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) else "error"


def _annotate_schema(schema: dict[str, Any], access: DataAccess) -> None:
    clear = writable_names(access)
    by_name = {column.attr.name: column for column in access.outcome.columns}
    for attr in schema["attributes"]:
        column = by_name.get(attr["name"])
        if column is None:
            continue
        attr["attribute_id"] = column.attr.attribute_id
        attr["presentation"] = {
            "row_varying": column.row_varying,
            "levels": [
                {"key": level.key, "mode": level.mode} for level in column.levels
            ],
            "may_be_withheld": column.may_be_withheld,
        }
        attr["writable"] = attr["name"] in clear
        if not attr["writable"]:
            attr["upsert_key"] = False
    schema["withheld_field"] = access.outcome.withheld_field
    schema["access"] = {
        "policy_revision": access.revision,
        "narrowed": access.narrow is not None,
    }
