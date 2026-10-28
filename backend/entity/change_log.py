"""Change log on the entity database.

One log per Business Entity. Callers pass a connection and commit it themselves.
The trigger appends inside the row-write transaction. This module does not set
``refraq.change_log_source`` or ``refraq.change_log_subject``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
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
    "read_effective",
    "remove_triggers",
    "write_effective",
]

CHANGE_LOG_SCHEMA = ENTITY_CHANGE_LOG_SCHEMA
EFFECTIVE_TABLE = "effective"
ENTRY_TABLE = "entry"
SOURCE_GUC = "refraq.change_log_source"
SUBJECT_GUC = "refraq.change_log_subject"
SOURCE_USER = "user"
SOURCE_CHANNEL_RUN = "channel_run"
SOURCE_UNATTRIBUTED = "unattributed"
CHANGE_LOG_PAGE_LIMIT = 50

_APPEND_FUNCTION = "append_change"
_CHANGED_FUNCTION = "changed_columns"
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

    Idempotent. Does not commit. Sequences and per-table triggers are created
    by ``install_triggers``.
    """
    role = str(conn.execute(text("SELECT current_user")).scalar_one())
    if role == ENTITY_OWNER_ROLE:
        _create_shared_objects(conn)
        return
    schema = ident(CHANGE_LOG_SCHEMA)
    owner = ident(ENTITY_OWNER_ROLE)
    conn.exec_driver_sql(
        f"CREATE SCHEMA IF NOT EXISTS {schema} AUTHORIZATION {owner}"
    )
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
    row = conn.execute(
        text(
            f"SELECT entity_id, recording, retention_days, applied_version_id "
            f"FROM {_effective_table()} WHERE entity_id = :entity_id"
        ),
        {"entity_id": entity_id},
    ).mappings().one_or_none()
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
    conn.exec_driver_sql(
        f"CREATE SEQUENCE IF NOT EXISTS {_sequence_name(entity_id)}"
    )
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
                f"DROP TRIGGER IF EXISTS {ident(f'change_log_{suffix}')} "
                f"ON {relation}"
            )


def delete_entries(conn: Connection, entity_id: str) -> None:
    """Delete every entry of this entity. Does not restart its sequence."""
    entity_id = _entity_id(entity_id)
    conn.execute(
        text(f"DELETE FROM {_entry_table()} WHERE entity_id = :entity_id"),
        {"entity_id": entity_id},
    )


def delete_entries_before(
    conn: Connection, entity_id: str, cutoff: datetime
) -> None:
    """Delete entries whose transaction timestamp is strictly earlier than cutoff."""
    entity_id = _entity_id(entity_id)
    if not isinstance(cutoff, datetime) or cutoff.tzinfo is None:
        raise ValueError("cutoff must be an aware timestamp")
    conn.execute(
        text(
            f"DELETE FROM {_entry_table()} "
            "WHERE entity_id = :entity_id AND occurred_at < :cutoff"
        ),
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
    entries: list[ChangeLogEntry] = []
    for row in rows:
        before_raw, after_raw = _rebuild(str(row["operation"]), _image_dict(row["image"]))
        entries.append(
            ChangeLogEntry(
                entity_id=str(row["entity_id"]),
                physical_table=str(row["physical_table"]),
                operation=str(row["operation"]),
                sequence=int(row["seq"]),
                occurred_at=row["occurred_at"],
                source=None if row["source"] is None else str(row["source"]),
                subject=None if row["subject"] is None else str(row["subject"]),
                before=_decode_image(conn, before_raw, attributes, target),
                after=_decode_image(conn, after_raw, attributes, target),
            )
        )
    return entries


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
    rows = conn.execute(
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
    items = [_entry_from_row(conn, row, tables) for row in rows]
    next_before = (
        items[-1].sequence if len(items) == CHANGE_LOG_PAGE_LIMIT else None
    )
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
    row = conn.execute(
        text(
            "SELECT entity_id, physical_table, operation, seq, occurred_at, "
            "source, subject, image "
            f"FROM {_entry_table()} "
            "WHERE entity_id = :entity_id AND seq = :seq"
        ),
        {"entity_id": entity_id, "seq": sequence},
    ).mappings().one_or_none()
    if row is None:
        return None
    return _entry_from_row(conn, row, tables)


def _entry_from_row(
    conn: Connection,
    row: Mapping[str, Any],
    tables: Sequence[ChangeLogTable],
) -> ChangeLogEntry:
    physical = str(row["physical_table"])
    target = _target_for(physical, tables)
    before_raw, after_raw = _rebuild(str(row["operation"]), _image_dict(row["image"]))
    return ChangeLogEntry(
        entity_id=str(row["entity_id"]),
        physical_table=physical,
        operation=str(row["operation"]),
        sequence=int(row["seq"]),
        occurred_at=row["occurred_at"],
        source=None if row["source"] is None else str(row["source"]),
        subject=None if row["subject"] is None else str(row["subject"]),
        before=_decode_image(conn, before_raw, target.attributes, target),
        after=_decode_image(conn, after_raw, target.attributes, target),
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
        "PRIMARY KEY (entity_id, seq), "
        "CONSTRAINT change_log_operation "
        "CHECK (operation IN ('insert', 'update', 'delete')), "
        "CONSTRAINT change_log_source "
        "CHECK (source IS NULL OR source IN ('user', 'channel_run')), "
        "CONSTRAINT change_log_unattributed "
        "CHECK (source IS NOT NULL OR subject IS NULL)"
        ")"
    )
    changed = qualified_table(CHANGE_LOG_SCHEMA, _CHANGED_FUNCTION)
    append = qualified_table(CHANGE_LOG_SCHEMA, _APPEND_FUNCTION)
    conn.exec_driver_sql(_changed_columns_sql(changed))
    conn.exec_driver_sql(_append_change_sql(append, changed))
    conn.exec_driver_sql(f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC")
    conn.exec_driver_sql(
        f"REVOKE ALL ON TABLE {_effective_table()}, {_entry_table()} FROM PUBLIC"
    )
    conn.exec_driver_sql(
        f"REVOKE ALL ON FUNCTION {changed}(jsonb, jsonb), {append}() FROM PUBLIC"
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
      entity_id, physical_table, operation, seq, occurred_at, source, subject, image
    )
    SELECT ent, qualified, 'insert',
           nextval(format('{CHANGE_LOG_SCHEMA}.%%I', 'seq_' || ent)::regclass),
           transaction_timestamp(), src, subj,
           jsonb_build_object('after', to_jsonb(n))
    FROM new_rows AS n;
  ELSIF TG_OP = 'DELETE' THEN
    INSERT INTO {entry} (
      entity_id, physical_table, operation, seq, occurred_at, source, subject, image
    )
    SELECT ent, qualified, 'delete',
           nextval(format('{CHANGE_LOG_SCHEMA}.%%I', 'seq_' || ent)::regclass),
           transaction_timestamp(), src, subj,
           jsonb_build_object('before', to_jsonb(o))
    FROM old_rows AS o;
  ELSIF TG_OP = 'UPDATE' THEN
    INSERT INTO {entry} (
      entity_id, physical_table, operation, seq, occurred_at, source, subject, image
    )
    SELECT ent, qualified, 'update',
           nextval(format('{CHANGE_LOG_SCHEMA}.%%I', 'seq_' || ent)::regclass),
           transaction_timestamp(), src, subj,
           jsonb_build_object(
             'after', to_jsonb(n),
             'changed', {changed}(to_jsonb(o), to_jsonb(n))
           )
    FROM new_rows AS n
    JOIN old_rows AS o ON o.row_id = n.row_id
    WHERE to_jsonb(o) IS DISTINCT FROM to_jsonb(n);
  END IF;
  RETURN NULL;
END
$body$
"""


def _effective_table() -> str:
    return qualified_table(CHANGE_LOG_SCHEMA, EFFECTIVE_TABLE)


def _entry_table() -> str:
    return qualified_table(CHANGE_LOG_SCHEMA, ENTRY_TABLE)


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
    selects = [
        "CAST((CAST(:img AS jsonb) ->> 'row_id') AS bigint) AS row_id"
    ]
    for index, attr in enumerate(attributes):
        key = f"k{index}"
        params[key] = attr.name
        physical = _physical_cast(attr, target)
        selects.append(
            f"CAST((CAST(:img AS jsonb) ->> :{key}) AS {physical}) "
            f"AS {ident(attr.name)}"
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
        raise ValueError(
            "retention_days must be null or a whole number of days >= 1"
        )
    return value


def _applied_version_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("applied_version_id must be a string or null")
    return value
