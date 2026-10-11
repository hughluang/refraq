"""Resolve Data Channel references through published Entity and channel reads."""

from __future__ import annotations

from backend.channel.graph import ResolvedAttribute, ResolvedEntity
from backend.channel.store import get_channel_store
from backend.entity.heads import get_entity_head

__all__ = ["ChannelReferenceResolver"]


class ChannelReferenceResolver:
    """Production resolver. A channel may not name itself as its error workflow."""

    def __init__(self, channel_id: str) -> None:
        self._channel_id = channel_id

    def entity_head(self, entity_id: str) -> ResolvedEntity | None:
        shape = get_entity_head(entity_id)
        if shape is None:
            return None
        return ResolvedEntity(
            attributes=tuple(
                ResolvedAttribute(
                    name=attr.name,
                    unique=attr.unique,
                    business_key=attr.business_key,
                    value_type=attr.value_type,
                )
                for attr in shape.attributes
            )
        )

    def channel_exists(self, channel_id: str) -> bool:
        if channel_id == self._channel_id:
            return False
        return get_channel_store().get(channel_id) is not None
