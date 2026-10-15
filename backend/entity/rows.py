"""Head-table row read and batch write for platform writers.

Callers pass a User. A Data Channel run passes the System Identity. Access
control is the same path as the Entity Data API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from sqlalchemy import text

from backend.admin.user_store import UserRecord
from backend.entity.access.enforce import (
    begin_data,
    read_context,
    require_write_grant,
)
from backend.entity.data import sql as data_sql
from backend.entity.data.filters import compile_filters
from backend.entity.data.head import HeadTarget, resolve_head
from backend.entity.data.values import decode_row, encode_inbound, encode_inbound_map
from backend.entity.ddl import ident
from backend.entity.errors import (
    EntityNotFound,
    EntityRowInvalid,
    EntityRowWriteFailed,
)
from backend.entity.reference_binding import business_key_attr
from backend.entity.store import get_entity_store

__all__ = [
    "RowWriteResult",
    "head_target",
    "read_rows",
    "write_rows",
]

Mode = Literal["upsert", "create", "update", "delete"]


@dataclass(frozen=True)
class RowWriteResult:
    inserted: int
    updated: int
    unchanged: int
    deleted: int
    unmatched: int


def head_target(entity_id: str) -> HeadTarget | None:
    try:
        entity = get_entity_store().get_entity(entity_id)
        if entity is None:
            raise EntityNotFound()
        return resolve_head(entity.table_name, for_write=True)
    except EntityNotFound:
        return None


def read_rows(
    entity_id: str,
    *,
    filters: list[dict[str, Any]],
    user: UserRecord,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    entity = get_entity_store().get_entity(entity_id)
    if entity is None:
        raise EntityNotFound()
    access = begin_data(entity.table_name, user, {}, action="read", for_write=False)
    target = access.target
    compiled = compile_filters(_as_filter_tree(filters), target)
    fields = ["row_id", *[attr.name for attr in target.attributes]]
    ctx = read_context(access)
    with data_sql.entity_read_connection(ctx) as conn:
        items, total = data_sql.query_offset(
            conn,
            target,
            fields=fields,
            compiled=compiled,
            limit=limit + 1,
            offset=0,
            include_total=True,
        )
    if len(items) > limit:
        raise EntityRowWriteFailed(
            f"Read returned more than {limit} rows",
            reason="item_limit",
        )
    access.log(row_count=len(items), outcome_code="ok", verb="channel-read")
    return items, int(total or len(items))


def write_rows(
    entity_id: str,
    *,
    mode: Mode,
    match_key: str | None,
    rows: Sequence[Mapping[str, Any]],
    user: UserRecord,
    statement_timeout_ms: int,
    dry_run: bool = False,
) -> RowWriteResult:
    entity = get_entity_store().get_entity(entity_id)
    if entity is None:
        raise EntityNotFound()
    access = begin_data(entity.table_name, user, {}, action="write", for_write=True)
    target = access.target
    key_name = _match_key_name(target, match_key)
    if not rows:
        return RowWriteResult(0, 0, 0, 0, 0)
    prepared = _prepare(rows, target, mode, key_name)
    keys = [item[0] for item in prepared]
    if len(keys) != len(set(_freeze(key) for key in keys)):
        raise EntityRowWriteFailed(
            "Source list contains a duplicate match key",
            reason="duplicate_key",
        )
    written_names = set(prepared[0][1]) if mode != "delete" else {key_name}
    try:
        with data_sql.entity_connection(rollback=dry_run) as conn:
            conn.execute(
                text("SELECT set_config('statement_timeout', :ms, true)"),
                {"ms": str(int(statement_timeout_ms))},
            )
            existing = _lock_existing(conn, target, key_name, keys)
            result = _apply(conn, target, mode, key_name, prepared, existing, access, written_names)
        if not dry_run:
            access.log(row_count=len(rows), outcome_code="ok", verb="channel-write")
        return result
    except Exception as exc:
        if not dry_run:
            access.log(
                row_count=None,
                outcome_code=getattr(exc, "code", "error"),
                verb="channel-write",
            )
        raise


def _as_filter_tree(filters: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not filters:
        return None
    leaves = []
    for item in filters:
        leaves.append(
            {
                "field": item["attribute"],
                "op": item.get("op", "eq"),
                "value": item.get("value"),
            }
        )
    if len(leaves) == 1:
        return leaves[0]
    return {"all": leaves}


def _match_key_name(target: HeadTarget, match_key: str | None) -> str:
    if match_key is None:
        marked = business_key_attr(target.attributes)
        if marked is None:
            raise EntityRowWriteFailed(
                "Target head has no Business Key",
                reason="business_key_missing",
            )
        return marked.name
    by_name = {attr.name: attr for attr in target.attributes}
    attr = by_name.get(match_key)
    if attr is None or not attr.unique:
        raise EntityRowWriteFailed(
            "Match key does not resolve",
            reason="match_key_not_unique",
        )
    return attr.name


def _prepare(
    rows: Sequence[Mapping[str, Any]],
    target: HeadTarget,
    mode: Mode,
    key_name: str,
) -> list[tuple[Any, dict[str, Any]]]:
    prepared: list[tuple[Any, dict[str, Any]]] = []
    for index, raw in enumerate(rows):
        values = dict(raw)
        try:
            if mode == "delete":
                if key_name not in values:
                    raise EntityRowInvalid(f"Attribute '{key_name}' is required")
                encoded_key = encode_inbound(
                    next(attr for attr in target.attributes if attr.name == key_name),
                    values[key_name],
                    target,
                )
                prepared.append((encoded_key, {key_name: encoded_key}))
                continue
            encoded = encode_inbound_map(
                values,
                target,
                partial=mode == "update",
            )
            if key_name not in encoded:
                raise EntityRowInvalid(f"Attribute '{key_name}' is required")
            prepared.append((encoded[key_name], encoded))
        except EntityRowInvalid as exc:
            raise EntityRowWriteFailed(
                exc.message,
                row_index=index,
                reason="invalid",
            ) from exc
    return prepared


def _lock_existing(
    conn: Any,
    target: HeadTarget,
    key_name: str,
    keys: list[Any],
) -> dict[Any, dict[str, Any]]:
    names = ["row_id", *[attr.name for attr in target.attributes]]
    returning = ", ".join(ident(name) for name in names)
    sql = (
        f"SELECT {returning} FROM {target.qualified_table} "
        f"WHERE {ident(key_name)} = ANY(:keys) FOR UPDATE"
    )
    rows = conn.execute(text(sql), {"keys": keys}).all()
    found: dict[Any, dict[str, Any]] = {}
    for row in rows:
        decoded = decode_row(names, tuple(row), target)
        found[_freeze(decoded[key_name])] = decoded
    return found


def _apply(
    conn: Any,
    target: HeadTarget,
    mode: Mode,
    key_name: str,
    prepared: list[tuple[Any, dict[str, Any]]],
    existing: dict[Any, dict[str, Any]],
    access: Any,
    written_names: set[str],
) -> RowWriteResult:
    inserted = updated = unchanged = deleted = unmatched = 0
    bk = business_key_attr(target.attributes)
    before: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    inserts: list[dict[str, Any]] = []
    updates: list[tuple[int, dict[str, Any]]] = []
    deletes: list[int] = []
    for index, (key, values) in enumerate(prepared):
        current = existing.get(_freeze(key))
        if mode == "delete":
            if current is None:
                unmatched += 1
                continue
            deletes.append(int(current["row_id"]))
            before.append(current)
            deleted += 1
            continue
        if mode == "create":
            if current is not None:
                raise EntityRowWriteFailed(
                    "Match key already exists",
                    row_index=index,
                    attribute=key_name,
                    value=key,
                    reason="key_exists",
                )
            inserts.append(values)
            after.append(values)
            inserted += 1
            continue
        if current is None:
            if mode == "update":
                unmatched += 1
                continue
            inserts.append(values)
            after.append(values)
            inserted += 1
            continue
        if bk is not None and bk.name in values and bk.name != key_name:
            if values[bk.name] != current.get(bk.name):
                raise EntityRowWriteFailed(
                    f"Attribute '{bk.name}' is the business key and cannot be changed",
                    row_index=index,
                    attribute=bk.name,
                    value=values[bk.name],
                    reason="business_key",
                )
        changed = {
            name: value
            for name, value in values.items()
            if name != key_name and value != current.get(name)
        }
        if not changed:
            unchanged += 1
            continue
        updates.append((int(current["row_id"]), changed))
        before.append(current)
        after.append({**current, **changed})
        updated += 1
    if inserts or updates or deletes:
        require_write_grant(
            access,
            written=written_names,
            before=before,
            after=after,
        )
    for values in inserts:
        data_sql.insert_row(conn, target, values)
    for row_id, changed in updates:
        data_sql.update_ids(conn, target, [row_id], changed)
    if deletes:
        data_sql.delete_ids(conn, target, deletes)
    return RowWriteResult(inserted, updated, unchanged, deleted, unmatched)


def _freeze(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    return value
