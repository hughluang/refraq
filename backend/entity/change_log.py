"""Change log on the entity database.

One log per Business Entity. Callers pass a connection and commit it themselves.
The trigger appends inside the row-write transaction. This module does not set
``refraq.change_log_source`` or ``refraq.change_log_subject``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.entity.attribute_type import resolve
from backend.entity.data.values import decode_row, reference_value_attr
from backend.entity.ddl import (
    ENTITY_CHANGE_LOG_SCHEMA,
    ENTITY_DATA_SCHEMA,
    ENTITY_OWNER_ROLE,
    ident,
    qualified_table,
)
from backend.entity.records import AttributeRecord

__all__ = [
    "CHANGE_LOG_SCHEMA",
    "EFFECTIVE_TABLE",
    "ENTRY_TABLE",
    "SOURCE_CHANNEL_RUN",
    "SOURCE_GUC",
    "SOURCE_USER",
    "SUBJECT_GUC",
    "CHANGE_LOG_PAGE_LIMIT",
    "ChangeLogEffective",
    "ChangeLogEntry",
    "ChangeLogPage",
    "ChangeLogTable",
    "delete_entries",
    "delete_entries_before",
    "ensure_shared_relations",
    "install_triggers",
    "list_effectives",
    "list_entries",
    "read_change_log",
    "read_change_log_entry",
    "map_legacy_cursor",
    "max_commit_seq",
    "read_effective",
    "read_entries_after",
    "read_purge_mark",
    "remove_triggers",
    "write_effective",
]

CHANGE_LOG_SCHEMA = ENTITY_CHANGE_LOG_SCHEMA
EFFECTIVE_TABLE = "effective"
ENTRY_TABLE = "entry"
PURGE_MARK_TABLE = "purge_mark"
SOURCE_GUC = "refraq.change_log_source"
SUBJECT_GUC = "refraq.change_log_subject"
SOURCE_USER = "user"
SOURCE_CHANNEL_RUN = "channel_run"
SOURCE_UNATTRIBUTED = "unattributed"
CHANGE_LOG_PAGE_LIMIT = 50

_APPEND_FUNCTION = "append_change"
_CHANGED_FUNCTION = "changed_columns"
_NOTE_COMMIT_FUNCTION = "note_commit_pending"
_ASSIGN_COMMIT_FUNCTION = "assign_commit_seq"
_COMMIT_COUNTER = "commit_counter"
_COMMIT_PENDING = "commit_pending"
_ENTITY_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NAME_MAX = 63
_TRIGGER_EVENTS = (
    ("insert", "INSERT", "REFERENCING NEW TABLE AS new_rows"),
    (
        "update",
        "UPDATE",
        "REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows",
    ),
    ("delete", "DELETE", "REFERENCING OLD TABLE AS old_rows"),
)


@dataclass(frozen=True, slots=True)
class ChangeLogEffective:
    """The recording facts one Business Entity is using.

    A missing row means recording is off. ``retention_days`` null means the
    log does not expire. ``applied_version_id`` stays null until a publish
    policy step records the version it finished.
    """

    entity_id: str
    recording: bool
    retention_days: int | None
    applied_version_id: str | None


@dataclass(frozen=True, slots=True)
class ChangeLogTable:
    """Decode target for one physical table's entries.

    ``physical_table`` is the quoted qualified name stored on the entry.
    ``business_key`` is that version's Business Key attribute, or none.
    """

    physical_table: str
    attributes: Sequence[AttributeRecord]
    reference_snapshots: Mapping[str, Any]
    business_key: str | None = None


@dataclass(frozen=True, slots=True)
class ChangeLogPage:
    """One sequence page. ``next_before_sequence`` is null on a short page."""

    items: list[ChangeLogEntry]
    limit: int
    next_before_sequence: int | None


@dataclass(frozen=True, slots=True)
class ChangeLogEntry:
    """One recorded row change, newest sequence first when listed.

    ``before`` and ``after`` are full physical rows. An insert has no before.
    A delete has no after. An update's before is rebuilt from the stored after
    plus the previous value of each column that differed.
    """

    entity_id: str
    physical_table: str
    operation: str
    sequence: int
    occurred_at: datetime
    source: str | None
    subject: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class _Snapshots:
    """Stand-in for a version head. Decode reads reference snapshots only."""

    def __init__(self) -> None:
        self.reference_snapshots: dict[str, Any] = {}


class _ImageTarget:
    def __init__(self, attributes: Sequence[AttributeRecord]) -> None:
        self.attributes = tuple(attributes)
        self.head = _Snapshots()


def ensure_shared_relations(conn: Connection) -> None:
    """Create the shared change-log schema, tables, and trigger function.

    Idempotent. Does not commit. Entity bootstrap calls this. A read does not:
    these statements lock the log table an open write already holds. Sequences
    and per-table triggers are created by ``install_triggers``. Commit
    sequences are assigned by a deferred trigger on the log itself.
    """
    role = str(conn.execute(text("SELECT current_user")).scalar_one())
    if role == ENTITY_OWNER_ROLE:
        _create_shared_objects(conn)
        return
    schema = ident(CHANGE_LOG_SCHEMA)
    owner = ident(ENTITY_OWNER_ROLE)
    conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {schema} AUTHORIZATION {owner}")
    conn.exec_driver_sql(f"ALTER SCHEMA {schema} OWNER TO {owner}")
    conn.exec_driver_sql(f"SET ROLE {owner}")
    try:
        conn.exec_driver_sql("SAVEPOINT change_log_ensure")
        try:
            _create_shared_objects(conn)
        except Exception:
            conn.exec_driver_sql("ROLLBACK TO SAVEPOINT change_log_ensure")
            raise
        else:
            conn.exec_driver_sql("RELEASE SAVEPOINT change_log_ensure")
    finally:
        conn.exec_driver_sql("RESET ROLE")


def list_effectives(conn: Connection) -> list[ChangeLogEffective]:
    """Return every effective row. The caller decides which ones to apply."""
    rows = conn.execute(
        text(
            "SELECT entity_id, recording, retention_days, applied_version_id "
            f"FROM {_effective_table()}"
        )
    ).mappings()
    return [
        ChangeLogEffective(
            entity_id=str(row["entity_id"]),
            recording=bool(row["recording"]),
            retention_days=(
                None if row["retention_days"] is None else int(row["retention_days"])
            ),
            applied_version_id=(
                None
                if row["applied_version_id"] is None
                else str(row["applied_version_id"])
            ),
        )
        for row in rows
    ]


def read_effective(conn: Connection, entity_id: str) -> ChangeLogEffective | None:
    """Return the effective row, or none when recording has no row."""
    entity_id = _entity_id(entity_id)
    row = (
        conn.execute(
            text(
                f"SELECT entity_id, recording, retention_days, applied_version_id "
                f"FROM {_effective_table()} WHERE entity_id = :entity_id"
            ),
            {"entity_id": entity_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return ChangeLogEffective(
        entity_id=str(row["entity_id"]),
        recording=bool(row["recording"]),
        retention_days=(
            None if row["retention_days"] is None else int(row["retention_days"])
        ),
        applied_version_id=(
            None
            if row["applied_version_id"] is None
            else str(row["applied_version_id"])
        ),
    )


def write_effective(conn: Connection, record: ChangeLogEffective) -> None:
    """Insert or replace the effective row. Does not arm tables or commit."""
    entity_id = _entity_id(record.entity_id)
    if not isinstance(record.recording, bool):
        raise ValueError("recording must be true or false")
    retention_days = _retention_days(record.retention_days)
    applied_version_id = _applied_version_id(record.applied_version_id)
    conn.execute(
        text(
            f"INSERT INTO {_effective_table()} "
            "(entity_id, recording, retention_days, applied_version_id) "
            "VALUES (:entity_id, :recording, :retention_days, :applied_version_id) "
            "ON CONFLICT (entity_id) DO UPDATE SET "
            "recording = EXCLUDED.recording, "
            "retention_days = EXCLUDED.retention_days, "
            "applied_version_id = EXCLUDED.applied_version_id"
        ),
        {
            "entity_id": entity_id,
            "recording": record.recording,
            "retention_days": retention_days,
            "applied_version_id": applied_version_id,
        },
    )


def install_triggers(
    conn: Connection,
    entity_id: str,
    tables: Sequence[str],
    *,
    schema: str = ENTITY_DATA_SCHEMA,
) -> None:
    """Arm physical tables and create this entity's sequence if it is new.

    The sequence stays when triggers are removed or entries are deleted.
    Does not commit.
    """
    entity_id = _entity_id(entity_id)
    schema = _schema_name(schema)
    conn.exec_driver_sql(f"CREATE SEQUENCE IF NOT EXISTS {_sequence_name(entity_id)}")
    function = qualified_table(CHANGE_LOG_SCHEMA, _APPEND_FUNCTION)
    for table in tables:
        relation = qualified_table(schema, table)
        for suffix, event, referencing in _TRIGGER_EVENTS:
            conn.exec_driver_sql(
                f"CREATE OR REPLACE TRIGGER {ident(f'change_log_{suffix}')} "
                f"AFTER {event} ON {relation} "
                f"{referencing} "
                f"FOR EACH STATEMENT "
                f"EXECUTE FUNCTION {function}('{entity_id}')"
            )


def remove_triggers(
    conn: Connection,
    entity_id: str,
    tables: Sequence[str],
    *,
    schema: str = ENTITY_DATA_SCHEMA,
) -> None:
    """Drop change-log triggers from these physical tables. Keeps the sequence."""
    _entity_id(entity_id)
    schema = _schema_name(schema)
    for table in tables:
        relation = qualified_table(schema, table)
        for suffix, _event, _referencing in _TRIGGER_EVENTS:
            conn.exec_driver_sql(
                f"DROP TRIGGER IF EXISTS {ident(f'change_log_{suffix}')} ON {relation}"
            )


def delete_entries(conn: Connection, entity_id: str) -> None:
    """Delete every entry of this entity. Does not restart its sequence.

    The same statement records the greatest deleted ``(commit_seq, seq)`` on
    ``purge_mark`` so a checkpoint behind that position can be reported.
    """
    entity_id = _entity_id(entity_id)
    _delete_noting_purge(
        conn,
        entity_id,
        "entity_id = :entity_id",
        {"entity_id": entity_id},
    )


def delete_entries_before(conn: Connection, entity_id: str, cutoff: datetime) -> None:
    """Delete entries whose transaction timestamp is strictly earlier than cutoff.

    The same statement records the greatest deleted ``(commit_seq, seq)`` on
    ``purge_mark``. An empty delete leaves the mark unchanged.
    """
    entity_id = _entity_id(entity_id)
    if not isinstance(cutoff, datetime) or cutoff.tzinfo is None:
        raise ValueError("cutoff must be an aware timestamp")
    _delete_noting_purge(
        conn,
        entity_id,
        "entity_id = :entity_id AND occurred_at < :cutoff",
        {"entity_id": entity_id, "cutoff": cutoff},
    )


def list_entries(
    conn: Connection,
    entity_id: str,
    attributes: Sequence[AttributeRecord],
) -> list[ChangeLogEntry]:
    """List this entity's entries, newest sequence first, with rebuilt images."""
    entity_id = _entity_id(entity_id)
    rows = conn.execute(
        text(
            "SELECT entity_id, physical_table, operation, seq, occurred_at, "
            "source, subject, image "
            f"FROM {_entry_table()} "
            "WHERE entity_id = :entity_id "
            "ORDER BY seq DESC"
        ),
        {"entity_id": entity_id},
    ).mappings()
    target = _ImageTarget(attributes)
    return _entries_decoded(conn, list(rows), lambda _row: target)


def read_change_log(
    conn: Connection,
    entity_id: str,
    tables: Sequence[ChangeLogTable],
    *,
    before_sequence: int | None = None,
    operation: str | None = None,
    source: str | None = None,
    subject: str | None = None,
    row_identity: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
) -> ChangeLogPage:
    """Matching entries, newest sequence first, at most one sequence page.

    ``before_sequence`` is an exclusive upper bound. ``next_before_sequence``
    is the smallest sequence on a full page and null when the page is short.
    A missing time bound does not constrain that side. ``source``
    ``unattributed`` matches a null source. ``row_identity`` matches ``row_id``
    or that table's Business Key exactly.
    """
    entity_id = _entity_id(entity_id)
    clauses = ["entity_id = :entity_id"]
    params: dict[str, Any] = {
        "entity_id": entity_id,
        "lim": CHANGE_LOG_PAGE_LIMIT,
    }
    if before_sequence is not None:
        clauses.append("seq < :before_sequence")
        params["before_sequence"] = before_sequence
    if operation is not None:
        clauses.append("operation = :operation")
        params["operation"] = operation
    if source == SOURCE_UNATTRIBUTED:
        clauses.append("source IS NULL")
    elif source is not None:
        clauses.append("source = :source")
        params["source"] = source
    if subject is not None:
        clauses.append("subject = :subject")
        params["subject"] = subject
    if occurred_from is not None:
        clauses.append("occurred_at >= :occurred_from")
        params["occurred_from"] = occurred_from
    if occurred_to is not None:
        clauses.append("occurred_at <= :occurred_to")
        params["occurred_to"] = occurred_to
    if row_identity is not None:
        identity_sql, identity_params = _row_identity_sql(tables, row_identity)
        clauses.append(identity_sql)
        params.update(identity_params)
    rows = list(
        conn.execute(
            text(
                "SELECT entity_id, physical_table, operation, seq, occurred_at, "
                "source, subject, image "
                f"FROM {_entry_table()} "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY seq DESC "
                "LIMIT :lim"
            ),
            params,
        ).mappings()
    )
    items = _entries_from_rows(conn, rows, tables)
    next_before = items[-1].sequence if len(items) == CHANGE_LOG_PAGE_LIMIT else None
    return ChangeLogPage(
        items=items,
        limit=CHANGE_LOG_PAGE_LIMIT,
        next_before_sequence=next_before,
    )


def read_change_log_entry(
    conn: Connection,
    entity_id: str,
    tables: Sequence[ChangeLogTable],
    sequence: int,
) -> ChangeLogEntry | None:
    """One entry by sequence, with the rebuilt physical images."""
    entity_id = _entity_id(entity_id)
    row = (
        conn.execute(
            text(
                "SELECT entity_id, physical_table, operation, seq, occurred_at, "
                "source, subject, image "
                f"FROM {_entry_table()} "
                "WHERE entity_id = :entity_id AND seq = :seq"
            ),
            {"entity_id": entity_id, "seq": sequence},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return _entry_from_row(conn, row, tables)


def read_purge_mark(conn: Connection, entity_id: str) -> tuple[int, int] | None:
    """Greatest deleted ``(commit_seq, seq)`` for this entity, or none."""
    entity_id = _entity_id(entity_id)
    row = (
        conn.execute(
            text(
                "SELECT commit_seq, seq "
                f"FROM {_purge_mark_table()} WHERE entity_id = :entity_id"
            ),
            {"entity_id": entity_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["commit_seq"] is None:
        return None
    return int(row["commit_seq"]), int(row["seq"])


def max_commit_seq(conn: Connection, entity_id: str) -> int:
    """Greatest committed sequence on this entity, or 0 when none is visible."""
    entity_id = _entity_id(entity_id)
    value = conn.execute(
        text(
            "SELECT COALESCE(MAX(commit_seq), 0) "
            f"FROM {_entry_table()} WHERE entity_id = :entity_id"
        ),
        {"entity_id": entity_id},
    ).scalar_one()
    return int(value)


def map_legacy_cursor(
    conn: Connection, entity_id: str, xact: int, seq: int
) -> tuple[int, int]:
    """Map one stored ``(xact, seq)`` cursor onto ``(commit_seq, seq)``.

    A row that is still present keeps its own commit sequence. A cursor strictly
    behind the purge mark stays strictly behind that mark's commit sequence. A
    cursor on the mark lands on the mark. Anything else lands on the latest
    surviving commit sequence at or before the old position, or ``(0, 0)``.
    """
    entity_id = _entity_id(entity_id)
    params = {"entity_id": entity_id, "xact": int(xact), "seq": int(seq)}
    found = (
        conn.execute(
            text(
                "SELECT commit_seq, seq "
                f"FROM {_entry_table()} "
                "WHERE entity_id = :entity_id "
                "AND xact = CAST(:xact AS text)::xid8 AND seq = :seq"
            ),
            params,
        )
        .mappings()
        .one_or_none()
    )
    if found is not None and found["commit_seq"] is not None:
        return int(found["commit_seq"]), int(found["seq"])
    mark = (
        conn.execute(
            text(
                "SELECT commit_seq, seq, "
                "(xact, seq) > (CAST(:xact AS text)::xid8, CAST(:seq AS bigint)) "
                "AS behind "
                f"FROM {_purge_mark_table()} WHERE entity_id = :entity_id"
            ),
            params,
        )
        .mappings()
        .one_or_none()
    )
    if mark is not None and mark["commit_seq"] is not None and mark["behind"]:
        return int(mark["commit_seq"]), int(mark["seq"]) - 1
    if mark is not None and mark["commit_seq"] is not None and not mark["behind"]:
        same = conn.execute(
            text(
                "SELECT 1 FROM "
                f"{_purge_mark_table()} WHERE entity_id = :entity_id "
                "AND xact = CAST(:xact AS text)::xid8 AND seq = :seq"
            ),
            params,
        ).one_or_none()
        if same is not None:
            return int(mark["commit_seq"]), int(mark["seq"])
    survivor = (
        conn.execute(
            text(
                "SELECT commit_seq, seq "
                f"FROM {_entry_table()} "
                "WHERE entity_id = :entity_id AND commit_seq IS NOT NULL "
                "AND (xact, seq) <= "
                "(CAST(:xact AS text)::xid8, CAST(:seq AS bigint)) "
                "ORDER BY commit_seq DESC LIMIT 1"
            ),
            params,
        )
        .mappings()
        .one_or_none()
    )
    if survivor is None:
        return (0, 0)
    return int(survivor["commit_seq"]), int(survivor["seq"])


def read_entries_after(
    conn: Connection,
    entity_id: str,
    tables: Sequence[ChangeLogTable],
    *,
    after_commit: int | None,
    bound_commit: int,
    limit: int,
) -> tuple[list[tuple[ChangeLogEntry, int]], bool]:
    """Entries with ``commit_seq`` at most ``bound_commit``, oldest first.

    ``after_commit`` is an exclusive lower bound, or absent to start at the
    beginning. ``limit`` is the page size. The boolean is true when another
    matching entry exists after this page. The integer beside each entry is
    its ``commit_seq``. A transaction that has not committed has no
    ``commit_seq``, so its rows stay out and do not hide a later commit.
    """
    entity_id = _entity_id(entity_id)
    if limit < 1:
        raise ValueError("limit must be at least 1")
    clauses = [
        "entity_id = :entity_id",
        "commit_seq IS NOT NULL",
        "commit_seq <= :bound_commit",
    ]
    params: dict[str, Any] = {
        "entity_id": entity_id,
        "bound_commit": int(bound_commit),
        "lim": limit + 1,
    }
    if after_commit is not None:
        clauses.append("commit_seq > :after_commit")
        params["after_commit"] = int(after_commit)
    rows = list(
        conn.execute(
            text(
                "SELECT entity_id, physical_table, operation, seq, occurred_at, "
                "source, subject, image, commit_seq "
                f"FROM {_entry_table()} "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY commit_seq "
                "LIMIT :lim"
            ),
            params,
        ).mappings()
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    entries = _entries_from_rows(conn, page, tables)
    return (
        [
            (entry, int(row["commit_seq"]))
            for entry, row in zip(entries, page, strict=True)
        ],
        has_more,
    )


def _entries_from_rows(
    conn: Connection,
    rows: Sequence[Mapping[str, Any]],
    tables: Sequence[ChangeLogTable],
) -> list[ChangeLogEntry]:
    return _entries_decoded(
        conn,
        rows,
        lambda row: _target_for(str(row["physical_table"]), tables),
    )


def _entries_decoded(
    conn: Connection,
    rows: Sequence[Mapping[str, Any]],
    target_for_row: Callable[[Mapping[str, Any]], _ImageTarget],
) -> list[ChangeLogEntry]:
    """One page: rebuild each image, decode the page once, keep entry order."""
    slots: list[tuple[dict[str, Any] | None, _ImageTarget]] = []
    for row in rows:
        target = target_for_row(row)
        before_raw, after_raw = _rebuild(
            str(row["operation"]), _image_dict(row["image"])
        )
        slots.append((before_raw, target))
        slots.append((after_raw, target))
    decoded = _decode_images(conn, slots)
    return [
        _entry_from_decoded(row, decoded[index * 2], decoded[index * 2 + 1])
        for index, row in enumerate(rows)
    ]


def _entry_from_row(
    conn: Connection,
    row: Mapping[str, Any],
    tables: Sequence[ChangeLogTable],
) -> ChangeLogEntry:
    physical = str(row["physical_table"])
    target = _target_for(physical, tables)
    before_raw, after_raw = _rebuild(str(row["operation"]), _image_dict(row["image"]))
    return _entry_from_decoded(
        row,
        _decode_image(conn, before_raw, target.attributes, target),
        _decode_image(conn, after_raw, target.attributes, target),
    )


def _entry_from_decoded(
    row: Mapping[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> ChangeLogEntry:
    return ChangeLogEntry(
        entity_id=str(row["entity_id"]),
        physical_table=str(row["physical_table"]),
        operation=str(row["operation"]),
        sequence=int(row["seq"]),
        occurred_at=row["occurred_at"],
        source=None if row["source"] is None else str(row["source"]),
        subject=None if row["subject"] is None else str(row["subject"]),
        before=before,
        after=after,
    )


def _target_for(physical: str, tables: Sequence[ChangeLogTable]) -> _ImageTarget:
    for table in tables:
        if table.physical_table == physical:
            target = _ImageTarget(table.attributes)
            target.head.reference_snapshots = dict(table.reference_snapshots)
            return target
    raise ValueError(f"change-log physical table is not loaded: {physical}")


def _row_identity_sql(
    tables: Sequence[ChangeLogTable], identity: str
) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {"row_identity": identity}
    parts = [
        "COALESCE(image->'after'->>'row_id', image->'before'->>'row_id') "
        "= :row_identity"
    ]
    for index, table in enumerate(tables):
        if not table.business_key:
            continue
        key = f"bk{index}"
        table_key = f"pt{index}"
        params[key] = table.business_key
        params[table_key] = table.physical_table
        parts.append(
            f"(physical_table = :{table_key} AND "
            f"COALESCE(image->'after'->>:{key}, image->'before'->>:{key}) "
            "= :row_identity)"
        )
    return "(" + " OR ".join(parts) + ")", params


def _create_shared_objects(conn: Connection) -> None:
    """Tables and the trigger function. The schema already exists and is owned."""
    schema = ident(CHANGE_LOG_SCHEMA)
    conn.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS {_effective_table()} ("
        "entity_id text PRIMARY KEY, "
        "recording boolean NOT NULL, "
        "retention_days integer, "
        "applied_version_id text, "
        "CONSTRAINT change_log_retention_days "
        "CHECK (retention_days IS NULL OR retention_days >= 1)"
        ")"
    )
    conn.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS {_entry_table()} ("
        "entity_id text NOT NULL, "
        "physical_table text NOT NULL, "
        "operation text NOT NULL, "
        "seq bigint NOT NULL, "
        "occurred_at timestamptz NOT NULL, "
        "source text, "
        "subject text, "
        "image jsonb NOT NULL, "
        "xact xid8 NOT NULL DEFAULT pg_current_xact_id(), "
        "commit_seq bigint, "
        "PRIMARY KEY (entity_id, seq), "
        "CONSTRAINT change_log_operation "
        "CHECK (operation IN ('insert', 'update', 'delete')), "
        "CONSTRAINT change_log_source "
        "CHECK (source IS NULL OR source IN ('user', 'channel_run')), "
        "CONSTRAINT change_log_unattributed "
        "CHECK (source IS NOT NULL OR subject IS NULL)"
        ")"
    )
    _ensure_entry_position(conn)
    _ensure_commit_order(conn)
    changed = qualified_table(CHANGE_LOG_SCHEMA, _CHANGED_FUNCTION)
    append = qualified_table(CHANGE_LOG_SCHEMA, _APPEND_FUNCTION)
    conn.exec_driver_sql(_changed_columns_sql(changed))
    conn.exec_driver_sql(_append_change_sql(append, changed))
    conn.exec_driver_sql(f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC")
    conn.exec_driver_sql(
        f"REVOKE ALL ON TABLE {_effective_table()}, {_entry_table()}, "
        f"{_purge_mark_table()}, {_commit_counter_table()}, "
        f"{_commit_pending_table()} FROM PUBLIC"
    )
    note = qualified_table(CHANGE_LOG_SCHEMA, _NOTE_COMMIT_FUNCTION)
    assign = qualified_table(CHANGE_LOG_SCHEMA, _ASSIGN_COMMIT_FUNCTION)
    conn.exec_driver_sql(
        f"REVOKE ALL ON FUNCTION {changed}(jsonb, jsonb), {append}(), "
        f"{note}(), {assign}() FROM PUBLIC"
    )


def _changed_columns_sql(function: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {function}(old_row jsonb, new_row jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $body$
  SELECT COALESCE(
    (
      SELECT jsonb_object_agg(d.key, d.value)
      FROM (
        SELECT o.key, o.value
        FROM jsonb_each(old_row) AS o(key, value)
        WHERE o.value IS DISTINCT FROM (new_row -> o.key)
      ) AS d
    ),
    '{{}}'::jsonb
  );
$body$
"""


def _append_change_sql(function: str, changed: str) -> str:
    effective = _effective_table()
    entry = _entry_table()
    return f"""
CREATE OR REPLACE FUNCTION {function}() RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
AS $body$
DECLARE
  ent text := TG_ARGV[0];
  recording boolean;
  src text;
  subj text;
  qualified text;
BEGIN
  SELECT e.recording INTO recording
  FROM {effective} AS e
  WHERE e.entity_id = ent;

  IF recording IS NOT TRUE THEN
    RETURN NULL;
  END IF;

  src := current_setting('{SOURCE_GUC}', true);
  IF src IS NULL OR btrim(src) = '' OR src NOT IN ('{SOURCE_USER}', '{SOURCE_CHANNEL_RUN}') THEN
    src := NULL;
    subj := NULL;
  ELSE
    subj := nullif(btrim(current_setting('{SUBJECT_GUC}', true)), '');
  END IF;

  qualified := '"' || replace(TG_TABLE_SCHEMA, '"', '""')
    || '"."' || replace(TG_TABLE_NAME, '"', '""') || '"';

  IF TG_OP = 'INSERT' THEN
    INSERT INTO {entry} (
      entity_id, physical_table, operation, seq, occurred_at, source, subject, image, xact
    )
    SELECT ent, qualified, 'insert',
           nextval(format('{CHANGE_LOG_SCHEMA}.%%I', 'seq_' || ent)::regclass),
           transaction_timestamp(), src, subj,
           jsonb_build_object('after', to_jsonb(n)),
           pg_current_xact_id()
    FROM new_rows AS n;
  ELSIF TG_OP = 'DELETE' THEN
    INSERT INTO {entry} (
      entity_id, physical_table, operation, seq, occurred_at, source, subject, image, xact
    )
    SELECT ent, qualified, 'delete',
           nextval(format('{CHANGE_LOG_SCHEMA}.%%I', 'seq_' || ent)::regclass),
           transaction_timestamp(), src, subj,
           jsonb_build_object('before', to_jsonb(o)),
           pg_current_xact_id()
    FROM old_rows AS o;
  ELSIF TG_OP = 'UPDATE' THEN
    INSERT INTO {entry} (
      entity_id, physical_table, operation, seq, occurred_at, source, subject, image, xact
    )
    SELECT ent, qualified, 'update',
           nextval(format('{CHANGE_LOG_SCHEMA}.%%I', 'seq_' || ent)::regclass),
           transaction_timestamp(), src, subj,
           jsonb_build_object(
             'after', to_jsonb(n),
             'changed', {changed}(to_jsonb(o), to_jsonb(n))
           ),
           pg_current_xact_id()
    FROM new_rows AS n
    JOIN old_rows AS o ON o.row_id = n.row_id
    WHERE to_jsonb(o) IS DISTINCT FROM to_jsonb(n);
  END IF;
  RETURN NULL;
END
$body$
"""


def _delete_noting_purge(
    conn: Connection,
    entity_id: str,
    where_sql: str,
    params: dict[str, Any],
) -> None:
    """Delete matching entries and raise the purge mark to the greatest position."""
    mark = _purge_mark_table()
    conn.execute(
        text(
            f"WITH deleted AS ("
            f"DELETE FROM {_entry_table()} WHERE {where_sql} "
            f"RETURNING xact, seq, commit_seq"
            f"), top AS ("
            f"SELECT xact, seq, commit_seq FROM deleted "
            f"WHERE commit_seq IS NOT NULL "
            f"ORDER BY commit_seq DESC, seq DESC LIMIT 1"
            f") "
            f"INSERT INTO {mark} AS mark (entity_id, xact, seq, commit_seq) "
            f"SELECT :entity_id, xact, seq, commit_seq FROM top "
            f"ON CONFLICT (entity_id) DO UPDATE SET "
            f"xact = CASE WHEN mark.commit_seq IS NULL "
            f"OR (EXCLUDED.commit_seq, EXCLUDED.seq) > (mark.commit_seq, mark.seq) "
            f"THEN EXCLUDED.xact ELSE mark.xact END, "
            f"seq = CASE WHEN mark.commit_seq IS NULL "
            f"OR (EXCLUDED.commit_seq, EXCLUDED.seq) > (mark.commit_seq, mark.seq) "
            f"THEN EXCLUDED.seq ELSE mark.seq END, "
            f"commit_seq = CASE WHEN mark.commit_seq IS NULL "
            f"OR (EXCLUDED.commit_seq, EXCLUDED.seq) > (mark.commit_seq, mark.seq) "
            f"THEN EXCLUDED.commit_seq ELSE mark.commit_seq END"
        ),
        params,
    )


def _ensure_entry_position(conn: Connection) -> None:
    """Add the transaction id, its index, and the purge-mark table.

    Existing rows receive ``xact`` 0, which sorts before every real transaction.
    Later inserts take ``pg_current_xact_id`` unless the trigger sets it.
    """
    entry = _entry_table()
    conn.exec_driver_sql(
        f"ALTER TABLE {entry} ADD COLUMN IF NOT EXISTS "
        "xact xid8 NOT NULL DEFAULT '0'::xid8"
    )
    conn.exec_driver_sql(
        f"ALTER TABLE {entry} ALTER COLUMN xact SET DEFAULT pg_current_xact_id()"
    )
    conn.exec_driver_sql(
        f"CREATE INDEX IF NOT EXISTS change_log_entry_position "
        f"ON {entry} (entity_id, xact, seq)"
    )
    conn.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS {_purge_mark_table()} ("
        "entity_id text PRIMARY KEY, "
        "xact xid8 NOT NULL, "
        "seq bigint NOT NULL, "
        "commit_seq bigint"
        ")"
    )


def _ensure_commit_order(conn: Connection) -> None:
    """Add commit sequences, the per-entity counter, and the assign trigger.

    Existing committed rows are numbered in ``(xact, seq)`` order. The counter
    update is part of the writing transaction, so a rollback returns the numbers.
    """
    entry = _entry_table()
    counter = _commit_counter_table()
    pending = _commit_pending_table()
    note = qualified_table(CHANGE_LOG_SCHEMA, _NOTE_COMMIT_FUNCTION)
    assign = qualified_table(CHANGE_LOG_SCHEMA, _ASSIGN_COMMIT_FUNCTION)
    conn.exec_driver_sql(
        f"ALTER TABLE {entry} ADD COLUMN IF NOT EXISTS commit_seq bigint"
    )
    conn.exec_driver_sql(
        f"CREATE INDEX IF NOT EXISTS change_log_entry_commit "
        f"ON {entry} (entity_id, commit_seq)"
    )
    conn.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS {counter} ("
        "entity_id text PRIMARY KEY, "
        "last_seq bigint NOT NULL"
        ")"
    )
    conn.exec_driver_sql(
        f"CREATE TABLE IF NOT EXISTS {pending} ("
        "xact xid8 NOT NULL, "
        "entity_id text NOT NULL, "
        "PRIMARY KEY (xact, entity_id)"
        ")"
    )
    conn.exec_driver_sql(
        f"ALTER TABLE {_purge_mark_table()} ADD COLUMN IF NOT EXISTS commit_seq bigint"
    )
    conn.exec_driver_sql(_note_commit_sql(note, pending))
    conn.exec_driver_sql(_assign_commit_sql(assign, entry, counter, pending))
    conn.exec_driver_sql(
        f"CREATE OR REPLACE TRIGGER change_log_note_commit "
        f"AFTER INSERT ON {entry} "
        f"REFERENCING NEW TABLE AS new_rows "
        f"FOR EACH STATEMENT "
        f"EXECUTE FUNCTION {note}()"
    )
    conn.exec_driver_sql(
        f"DROP TRIGGER IF EXISTS change_log_assign_commit ON {pending}"
    )
    conn.exec_driver_sql(
        f"CREATE CONSTRAINT TRIGGER change_log_assign_commit "
        f"AFTER INSERT ON {pending} "
        f"DEFERRABLE INITIALLY DEFERRED "
        f"FOR EACH ROW "
        f"EXECUTE FUNCTION {assign}()"
    )
    conn.exec_driver_sql(f"LOCK TABLE {entry} IN SHARE ROW EXCLUSIVE MODE")
    conn.exec_driver_sql(
        f"WITH floors AS ("
        f"SELECT entity_id, COALESCE(MAX(commit_seq), 0) AS floor "
        f"FROM {entry} GROUP BY entity_id"
        f"), numbered AS ("
        f"SELECT e.entity_id, e.seq, "
        f"f.floor + row_number() OVER ("
        f"PARTITION BY e.entity_id ORDER BY e.xact, e.seq"
        f") AS commit_seq "
        f"FROM {entry} AS e "
        f"JOIN floors AS f ON f.entity_id = e.entity_id "
        f"WHERE e.commit_seq IS NULL"
        f") "
        f"UPDATE {entry} AS e SET commit_seq = numbered.commit_seq "
        f"FROM numbered "
        f"WHERE e.entity_id = numbered.entity_id AND e.seq = numbered.seq"
    )
    conn.exec_driver_sql(
        f"INSERT INTO {counter} (entity_id, last_seq) "
        f"SELECT entity_id, MAX(commit_seq) FROM {entry} "
        f"WHERE commit_seq IS NOT NULL GROUP BY entity_id "
        f"ON CONFLICT (entity_id) DO UPDATE "
        f"SET last_seq = GREATEST({counter}.last_seq, EXCLUDED.last_seq)"
    )
    mark = _purge_mark_table()
    conn.exec_driver_sql(
        f"UPDATE {mark} AS m SET commit_seq = COALESCE(("
        f"SELECT MAX(e.commit_seq) FROM {entry} AS e "
        f"WHERE e.entity_id = m.entity_id "
        f"AND (e.xact, e.seq) <= (m.xact, m.seq)"
        f"), 0) "
        f"WHERE m.commit_seq IS NULL"
    )


def _note_commit_sql(function: str, pending: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {function}() RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
AS $body$
BEGIN
  INSERT INTO {pending} (xact, entity_id)
  SELECT DISTINCT pg_current_xact_id(), n.entity_id
  FROM new_rows AS n
  ON CONFLICT DO NOTHING;
  RETURN NULL;
END
$body$
"""


def _assign_commit_sql(function: str, entry: str, counter: str, pending: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {function}() RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
AS $body$
DECLARE
  ent text;
  base_seq bigint;
  next_seq bigint;
BEGIN
  FOR ent IN
    SELECT entity_id FROM {pending}
    WHERE xact = pg_current_xact_id()
    ORDER BY entity_id
  LOOP
    INSERT INTO {counter} (entity_id, last_seq)
    VALUES (ent, 0)
    ON CONFLICT (entity_id) DO NOTHING;

    SELECT last_seq INTO base_seq
    FROM {counter}
    WHERE entity_id = ent
    FOR UPDATE;

    WITH ordered AS (
      SELECT seq, row_number() OVER (ORDER BY seq) AS rn
      FROM {entry}
      WHERE entity_id = ent
        AND xact = pg_current_xact_id()
        AND commit_seq IS NULL
    ), updated AS (
      UPDATE {entry} AS e
      SET commit_seq = base_seq + ordered.rn
      FROM ordered
      WHERE e.entity_id = ent AND e.seq = ordered.seq
      RETURNING e.commit_seq
    )
    SELECT COALESCE(MAX(commit_seq), base_seq) INTO next_seq FROM updated;

    UPDATE {counter}
    SET last_seq = next_seq
    WHERE entity_id = ent;
  END LOOP;

  DELETE FROM {pending} WHERE xact = pg_current_xact_id();
  RETURN NULL;
END
$body$
"""


def _effective_table() -> str:
    return qualified_table(CHANGE_LOG_SCHEMA, EFFECTIVE_TABLE)


def _entry_table() -> str:
    return qualified_table(CHANGE_LOG_SCHEMA, ENTRY_TABLE)


def _purge_mark_table() -> str:
    return qualified_table(CHANGE_LOG_SCHEMA, PURGE_MARK_TABLE)


def _commit_counter_table() -> str:
    return qualified_table(CHANGE_LOG_SCHEMA, _COMMIT_COUNTER)


def _commit_pending_table() -> str:
    return qualified_table(CHANGE_LOG_SCHEMA, _COMMIT_PENDING)


def _sequence_name(entity_id: str) -> str:
    return qualified_table(CHANGE_LOG_SCHEMA, f"seq_{entity_id}")


def _rebuild(
    operation: str, image: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if operation == "insert":
        return None, dict(image["after"])
    if operation == "delete":
        return dict(image["before"]), None
    after = dict(image["after"])
    before = dict(after)
    changed = image.get("changed") or {}
    for key, value in changed.items():
        before[str(key)] = value
    return before, after


def _physical_cast(attr: AttributeRecord, target: _ImageTarget) -> str:
    """Column cast for one stored image value.

    A reference column uses the version's snapshot. Without that snapshot
    the decode raises ``EntityNotServing``, the same as a serving read.
    """
    if attr.type == "reference":
        attr = reference_value_attr(attr, target)  # type: ignore[arg-type]
    return resolve(attr.type).physical_sql(attr)


_ROW_ID_KEY = "'row_id'"


def _cast_as(extracted: str, physical: str) -> str:
    """``CAST((extracted) AS physical)``. One image and both page shapes share this."""
    return f"CAST(({extracted}) AS {physical})"


def _cast_expr(jsonb_expr: str, key_expr: str, physical: str) -> str:
    """``CAST((jsonb ->> key) AS physical)``."""
    return _cast_as(f"{jsonb_expr} ->> {key_expr}", physical)


def _guarded_cast(group: int, key_expr: str, physical: str) -> str:
    """``->>`` then ``CAST``, only when this image's target matches.

    The same attribute name may use a different physical type on another
    table in the page. ``target`` selects the image's own cast.
    """
    extracted = f"CASE WHEN target = {group} THEN CAST(img AS jsonb) ->> {key_expr} END"
    return _cast_as(extracted, physical)


def _cast_columns(
    attributes: Sequence[AttributeRecord],
    target: _ImageTarget,
    params: dict[str, Any],
    *,
    key_prefix: str,
    project: Callable[[str, str], str],
    column_alias: Callable[[int], str],
) -> list[str]:
    """``row_id``, then each attribute, in list order.

    ``project`` is ``(key_expr, physical) -> CAST expression``. Names are
    bound parameters. ``column_alias`` names column 0, then each attribute.
    """
    selects = [f"{project(_ROW_ID_KEY, 'bigint')} AS {column_alias(0)}"]
    for index, attr in enumerate(attributes):
        key = f"{key_prefix}{index}"
        params[key] = attr.name
        physical = _physical_cast(attr, target)
        selects.append(f"{project(f':{key}', physical)} AS {column_alias(index + 1)}")
    return selects


def _decode_images(
    conn: Connection,
    images: Sequence[tuple[dict[str, Any] | None, _ImageTarget]],
) -> list[dict[str, Any] | None]:
    """Decode the non-null images of one page in one statement.

    A null image stays None and is not sent. A page that mixes physical
    tables still sends one statement. Each column is cast only for the
    target that owns it, with that target's ``_physical_cast`` type.
    """
    decoded: list[dict[str, Any] | None] = [None] * len(images)
    pending: list[tuple[int, dict[str, Any], _ImageTarget]] = []
    for index, (image, target) in enumerate(images):
        if image is not None:
            pending.append((index, image, target))
    if not pending:
        return decoded
    groups, owners = _assign_groups(pending)
    payload = [image for _index, image, _target in pending]
    if len(groups) == 1:
        rows = _decode_target_page(conn, groups[0], payload)
    else:
        rows = _decode_mixed_page(conn, groups, payload, owners)
    _store_decoded(decoded, pending, rows, owners)
    return decoded


def _assign_groups(
    pending: Sequence[tuple[int, dict[str, Any], _ImageTarget]],
) -> tuple[list[_ImageTarget], list[int]]:
    groups: list[_ImageTarget] = []
    seen: dict[str, int] = {}
    owners: list[int] = []
    for _index, _image, target in pending:
        key = _target_key(target)
        gid = seen.get(key)
        if gid is None:
            gid = len(groups)
            seen[key] = gid
            groups.append(target)
        owners.append(gid)
    return groups, owners


def _target_key(target: _ImageTarget) -> str:
    snaps = json.dumps(dict(target.head.reference_snapshots), sort_keys=True)
    identity = [
        (
            attr.name,
            attr.type,
            attr.max_length,
            attr.precision,
            attr.scale,
            attr.dictionary_id,
            attr.target_entity_id,
        )
        for attr in target.attributes
    ]
    return json.dumps({"attributes": identity, "snapshots": snaps}, sort_keys=True)


def _decode_target_page(
    conn: Connection,
    target: _ImageTarget,
    images: Sequence[dict[str, Any]],
) -> Sequence[Mapping[str, Any]]:
    params: dict[str, Any] = {"payload": json.dumps(list(images))}
    jsonb_expr = "CAST(img AS jsonb)"
    selects = _cast_columns(
        target.attributes,
        target,
        params,
        key_prefix="k",
        project=lambda key_expr, physical: _cast_expr(jsonb_expr, key_expr, physical),
        column_alias=lambda index: ident(f"g0c{index}"),
    )
    return list(
        conn.execute(
            text(
                "SELECT n, "
                + ", ".join(selects)
                + " FROM jsonb_array_elements(CAST(:payload AS jsonb))"
                " WITH ORDINALITY AS s(img, n)"
            ),
            params,
        ).mappings()
    )


def _decode_mixed_page(
    conn: Connection,
    groups: Sequence[_ImageTarget],
    images: Sequence[dict[str, Any]],
    owners: Sequence[int],
) -> Sequence[Mapping[str, Any]]:
    payload = [
        {"t": owners[index], "img": image} for index, image in enumerate(images)
    ]
    params: dict[str, Any] = {"payload": json.dumps(payload)}
    selects: list[str] = []
    for gid, target in enumerate(groups):
        selects.extend(
            _cast_columns(
                target.attributes,
                target,
                params,
                key_prefix=f"k{gid}_",
                project=lambda key_expr, physical, group=gid: _guarded_cast(
                    group, key_expr, physical
                ),
                column_alias=lambda index, group=gid: ident(f"g{group}c{index}"),
            )
        )
    return list(
        conn.execute(
            text(
                "WITH src AS ("
                "SELECT CAST(elem ->> 't' AS integer) AS target, "
                "elem -> 'img' AS img, n "
                "FROM jsonb_array_elements(CAST(:payload AS jsonb)) "
                "WITH ORDINALITY AS s(elem, n)"
                ") SELECT n, " + ", ".join(selects) + " FROM src"
            ),
            params,
        ).mappings()
    )


def _store_decoded(
    decoded: list[dict[str, Any] | None],
    pending: Sequence[tuple[int, dict[str, Any], _ImageTarget]],
    rows: Sequence[Mapping[str, Any]],
    owners: Sequence[int],
) -> None:
    by_n = {int(row["n"]): row for row in rows}
    for ordinal, (index, _image, target) in enumerate(pending, start=1):
        gid = owners[ordinal - 1]
        columns = ["row_id", *[attr.name for attr in target.attributes]]
        row = by_n[ordinal]
        values = tuple(row[f"g{gid}c{col}"] for col in range(len(columns)))
        decoded[index] = decode_row(columns, values, target)  # type: ignore[arg-type]


def _decode_image(
    conn: Connection,
    image: dict[str, Any] | None,
    attributes: Sequence[AttributeRecord],
    target: _ImageTarget,
) -> dict[str, Any] | None:
    if image is None:
        return None
    columns = ["row_id", *[attr.name for attr in attributes]]
    params: dict[str, Any] = {"img": json.dumps(image)}
    jsonb_expr = "CAST(:img AS jsonb)"
    selects = _cast_columns(
        attributes,
        target,
        params,
        key_prefix="k",
        project=lambda key_expr, physical: _cast_expr(jsonb_expr, key_expr, physical),
        column_alias=lambda index: (
            "row_id" if index == 0 else ident(attributes[index - 1].name)
        ),
    )
    row = conn.execute(text("SELECT " + ", ".join(selects)), params).one()
    return decode_row(columns, tuple(row), target)  # type: ignore[arg-type]


def _image_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        loaded = json.loads(value)
    else:
        loaded = value
    if not isinstance(loaded, dict):
        raise ValueError("change-log image must be an object")
    return loaded


def _entity_id(entity_id: str) -> str:
    if not isinstance(entity_id, str) or _ENTITY_ID_RE.fullmatch(entity_id) is None:
        raise ValueError("entity id must be an identifier")
    if len(f"seq_{entity_id}") > _NAME_MAX:
        raise ValueError("entity id is too long for a change-log sequence")
    return entity_id


def _schema_name(schema: str) -> str:
    ident(schema)
    return schema


def _retention_days(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("retention_days must be null or a whole number of days >= 1")
    return value


def _applied_version_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("applied_version_id must be a string or null")
    return value
