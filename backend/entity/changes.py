"""Change-log bounds for a Data Channel checkpoint.

Recording, the purge mark, and the commit-sequence bound live here. Projected
pages are ``entity.history.service.read_incremental``. These reads do not
create or alter relations. An open write already holds the log table, and DDL
here would fail the read.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from backend.entity.change_log import (
    map_legacy_cursor,
    max_commit_seq,
    read_effective,
    read_purge_mark,
)
from backend.entity.entity_db import get_entity_engine

__all__ = [
    "ChangeLogOff",
    "ChangePosition",
    "capture_bound",
    "commit_seq_ready",
    "legacy_commit_position",
    "purge_mark",
    "recording_enabled",
]


class ChangeLogOff(Exception):
    """The entity has no effective change-log row, or recording is off."""


@dataclass(frozen=True, slots=True)
class ChangePosition:
    """One consumed position. ``xact`` stores the commit sequence; ``seq`` is the log sequence."""

    xact: int
    seq: int


def capture_bound(entity_id: str) -> int:
    """Greatest committed sequence on this entity, or 0 when none is visible."""
    with get_entity_engine().begin() as conn:
        return max_commit_seq(conn, entity_id)


def commit_seq_ready() -> bool:
    """True when the entity log has the commit-sequence column."""
    from backend.entity.change_log import CHANGE_LOG_SCHEMA

    with get_entity_engine().begin() as conn:
        found = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'entry' "
                "AND column_name = 'commit_seq'"
            ),
            {"schema": CHANGE_LOG_SCHEMA},
        ).first()
    return found is not None


def legacy_commit_position(entity_id: str, xact: int, seq: int) -> ChangePosition:
    """Rewrite one stored transaction-id cursor into commit-sequence order."""
    with get_entity_engine().begin() as conn:
        found = map_legacy_cursor(conn, entity_id, xact, seq)
    return ChangePosition(xact=found[0], seq=found[1])


def recording_enabled(entity_id: str) -> bool:
    """True only when the effective row exists and recording is on."""
    with get_entity_engine().begin() as conn:
        row = read_effective(conn, entity_id)
    return row is not None and row.recording


def purge_mark(entity_id: str) -> ChangePosition | None:
    """Greatest deleted position, or none when nothing has been purged."""
    with get_entity_engine().begin() as conn:
        found = read_purge_mark(conn, entity_id)
    if found is None:
        return None
    return ChangePosition(xact=found[0], seq=found[1])
