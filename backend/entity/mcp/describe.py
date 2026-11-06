"""Entity MCP discovery documents built from the caller's read schema."""

from __future__ import annotations

from typing import Any

from backend.admin.user_store import UserRecord
from backend.core.pagination import PageBounds
from backend.entity.access.compiler import compile_policy, subject_outcome
from backend.entity.access.facts import Person
from backend.entity.access.membership import person_of, readable_entity_ids
from backend.entity.access.plan import head_from, load_policy
from backend.entity.access.store import get_access_store
from backend.entity.data.service import schema_for
from backend.entity.errors import EntityRequestInvalid
from backend.entity.inbound import serving_inbound_references
from backend.entity.store import get_entity_store

_CODE_CAP = 50
_CODE_PAGE = PageBounds(default_limit=50, max_limit=200)


def describe_for(user: UserRecord, table_name: str) -> dict[str, Any]:
    """Un-narrowed read schema, plus references and inbound references."""
    schema = schema_for(table_name, {}, user)
    return _present(schema, user)


def dictionary_codes(
    user: UserRecord,
    table_name: str,
    attribute: str,
    *,
    query_text: str | None,
    limit: int | None,
    offset: int | None,
) -> dict[str, Any]:
    """Offset Page of one visible dictionary attribute's head-snapshot codes."""
    schema = schema_for(table_name, {}, user)
    found = next(
        (item for item in schema["attributes"] if item["name"] == attribute),
        None,
    )
    if found is None:
        raise EntityRequestInvalid(f"Attribute '{attribute}' was not found")
    if found.get("type") != "dictionary":
        raise EntityRequestInvalid(f"Attribute '{attribute}' is not a dictionary")
    codes = [_active_code(item) for item in found.get("codes") or []]
    needle = query_text.casefold() if query_text else ""
    if needle:
        codes = [item for item in codes if _matches(item, needle)]
    lim = _CODE_PAGE.clamp(limit)
    off = max(0, int(offset or 0))
    return {
        "items": codes[off : off + lim],
        "total": len(codes),
        "limit": lim,
        "offset": off,
    }


def _present(schema: dict[str, Any], user: UserRecord) -> dict[str, Any]:
    entity = dict(schema["entity"])
    entity.pop("writable", None)
    attributes = [_attribute(item) for item in schema["attributes"]]
    limits = dict(schema["limits"])
    limits.pop("row_write_max", None)
    body = dict(schema)
    body["entity"] = entity
    body["attributes"] = attributes
    body["limits"] = limits
    body["references"] = _references(attributes)
    body["inbound_references"] = _inbound(str(entity["id"]), user)
    return body


def _attribute(raw: dict[str, Any]) -> dict[str, Any]:
    attr = dict(raw)
    attr.pop("writable", None)
    attr.pop("upsert_key", None)
    if attr.get("type") != "dictionary":
        return attr
    codes = list(attr.get("codes") or [])
    attr["codes_truncated"] = len(codes) > _CODE_CAP
    attr["codes"] = [_active_code(item) for item in codes[:_CODE_CAP]]
    return attr


def _active_code(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": item["code"],
        "label": item.get("label"),
        "active": bool(item.get("writable")),
    }


def _references(attributes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for attr in attributes:
        if attr.get("type") != "reference":
            continue
        target = attr.get("target")
        if not isinstance(target, dict):
            found.append({"attribute": attr["name"], "target": None})
            continue
        found.append(
            {
                "attribute": attr["name"],
                "target": {
                    "table_name": target.get("table_name"),
                    "business_key": target.get("business_key"),
                },
            }
        )
    return found


def _inbound(entity_id: str, user: UserRecord) -> list[dict[str, str]]:
    rows = serving_inbound_references(get_entity_store(), entity_id)
    if not rows:
        return []
    person = person_of(user)
    visible = readable_entity_ids(
        tuple(row["entity_id"] for row in rows), person
    )
    shapes: dict[str, set[str] | None] = {}
    kept: list[dict[str, str]] = []
    for row in rows:
        referrer = row["entity_id"]
        if referrer not in visible:
            continue
        if referrer not in shapes:
            shapes[referrer] = _read_shape_names(referrer, person)
        names = shapes[referrer]
        if names is not None and row["attribute"] not in names:
            continue
        kept.append({"table_name": row["table_name"], "attribute": row["attribute"]})
    return kept


def _read_shape_names(entity_id: str, person: Person) -> set[str] | None:
    """Attribute names in this person's un-narrowed read shape.

    ``None`` means the serving head could not be loaded, so the caller keeps
    the attribute name of a referrer it can already read.
    """
    sources = get_entity_store().membership_sources(frozenset({entity_id}))
    pair = sources.get(entity_id)
    if pair is None or pair[1] is None:
        return None
    entity, version = pair
    head = head_from(entity, version)
    revision = get_access_store().revision(entity_id)
    policy = load_policy(head, revision, people=(person,))
    compiled = compile_policy(policy)
    outcome = subject_outcome(
        compiled, policy, person, action="read", narrow=None
    )
    return {column.attr.name for column in outcome.columns}


def _matches(item: dict[str, Any], needle: str) -> bool:
    if needle in str(item["code"]).casefold():
        return True
    label = item.get("label")
    return isinstance(label, str) and needle in label.casefold()
