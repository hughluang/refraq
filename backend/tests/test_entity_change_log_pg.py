"""Change log entries on a bootstrapped entity database.

Writes are direct statements on an armed physical table. Reads go through
the change-log functions. The trigger body is not the assertion surface.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError

from backend.core.config import reset_settings_cache
from backend.entity.change_log import (
    CHANGE_LOG_SCHEMA,
    ENTRY_TABLE,
    SOURCE_CHANNEL_RUN,
    SOURCE_GUC,
    SOURCE_USER,
    SUBJECT_GUC,
    ChangeLogEffective,
    ChangeLogEntry,
    delete_entries,
    delete_entries_before,
    ensure_shared_relations,
    install_triggers,
    list_entries,
    read_effective,
    remove_triggers,
    write_effective,
)
from backend.entity.ddl import ENTITY_DATA_SCHEMA, qualified_table
from backend.entity.entity_db import get_entity_engine, reset_entity_engine
from backend.entity.ids import new_entity_id
from backend.entity.records import AttributeRecord
from backend.entity.table_name import compose_physical_table_name
from backend.entity.table_port import PostgresEntityTablePort
from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)

_ATTRIBUTES = (
    AttributeRecord(
        name="sku",
        type="string",
        required=True,
        unique=True,
        max_length=32,
    ),
    AttributeRecord(name="qty", type="integer"),
    AttributeRecord(name="flag", type="boolean"),
    AttributeRecord(name="note", type="text"),
    AttributeRecord(name="amount", type="decimal", precision=10, scale=2),
    AttributeRecord(name="seen", type="timestamp"),
)

_INSERT_SQL = (
    "(sku, qty, flag, note, amount, seen) "
    "VALUES (:sku, :qty, :flag, :note, "
    "CAST(:amount AS numeric(10,2)), CAST(:seen AS timestamptz)) "
    "RETURNING row_id"
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def change_log_database():
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_clog") as urls:
        previous = os.environ.get("ENTITY_DATABASE_URL")
        os.environ["ENTITY_DATABASE_URL"] = urls.owner_url
        reset_settings_cache()
        reset_entity_engine()
        try:
            yield urls
        finally:
            reset_entity_engine()
            if previous is None:
                os.environ.pop("ENTITY_DATABASE_URL", None)
            else:
                os.environ["ENTITY_DATABASE_URL"] = previous
            reset_settings_cache()


def _physical_table() -> str:
    stem = f"m{uuid.uuid4().hex[:10]}"
    version_id = uuid.uuid4().hex[:16]
    name, _comment = compose_physical_table_name(stem, 1, version_id)
    return name


def _relation(table: str) -> str:
    return qualified_table(ENTITY_DATA_SCHEMA, table)


def _create_table(table: str) -> None:
    PostgresEntityTablePort().create_physical_table(
        ENTITY_DATA_SCHEMA, table, list(_ATTRIBUTES)
    )


def _values(sku: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "sku": sku,
        "qty": 1,
        "flag": True,
        "note": None,
        "amount": "12.50",
        "seen": "2020-01-02T03:04:05Z",
    }
    values.update(overrides)
    return values


def _image(row_id: int, **overrides: object) -> dict[str, object]:
    image: dict[str, object] = {
        "row_id": row_id,
        "sku": "a",
        "qty": 1,
        "flag": True,
        "note": None,
        "amount": "12.50",
        "seen": "2020-01-02T03:04:05Z",
    }
    image.update(overrides)
    return image


def _insert(conn: Connection, table: str, sku: str, **overrides: object) -> int:
    row_id = conn.execute(
        text(f"INSERT INTO {_relation(table)} {_INSERT_SQL}"),
        _values(sku, **overrides),
    ).scalar_one()
    return int(row_id)


def _row_count(conn: Connection, table: str) -> int:
    count = conn.execute(
        text(f"SELECT count(*) FROM {_relation(table)}")
    ).scalar_one()
    return int(count)


def _entries(conn: Connection, entity_id: str) -> list[ChangeLogEntry]:
    return list_entries(conn, entity_id, _ATTRIBUTES)


def _arm(
    engine: Engine,
    *,
    recording: bool | None = True,
    retention_days: int | None = None,
    applied_version_id: str | None = None,
    tables: Sequence[str] | None = None,
) -> tuple[str, list[str]]:
    entity_id = new_entity_id()
    created = list(tables) if tables is not None else [_physical_table()]
    for table in created:
        _create_table(table)
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        if recording is not None:
            write_effective(
                conn,
                ChangeLogEffective(
                    entity_id=entity_id,
                    recording=recording,
                    retention_days=retention_days,
                    applied_version_id=applied_version_id,
                ),
            )
        install_triggers(conn, entity_id, created)
    return entity_id, created


def _set_source(conn: Connection, source: str, subject: str | None) -> None:
    conn.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": SOURCE_GUC, "value": source},
    )
    if subject is not None:
        conn.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": SUBJECT_GUC, "value": subject},
        )


def test_insert_appends_one_unattributed_entry(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    table = tables[0]
    with engine.begin() as conn:
        row_id = _insert(conn, table, "a")
        occurred_at = conn.execute(text("SELECT transaction_timestamp()")).scalar_one()

    with engine.begin() as conn:
        entries = _entries(conn, entity_id)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.operation == "insert"
    assert entry.sequence == 1
    assert entry.occurred_at == occurred_at
    assert entry.physical_table == _relation(table)
    assert entry.source is None
    assert entry.subject is None
    assert entry.before is None
    assert entry.after == _image(row_id)


def test_update_rebuilds_before_and_stores_only_the_diff(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    table = tables[0]
    with engine.begin() as conn:
        row_id = _insert(conn, table, "a")
        conn.execute(
            text(
                f"UPDATE {_relation(table)} SET "
                "qty = NULL, flag = false, note = 'x' "
                "WHERE row_id = :row_id"
            ),
            {"row_id": row_id},
        )

    with engine.begin() as conn:
        entries = _entries(conn, entity_id)
        stored = conn.execute(
            text(
                f"SELECT image FROM {qualified_table(CHANGE_LOG_SCHEMA, ENTRY_TABLE)} "
                "WHERE entity_id = :entity_id AND operation = 'update'"
            ),
            {"entity_id": entity_id},
        ).scalar_one()

    assert [entry.operation for entry in entries] == ["update", "insert"]
    updated = entries[0]
    assert updated.before == _image(row_id)
    assert updated.after == _image(row_id, qty=None, flag=False, note="x")
    assert set(stored["changed"]) == {"qty", "flag", "note"}
    assert stored["changed"]["qty"] == 1
    assert stored["changed"]["flag"] is True
    assert stored["changed"]["note"] is None
    assert "sku" not in stored["changed"]
    assert "amount" not in stored["changed"]
    assert "seen" not in stored["changed"]
    assert "row_id" not in stored["changed"]


def test_equal_update_appends_nothing(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    table = tables[0]
    with engine.begin() as conn:
        row_id = _insert(conn, table, "a")
        conn.execute(
            text(
                f"UPDATE {_relation(table)} SET "
                "sku = sku, qty = qty, flag = flag, note = note, "
                "amount = amount, seen = seen "
                "WHERE row_id = :row_id"
            ),
            {"row_id": row_id},
        )
        conn.execute(
            text(
                f"UPDATE {_relation(table)} SET qty = CASE "
                "WHEN sku = 'a' THEN qty ELSE qty END"
            )
        )

    with engine.begin() as conn:
        entries = _entries(conn, entity_id)
        assert _row_count(conn, table) == 1

    assert len(entries) == 1
    assert entries[0].operation == "insert"


def test_statement_logs_only_rows_whose_values_differ(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    table = tables[0]
    with engine.begin() as conn:
        kept = _insert(conn, table, "keep")
        changed = _insert(conn, table, "move")
        occurred_at = conn.execute(text("SELECT transaction_timestamp()")).scalar_one()
        conn.execute(
            text(
                f"UPDATE {_relation(table)} SET qty = CASE "
                "WHEN sku = 'move' THEN 9 ELSE qty END"
            )
        )

    with engine.begin() as conn:
        entries = _entries(conn, entity_id)

    assert [entry.operation for entry in entries] == ["update", "insert", "insert"]
    assert entries[0].before == _image(changed, sku="move")
    assert entries[0].after == _image(changed, sku="move", qty=9)
    assert entries[1].occurred_at == entries[2].occurred_at == occurred_at
    assert {entry.after["row_id"] for entry in entries if entry.operation == "insert"} == {
        kept,
        changed,
    }
    assert entries[0].sequence == entries[1].sequence + 1


def test_delete_stores_full_before_and_no_after(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    table = tables[0]
    with engine.begin() as conn:
        row_id = _insert(conn, table, "a")
        conn.execute(
            text(f"DELETE FROM {_relation(table)} WHERE row_id = :row_id"),
            {"row_id": row_id},
        )

    with engine.begin() as conn:
        entries = _entries(conn, entity_id)
        assert _row_count(conn, table) == 0

    assert entries[0].operation == "delete"
    assert entries[0].before == _image(row_id)
    assert entries[0].after is None
    assert entries[0].source is None
    assert entries[0].subject is None


def test_rollback_leaves_no_entry_and_consumes_the_sequence(
    change_log_database,
) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    table = tables[0]
    with engine.begin() as conn:
        _insert(conn, table, "kept")

    with engine.connect() as conn:
        transaction = conn.begin()
        _insert(conn, table, "rolled")
        transaction.rollback()

    with engine.begin() as conn:
        third = _insert(conn, table, "next")

    with engine.begin() as conn:
        entries = _entries(conn, entity_id)
        assert _row_count(conn, table) == 2

    assert [entry.sequence for entry in entries] == [3, 1]
    assert entries[0].after["row_id"] == third
    assert entries[0].after["sku"] == "next"
    assert all(entry.after["sku"] != "rolled" for entry in entries)


def test_deleting_entries_does_not_restart_the_sequence(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    other_id, other_tables = _arm(engine)
    table = tables[0]
    with engine.begin() as conn:
        _insert(conn, table, "a")
        _insert(conn, other_tables[0], "other")
        delete_entries(conn, entity_id)
        row_id = _insert(conn, table, "b")

    with engine.begin() as conn:
        entries = _entries(conn, entity_id)
        other = _entries(conn, other_id)

    assert [entry.sequence for entry in entries] == [2]
    assert entries[0].after["row_id"] == row_id
    assert entries[0].after["sku"] == "b"
    assert [entry.sequence for entry in other] == [1]


def test_delete_entries_before_keeps_the_cutoff_instant(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    other_id, other_tables = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, tables[0], "old")
    with engine.begin() as conn:
        _insert(conn, tables[0], "new")
        _insert(conn, other_tables[0], "other")

    with engine.begin() as conn:
        entries = _entries(conn, entity_id)
        later = entries[0].occurred_at
        earlier = entries[1].occurred_at
        delete_entries_before(conn, entity_id, earlier)
        assert [entry.sequence for entry in _entries(conn, entity_id)] == [
            entries[0].sequence,
            entries[1].sequence,
        ]
        delete_entries_before(conn, entity_id, later)

    with engine.begin() as conn:
        remaining = _entries(conn, entity_id)
        other = _entries(conn, other_id)

    assert [entry.sequence for entry in remaining] == [entries[0].sequence]
    assert remaining[0].after["sku"] == "new"
    assert [entry.after["sku"] for entry in other] == ["other"]


def test_recording_off_or_missing_appends_nothing(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    off_id, off_tables = _arm(engine, recording=False)
    missing_id, missing_tables = _arm(engine, recording=None)
    with engine.begin() as conn:
        _insert(conn, off_tables[0], "off")
        _insert(conn, missing_tables[0], "missing")

    with engine.begin() as conn:
        assert _row_count(conn, off_tables[0]) == 1
        assert _row_count(conn, missing_tables[0]) == 1
        assert _entries(conn, off_id) == []
        assert _entries(conn, missing_id) == []
        assert read_effective(conn, missing_id) is None
        assert read_effective(conn, off_id) == ChangeLogEffective(
            entity_id=off_id,
            recording=False,
            retention_days=None,
            applied_version_id=None,
        )


def test_arming_does_not_invent_entries_for_stored_rows(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    table = _physical_table()
    _create_table(table)
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert(conn, table, "already")
        write_effective(
            conn,
            ChangeLogEffective(
                entity_id=entity_id,
                recording=True,
                retention_days=7,
                applied_version_id="ver_0123456789abcd",
            ),
        )
        install_triggers(conn, entity_id, [table])
        assert _entries(conn, entity_id) == []
        row_id = _insert(conn, table, "after")

    with engine.begin() as conn:
        stored = read_effective(conn, entity_id)
        entries = _entries(conn, entity_id)

    assert stored == ChangeLogEffective(
        entity_id=entity_id,
        recording=True,
        retention_days=7,
        applied_version_id="ver_0123456789abcd",
    )
    assert len(entries) == 1
    assert entries[0].after["row_id"] == row_id
    assert entries[0].after["sku"] == "after"


def test_failed_append_leaves_the_table_unchanged(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    table = tables[0]
    sequence = qualified_table(CHANGE_LOG_SCHEMA, f"seq_{entity_id}")
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.exec_driver_sql(f"DROP SEQUENCE {sequence}")
            _insert(conn, table, "nope")

    with engine.begin() as conn:
        assert _row_count(conn, table) == 0
        assert _entries(conn, entity_id) == []
        row_id = _insert(conn, table, "later")

    with engine.begin() as conn:
        entries = _entries(conn, entity_id)

    assert len(entries) == 1
    assert entries[0].after["row_id"] == row_id
    assert entries[0].sequence == 1


def test_two_physical_tables_share_one_log(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    first = _physical_table()
    second = _physical_table()
    entity_id, tables = _arm(engine, tables=[first, second])
    with engine.begin() as conn:
        left = _insert(conn, tables[0], "left")
        right = _insert(conn, tables[1], "right")

    with engine.begin() as conn:
        entries = _entries(conn, entity_id)

    assert [entry.sequence for entry in entries] == [2, 1]
    assert entries[0].physical_table == _relation(tables[1])
    assert entries[1].physical_table == _relation(tables[0])
    assert entries[0].after["row_id"] == right
    assert entries[1].after["row_id"] == left
    assert entries[0].occurred_at == entries[1].occurred_at


def test_unknown_source_is_unattributed_and_known_sources_keep_the_subject(
    change_log_database,
) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    table = tables[0]
    with engine.begin() as conn:
        _set_source(conn, "sql", "should-drop")
        _insert(conn, table, "plain")
    with engine.begin() as conn:
        _set_source(conn, "", "should-drop")
        _insert(conn, table, "empty")
    with engine.begin() as conn:
        _set_source(conn, SOURCE_USER, "usr_1")
        _insert(conn, table, "person")
    with engine.begin() as conn:
        _set_source(conn, SOURCE_CHANNEL_RUN, "run_1")
        _insert(conn, table, "run")

    with engine.begin() as conn:
        by_sku = {entry.after["sku"]: entry for entry in _entries(conn, entity_id)}

    assert by_sku["plain"].source is None
    assert by_sku["plain"].subject is None
    assert by_sku["empty"].source is None
    assert by_sku["empty"].subject is None
    assert by_sku["person"].source == SOURCE_USER
    assert by_sku["person"].subject == "usr_1"
    assert by_sku["run"].source == SOURCE_CHANNEL_RUN
    assert by_sku["run"].subject == "run_1"


def test_removed_triggers_stop_appending(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id, tables = _arm(engine)
    table = tables[0]
    with engine.begin() as conn:
        remove_triggers(conn, entity_id, [table])
        _insert(conn, table, "quiet")

    with engine.begin() as conn:
        assert _row_count(conn, table) == 1
        assert _entries(conn, entity_id) == []


def test_effective_write_does_not_commit(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    with pytest.raises(RuntimeError):
        with engine.begin() as conn:
            ensure_shared_relations(conn)
            write_effective(
                conn,
                ChangeLogEffective(
                    entity_id=entity_id,
                    recording=True,
                    retention_days=3,
                    applied_version_id=None,
                ),
            )
            raise RuntimeError("stop")

    with engine.begin() as conn:
        assert read_effective(conn, entity_id) is None
