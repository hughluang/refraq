"""Short Channel rows for the Tag subject page. Missing ids are omitted."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.channel.store import get_channel_store

__all__ = ["ChannelSubjectDisplay", "channel_subject_displays"]


@dataclass(frozen=True, slots=True)
class ChannelSubjectDisplay:
    id: str
    name: str
    active: bool


def channel_subject_displays(channel_ids: Sequence[str]) -> list[ChannelSubjectDisplay]:
    store = get_channel_store()
    found: list[ChannelSubjectDisplay] = []
    for channel_id in channel_ids:
        record = store.get(channel_id)
        if record is None:
            continue
        found.append(
            ChannelSubjectDisplay(id=record.id, name=record.name, active=record.active)
        )
    return found
