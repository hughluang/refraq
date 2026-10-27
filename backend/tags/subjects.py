"""One page of records that carry a Tag.

Display fields and Entity visibility come from a port composition binds.
This module does not import entity or channel.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from backend.admin.user_store import UserRecord
from backend.tags.service import get_tag
from backend.tags.store import get_tag_store

__all__ = [
    "ChannelSubjectView",
    "EntitySubjectView",
    "SubjectDisplayPort",
    "bind_subject_display_port",
    "list_tag_subjects",
]


@runtime_checkable
class EntitySubjectView(Protocol):
    id: str
    name: str
    table_name: str
    deprecated_at: datetime | None
    ever_published: bool


class ChannelSubjectView(Protocol):
    id: str
    name: str
    active: bool


class SubjectDisplayPort(Protocol):
    def entities(
        self, user: UserRecord, entity_ids: Sequence[str]
    ) -> Sequence[EntitySubjectView]: ...

    def channels(self, channel_ids: Sequence[str]) -> Sequence[ChannelSubjectView]: ...


_port: SubjectDisplayPort | None = None


def bind_subject_display_port(port: SubjectDisplayPort) -> None:
    global _port
    _port = port


def list_tag_subjects(
    *,
    tag_id: str,
    user: UserRecord,
    include_entities: bool,
    include_channels: bool,
    limit: int,
    offset: int,
) -> tuple[list[EntitySubjectView | ChannelSubjectView], int]:
    """Visible carriers, entities first, each kind by subject id."""

    get_tag(tag_id)
    pairs = get_tag_store().run(lambda view: view.assignment_subjects(tag_id))
    entity_ids = [subject_id for kind, subject_id in pairs if kind == "entity"]
    channel_ids = [subject_id for kind, subject_id in pairs if kind == "channel"]
    entities: list[EntitySubjectView] = []
    channels: list[ChannelSubjectView] = []
    if (include_entities and entity_ids) or (include_channels and channel_ids):
        port = _require_port()
        if include_entities and entity_ids:
            entities = sorted(port.entities(user, entity_ids), key=lambda row: row.id)
        if include_channels and channel_ids:
            channels = sorted(port.channels(channel_ids), key=lambda row: row.id)
    ordered: list[EntitySubjectView | ChannelSubjectView] = [*entities, *channels]
    return ordered[offset : offset + limit], len(ordered)


def _require_port() -> SubjectDisplayPort:
    if _port is None:
        raise RuntimeError("subject display port is not bound")
    return _port
