"""Change-log read for a Data Channel checkpoint.

One page is every entry whose transaction id is strictly below a snapshot
xmin captured for the run, after a stored ``(xact, seq)``. The caller commits
nothing here. Images are the decoded physical row, JSON-safe.

Shared relations come from entity bootstrap. These reads do not create or
alter them. An open write already holds the log table, and DDL here would
fail the read instead of letting the snapshot bound hide that write.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from backend.core.time import format_instant
from backend.entity.change_log import (
    read_effective,
    read_entries_after,
    read_purge_mark,
)
from backend.entity.entity_db import get_entity_engine
from backend.entity.service import change_log_tables

__all__ = [
    "ChangeEntry",
    "ChangeLogOff",
    "ChangePage",
    "ChangePosition",
    "capture_bound",
    "purge_mark",
    "read_changes",
    "recording_enabled",
]


class ChangeLogOff(Exception):
    """The entity has no effective change-log row, or recording is off."""


@dataclass(frozen=True, slots=True)
class ChangePosition:
    """One consumed position. ``xact`` is the transaction id; ``seq`` is the log sequence."""

    xact: int
    seq: int


@dataclass(frozen=True, slots=True)
class ChangeEntry:
    """One decoded change-log row, in ``(xact, seq)`` order."""

    sequence: int
    xact: int
    operation: str
    occurred_at: str
    source: str | None
    subject: str | None
    physical_table: str
    row_id: int | None
    business_key: Any
    has_business_key: bool
    before: dict[str, Any] | None
    after: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ChangePage:
    """One forward page. ``has_more`` is true when another row is still below the bound."""

    entries: list[ChangeEntry]
    has_more: bool


def capture_bound() -> int:
    """Snapshot xmin as an integer. Every transaction strictly below it has ended."""
    with get_entity_engine().begin() as conn:
        value = conn.execute(
            text("SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint")
        ).scalar_one()
    return int(value)


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


def read_changes(
    entity_id: str,
    *,
    after: ChangePosition | None,
    bound: int,
    limit: int,
) -> ChangePage:
    """Read one forward page. Raises ``ChangeLogOff`` when recording is off.

    ``after`` is exclusive. ``bound`` is the snapshot xmin captured for the run.
    A missing entity is ``EntityNotFound``.
    """
    tables = change_log_tables(entity_id)
    with get_entity_engine().begin() as conn:
        effective = read_effective(conn, entity_id)
        if effective is None or not effective.recording:
            raise ChangeLogOff()
        spans, has_more = read_entries_after(
            conn,
            entity_id,
            tables,
            after_xact=None if after is None else after.xact,
            after_seq=None if after is None else after.seq,
            bound_xact=bound,
            limit=limit,
        )
    entries = [_entry(span, xact, tables) for span, xact in spans]
    return ChangePage(entries=entries, has_more=has_more)


def _entry(span: Any, xact: int, tables: Any) -> ChangeEntry:
    image = span.after if span.after is not None else span.before
    row: dict[str, Any] = {} if image is None else image
    key_name = next(
        (
            table.business_key
            for table in tables
            if table.physical_table == span.physical_table
        ),
        None,
    )
    row_id = row.get("row_id")
    return ChangeEntry(
        sequence=span.sequence,
        xact=xact,
        operation=span.operation,
        occurred_at=format_instant(span.occurred_at),
        source=span.source,
        subject=span.subject,
        physical_table=span.physical_table,
        row_id=None if row_id is None else int(row_id),
        business_key=None if key_name is None else _jsonable(row.get(key_name)),
        has_business_key=key_name is not None,
        before=_jsonable(span.before),
        after=_jsonable(span.after),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    return value
