"""Write nodes in current published versions that a candidate head would break."""

from __future__ import annotations

from typing import Any, Sequence

from backend.channel.nodes.spec import ResolvedAttribute, ResolvedEntity
from backend.channel.store import get_channel_store
from backend.channel.write_compatibility import write_reasons

__all__ = ["incompatible_writers"]


def incompatible_writers(
    entity_id: str, attributes: Sequence[Any]
) -> list[dict[str, Any]]:
    head = _resolved_head(attributes)
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
            reasons = list(
                dict.fromkeys(
                    reason.code
                    for reason in write_reasons(
                        config.get("match_key"),
                        config.get("mapping") or [],
                        head,
                    )
                )
            )
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


def _resolved_head(attributes: Sequence[Any]) -> ResolvedEntity:
    return ResolvedEntity(attributes=tuple(_attribute(item) for item in attributes))


def _attribute(item: Any) -> ResolvedAttribute:
    if isinstance(item, dict):
        return ResolvedAttribute(
            name=item["name"],
            unique=bool(item.get("unique")),
            business_key=bool(item.get("business_key")),
        )
    return ResolvedAttribute(
        name=item.name,
        unique=bool(item.unique),
        business_key=bool(item.business_key),
    )
