"""Write nodes in current published versions that a candidate head would break."""

from __future__ import annotations

from typing import Any, Sequence

from backend.channel.store import get_channel_store

__all__ = ["incompatible_writers"]


def incompatible_writers(
    entity_id: str, attributes: Sequence[Any]
) -> list[dict[str, Any]]:
    attrs = [_attr(item) for item in attributes]
    store = get_channel_store()
    channels, _total = store.list_channels(q=None, active=None, limit=500, offset=0)
    found: list[dict[str, Any]] = []
    for channel in channels:
        versions, _count = store.list_versions(channel.id, limit=1, offset=0)
        if not versions:
            continue
        for node in versions[0].graph.get("nodes") or []:
            if node.get("type") != "write.entity":
                continue
            config = node.get("config") or {}
            if config.get("entity_id") != entity_id:
                continue
            reasons = _reasons(config, attrs)
            if not reasons:
                continue
            found.append(
                {
                    "channel_id": channel.id,
                    "channel_name": channel.name,
                    "node_id": node.get("id"),
                    "node_name": node.get("name"),
                    "on_incompatible_head": config.get("on_incompatible_head", "fail"),
                    "reasons": reasons,
                }
            )
    return found


def _attr(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    return {
        "name": item.name,
        "unique": item.unique,
        "required": item.required,
        "business_key": item.business_key,
    }


def _reasons(config: dict[str, Any], attrs: list[dict[str, Any]]) -> list[str]:
    by_name = {item["name"]: item for item in attrs}
    reasons: list[str] = []
    mapped = {
        entry.get("attribute")
        for entry in config.get("mapping") or []
        if isinstance(entry, dict)
    }
    match = config.get("match_key")
    if match is None:
        marked = next((item for item in attrs if item.get("business_key")), None)
        if marked is None:
            reasons.append("business_key_missing")
        else:
            match = marked["name"]
    if isinstance(match, str):
        attr = by_name.get(match)
        if attr is None:
            reasons.append("attribute_missing")
        elif not attr.get("unique"):
            reasons.append("match_key_not_unique")
    for name in mapped:
        if isinstance(name, str) and name not in by_name:
            reasons.append("attribute_missing")
    return list(dict.fromkeys(reasons))
