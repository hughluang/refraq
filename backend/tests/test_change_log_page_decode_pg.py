"""One change-log page is decoded in one statement.

Values are the public read results. The statement count is how many
executions the read performs, not the text of those statements.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection

from backend.core.config import reset_settings_cache
from backend.entity.change_log import (
    SOURCE_CHANNEL_RUN,
    SOURCE_USER,
    ChangeLogTable,
    ensure_shared_relations,
    list_entries,
    read_change_log,
    read_entries_after,
)
from backend.entity.entity_db import get_entity_engine, reset_entity_engine
from backend.entity.ids import new_entity_id
from backend.entity.records import AttributeRecord
from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)

_INSERT_AT = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
_UPDATE_AT = datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)
_DELETE_AT = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)

_ATTRIBUTES = (
    AttributeRecord(name="label", type="string", max_length=32),
    AttributeRecord(name="note", type="text"),
    AttributeRecord(name="qty", type="integer"),
    AttributeRecord(name="amount", type="decimal", precision=10, scale=2),
    AttributeRecord(name="score", type="number"),
    AttributeRecord(name="flag", type="boolean"),
    AttributeRecord(name="day", type="date"),
    AttributeRecord(name="seen", type="timestamp"),
    AttributeRecord(name="clock", type="time"),
    AttributeRecord(name="payload", type="json"),
    AttributeRecord(name="status", type="dictionary", dictionary_id="dict_status"),
    AttributeRecord(name="owner", type="user"),
    AttributeRecord(
        name="supplier",
        type="reference",
        target_entity_id="ent_supplier",
    ),
    AttributeRecord(
        name="bin",
        type="reference",
        target_entity_id="ent_bin",
    ),
)

_ORIGINAL = {
    "row_id": 1,
    "label": "sku-1",
    "note": None,
    "qty": 7,
    "amount": "12.50",
    "score": 1.25,
    "flag": False,
    "day": "2020-03-04",
    "seen": "2020-01-02T03:04:05Z",
    "clock": "03:04:05",
    "payload": {"n": 1, "ok": False},
    "status": "open",
    "owner": "usr_01",
    "supplier": "ACME",
    "bin": 42,
}

_EDITED = {
    **_ORIGINAL,
    "qty": 8,
    "amount": "99.90",
    "flag": True,
}

# Stored images use the text a physical jsonb image yields. Decimal scale and
# the Z instant appear only after the column cast.
_STORED_ORIGINAL = {
    "row_id": 1,
    "label": "sku-1",
    "note": None,
    "qty": 7,
    "amount": 12.5,
    "score": 1.25,
    "flag": False,
    "day": "2020-03-04",
    "seen": "2020-01-02T03:04:05+00:00",
    "clock": "03:04:05",
    "payload": {"n": 1, "ok": False},
    "status": "open",
    "owner": "usr_01",
    "supplier": "ACME",
    "bin": 42,
}

_STORED_EDITED = {
    **_STORED_ORIGINAL,
    "qty": 8,
    "amount": 99.9,
    "flag": True,
}


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
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_clogd") as urls:
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


def _table(
    name: str,
    attributes: tuple[AttributeRecord, ...] = _ATTRIBUTES,
) -> ChangeLogTable:
    snapshots: dict[str, object] = {}
    if any(attr.name == "supplier" for attr in attributes):
        snapshots["supplier"] = {"type": "string", "max_length": 16}
    if any(attr.name == "bin" for attr in attributes):
        snapshots["bin"] = {"type": "integer"}
    return ChangeLogTable(
        physical_table=f'"entity_data"."{name}"',
        attributes=attributes,
        reference_snapshots=snapshots,
        business_key=None,
    )


def _insert_entry(
    conn: Connection,
    entity_id: str,
    *,
    sequence: int,
    physical: str,
    operation: str,
    image: dict[str, object],
    occurred_at: datetime,
    source: str | None = None,
    subject: str | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO entity_change_log.entry ("
            "entity_id, physical_table, operation, seq, occurred_at, "
            "source, subject, image"
            ") VALUES ("
            ":entity_id, :physical, :operation, :seq, :occurred_at, "
            ":source, :subject, CAST(:image AS jsonb)"
            ")"
        ),
        {
            "entity_id": entity_id,
            "physical": physical,
            "operation": operation,
            "seq": sequence,
            "occurred_at": occurred_at,
            "source": source,
            "subject": subject,
            "image": json.dumps(image),
        },
    )


def _execution_count(conn: Connection, call):
    count = 0

    def _on_execute(*_args: object) -> None:
        nonlocal count
        count += 1

    event.listen(conn, "before_cursor_execute", _on_execute)
    try:
        return call(), count
    finally:
        event.remove(conn, "before_cursor_execute", _on_execute)


def test_a_mixed_operation_page_decodes_every_attribute_with_one_statement(
    change_log_database,
) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    table = _table("widget__v1__decode0000000001")
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert_entry(
            conn,
            entity_id,
            sequence=1,
            physical=table.physical_table,
            operation="insert",
            image={"after": _STORED_ORIGINAL},
            occurred_at=_INSERT_AT,
            source=SOURCE_USER,
            subject="alice",
        )
        _insert_entry(
            conn,
            entity_id,
            sequence=2,
            physical=table.physical_table,
            operation="update",
            image={
                "after": _STORED_EDITED,
                "changed": {"qty": 7, "amount": 12.5, "flag": False},
            },
            occurred_at=_UPDATE_AT,
            source=SOURCE_CHANNEL_RUN,
            subject="run-1",
        )
        _insert_entry(
            conn,
            entity_id,
            sequence=3,
            physical=table.physical_table,
            operation="delete",
            image={"before": _STORED_EDITED},
            occurred_at=_DELETE_AT,
        )
        page, executions = _execution_count(
            conn, lambda: read_change_log(conn, entity_id, [table])
        )

    assert page.limit == 50
    assert page.next_before_sequence is None
    assert [item.sequence for item in page.items] == [3, 2, 1]
    deleted, updated, inserted = page.items

    assert deleted.operation == "delete"
    assert deleted.entity_id == entity_id
    assert deleted.physical_table == table.physical_table
    assert deleted.occurred_at == _DELETE_AT
    assert deleted.source is None
    assert deleted.subject is None
    assert deleted.before == _EDITED
    assert deleted.after is None

    assert updated.operation == "update"
    assert updated.occurred_at == _UPDATE_AT
    assert updated.source == SOURCE_CHANNEL_RUN
    assert updated.subject == "run-1"
    assert updated.before == _ORIGINAL
    assert updated.after == _EDITED
    assert updated.after["flag"] is True
    assert updated.before["flag"] is False

    assert inserted.operation == "insert"
    assert inserted.occurred_at == _INSERT_AT
    assert inserted.source == SOURCE_USER
    assert inserted.subject == "alice"
    assert inserted.before is None
    assert inserted.after == _ORIGINAL
    assert inserted.after["amount"] == "12.50"
    assert inserted.after["seen"] == "2020-01-02T03:04:05Z"
    assert executions == 2


_SKU_ATTRIBUTES = (
    AttributeRecord(name="code", type="string", max_length=32),
    AttributeRecord(name="amount", type="decimal", precision=10, scale=2),
    AttributeRecord(name="flag", type="boolean"),
)

_CODE_ATTRIBUTES = (
    AttributeRecord(name="code", type="integer"),
    AttributeRecord(
        name="bin",
        type="reference",
        target_entity_id="ent_bin",
    ),
)

_SKU_ROW = {"row_id": 1, "code": "ACME", "amount": "12.50", "flag": False}
_SKU_STORED = {"row_id": 1, "code": "ACME", "amount": 12.5, "flag": False}
_CODE_ROW = {"row_id": 4, "code": 9, "bin": 42}
_CODE_STORED = {"row_id": 4, "code": 9, "bin": 42}


def test_a_page_of_two_physical_tables_decodes_in_one_statement(
    change_log_database,
) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    sku = _table("sku__v1__decode0000000002", _SKU_ATTRIBUTES)
    code = _table("code__v1__decode0000000002", _CODE_ATTRIBUTES)
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert_entry(
            conn,
            entity_id,
            sequence=1,
            physical=sku.physical_table,
            operation="insert",
            image={"after": _SKU_STORED},
            occurred_at=_INSERT_AT,
        )
        _insert_entry(
            conn,
            entity_id,
            sequence=2,
            physical=code.physical_table,
            operation="update",
            image={
                "after": _CODE_STORED,
                "changed": {"code": 8},
            },
            occurred_at=_UPDATE_AT,
            source=SOURCE_USER,
            subject="alice",
        )
        _insert_entry(
            conn,
            entity_id,
            sequence=3,
            physical=sku.physical_table,
            operation="delete",
            image={"before": _SKU_STORED},
            occurred_at=_DELETE_AT,
        )
        page, executions = _execution_count(
            conn, lambda: read_change_log(conn, entity_id, [sku, code])
        )

    assert [item.sequence for item in page.items] == [3, 2, 1]
    deleted, updated, inserted = page.items
    assert deleted.physical_table == sku.physical_table
    assert deleted.before == _SKU_ROW
    assert deleted.after is None
    assert deleted.before["flag"] is False
    assert updated.physical_table == code.physical_table
    assert updated.source == SOURCE_USER
    assert updated.subject == "alice"
    assert updated.before == {"row_id": 4, "code": 8, "bin": 42}
    assert updated.after == _CODE_ROW
    assert inserted.physical_table == sku.physical_table
    assert inserted.before is None
    assert inserted.after == _SKU_ROW
    assert inserted.after["amount"] == "12.50"
    assert executions == 2


def test_list_entries_decodes_the_page_in_one_statement(change_log_database) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    table = _table("sku__v1__decode0000000003", _SKU_ATTRIBUTES)
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert_entry(
            conn,
            entity_id,
            sequence=1,
            physical=table.physical_table,
            operation="insert",
            image={"after": _SKU_STORED},
            occurred_at=_INSERT_AT,
            source=SOURCE_USER,
            subject="alice",
        )
        _insert_entry(
            conn,
            entity_id,
            sequence=2,
            physical=table.physical_table,
            operation="delete",
            image={"before": _SKU_STORED},
            occurred_at=_DELETE_AT,
        )
        entries, executions = _execution_count(
            conn, lambda: list_entries(conn, entity_id, _SKU_ATTRIBUTES)
        )

    assert [entry.sequence for entry in entries] == [2, 1]
    deleted, inserted = entries
    assert deleted.operation == "delete"
    assert deleted.before == _SKU_ROW
    assert deleted.after is None
    assert deleted.before["flag"] is False
    assert inserted.operation == "insert"
    assert inserted.before is None
    assert inserted.after == _SKU_ROW
    assert inserted.after["amount"] == "12.50"
    assert inserted.source == SOURCE_USER
    assert inserted.subject == "alice"
    assert inserted.occurred_at == _INSERT_AT
    assert executions == 2


def _bound(conn: Connection, entity_id: str) -> int:
    value = conn.execute(
        text(
            "SELECT COALESCE(MAX(commit_seq), 0) "
            "FROM entity_change_log.entry WHERE entity_id = :entity_id"
        ),
        {"entity_id": entity_id},
    ).scalar_one()
    return int(value)


def test_read_entries_after_decodes_a_mixed_page_in_one_statement(
    change_log_database,
) -> None:
    del change_log_database
    engine = get_entity_engine()
    entity_id = new_entity_id()
    sku = _table("sku__v1__decode0000000004", _SKU_ATTRIBUTES)
    code = _table("code__v1__decode0000000004", _CODE_ATTRIBUTES)
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        _insert_entry(
            conn,
            entity_id,
            sequence=1,
            physical=sku.physical_table,
            operation="insert",
            image={"after": _SKU_STORED},
            occurred_at=_INSERT_AT,
        )
        _insert_entry(
            conn,
            entity_id,
            sequence=2,
            physical=code.physical_table,
            operation="insert",
            image={"after": _CODE_STORED},
            occurred_at=_UPDATE_AT,
        )
        _insert_entry(
            conn,
            entity_id,
            sequence=3,
            physical=sku.physical_table,
            operation="delete",
            image={"before": _SKU_STORED},
            occurred_at=_DELETE_AT,
        )
    with engine.begin() as conn:
        bound = _bound(conn, entity_id)
        result, executions = _execution_count(
            conn,
            lambda: read_entries_after(
                conn,
                entity_id,
                [sku, code],
                after_commit=None,
                bound_commit=bound,
                limit=2,
            ),
        )
    page, has_more = result
    assert has_more is True
    assert [entry.sequence for entry, _xact in page] == [1, 2]
    first, second = page
    assert first[0].physical_table == sku.physical_table
    assert first[0].before is None
    assert first[0].after == _SKU_ROW
    assert first[0].after["flag"] is False
    assert first[0].after["amount"] == "12.50"
    assert second[0].physical_table == code.physical_table
    assert second[0].before is None
    assert second[0].after == _CODE_ROW
    assert first[1] < second[1]
    assert isinstance(first[1], int)
    with engine.begin() as conn:
        rest, rest_more = read_entries_after(
            conn,
            entity_id,
            [sku, code],
            after_commit=second[1],
            bound_commit=bound,
            limit=2,
        )
    assert rest_more is False
    assert [entry.sequence for entry, _xact in rest] == [3]
    assert rest[0][0].operation == "delete"
    assert rest[0][0].before == _SKU_ROW
    assert rest[0][0].after is None
    assert executions == 2
