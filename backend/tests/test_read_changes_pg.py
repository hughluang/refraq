"""Forward change-log reads and the Read Changes node, on Postgres."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from backend.channel.checkpoints import CheckpointPosition
from backend.channel.nodes.read.changes import NODE_TYPE
from backend.core.config import reset_settings_cache
from backend.core.time import utc_now
from backend.entity.change_log import (
    SOURCE_CHANNEL_RUN,
    SOURCE_GUC,
    SUBJECT_GUC,
    ChangeLogEffective,
    ChangeLogTable,
    delete_entries,
    delete_entries_before,
    ensure_shared_relations,
    install_triggers,
    read_change_log,
    read_entries_after,
    read_purge_mark,
    write_effective,
)
from backend.entity.changes import capture_bound, purge_mark, read_changes, recording_enabled
from backend.entity.service import live_change_log
from backend.entity.ddl import ENTITY_DATA_SCHEMA, qualified_table
from backend.entity.entity_db import get_entity_engine, reset_entity_engine
from backend.entity.ids import new_entity_id
from backend.entity.lifecycle import PUBLISHED
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
)
from backend.entity.store import get_entity_store
from backend.entity.table_name import compose_physical_table_name
from backend.entity.table_port import (
    PostgresEntityTablePort,
    bind_entity_table_port,
    reset_entity_table_port,
)
from backend.tests.channel_hooks_fake import FakeHooks
from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)

_SKU = AttributeRecord(
    name="sku",
    type="string",
    required=True,
    unique=True,
    business_key=True,
    max_length=32,
)
_QTY = AttributeRecord(name="qty", type="integer")


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
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_rchg") as urls:
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


def _relation(table: str) -> str:
    return qualified_table(ENTITY_DATA_SCHEMA, table)


def _create_table(table: str) -> None:
    PostgresEntityTablePort().create_physical_table(
        ENTITY_DATA_SCHEMA, table, [_SKU, _QTY]
    )


def _insert(conn: Connection, table: str, sku: str) -> int:
    row_id = conn.execute(
        text(f"INSERT INTO {_relation(table)} (sku) VALUES (:sku) RETURNING row_id"),
        {"sku": sku},
    ).scalar_one()
    return int(row_id)


def _update_qty(conn: Connection, table: str, sku: str, qty: int) -> None:
    conn.execute(
        text(f"UPDATE {_relation(table)} SET qty = :qty WHERE sku = :sku"),
        {"sku": sku, "qty": qty},
    )


def _delete(conn: Connection, table: str, sku: str) -> None:
    conn.execute(
        text(f"DELETE FROM {_relation(table)} WHERE sku = :sku"),
        {"sku": sku},
    )


def _arm(engine: Engine, *, recording: bool = True) -> tuple[str, str]:
    entity_id = new_entity_id()
    version_id = uuid.uuid4().hex[:16]
    stem = f"m{uuid.uuid4().hex[:8]}"
    table, _comment = compose_physical_table_name(stem, 1, version_id)
    _create_table(table)
    now = datetime.now(timezone.utc)
    get_entity_store().create_entity(
        BusinessEntityRecord(
            id=entity_id,
            table_name=stem,
            name="Orders",
            description="",
            deprecated_at=None,
            created_at=now,
            updated_at=now,
        ),
        EntityVersionRecord(
            id=version_id,
            entity_id=entity_id,
            version=1,
            attributes=[_SKU, _QTY],
            materialized_attributes=[],
            publish_status=PUBLISHED,
            latest_reconcile_job_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        write_effective(
            conn,
            ChangeLogEffective(
                entity_id=entity_id,
                recording=recording,
                retention_days=None,
                applied_version_id=version_id,
            ),
        )
        install_triggers(conn, entity_id, [table])
    return entity_id, table


def _table(table: str) -> ChangeLogTable:
    return ChangeLogTable(
        physical_table=_relation(table),
        attributes=(_SKU, _QTY),
        reference_snapshots={},
        business_key="sku",
    )


def _positions(conn: Connection, entity_id: str) -> list[tuple[int, int, str]]:
    rows = conn.execute(
        text(
            "SELECT xact::text::bigint AS xact, seq, operation "
            "FROM entity_change_log.entry "
            "WHERE entity_id = :entity_id ORDER BY xact, seq"
        ),
        {"entity_id": entity_id},
    )
    return [(int(xact), int(seq), str(operation)) for xact, seq, operation in rows]


def _read(conn: Connection, entity_id: str, table: str, bound: int):
    return read_entries_after(
        conn,
        entity_id,
        [_table(table)],
        after_xact=None,
        after_seq=None,
        bound_xact=bound,
        limit=100,
    )


def test_an_open_transaction_hides_later_committed_rows_until_it_ends(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    held = engine.connect()
    held_tx = held.begin()
    try:
        _insert(held, table, "early")
        with engine.begin() as conn:
            _insert(conn, table, "later")
        bound = capture_bound()
        with engine.begin() as conn:
            page, has_more = _read(conn, entity_id, table, bound)
        assert page == []
        assert has_more is False
        held_tx.commit()
    finally:
        held.close()
    bound = capture_bound()
    with engine.begin() as conn:
        page, _has_more = _read(conn, entity_id, table, bound)
    keys = [entry.after["sku"] for entry, _xact in page]
    assert keys == ["early", "later"]
    positions = [(xact, entry.sequence) for entry, xact in page]
    assert positions == sorted(positions)


def test_an_open_write_does_not_block_the_checkpoint_read(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    bind_entity_table_port(PostgresEntityTablePort())
    held = engine.connect()
    held_tx = held.begin()
    try:
        _insert(held, table, "early")
        with engine.begin() as conn:
            _insert(conn, table, "later")
        assert recording_enabled(entity_id) is True
        assert purge_mark(entity_id) is None
        assert live_change_log(entity_id) == (True, None)
        bound = capture_bound()
        hidden = read_changes(entity_id, after=None, bound=bound, limit=100)
        assert hidden.entries == []
        assert hidden.has_more is False
        result = NODE_TYPE.execute(_node(entity_id), _hooks(bound))
        assert result.status == "succeeded"
        assert result.output["count"] == 0
        with engine.begin() as conn:
            listed = read_change_log(conn, entity_id, [_table(table)])
        assert [item.after["sku"] for item in listed.items] == ["later"]
        held_tx.commit()
    finally:
        held.close()
        reset_entity_table_port()
    bound = capture_bound()
    visible = read_changes(entity_id, after=None, bound=bound, limit=100)
    assert [entry.after["sku"] for entry in visible.entries] == ["early", "later"]


def test_a_rolled_back_sequence_does_not_block_the_next_read(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    held = engine.connect()
    held_tx = held.begin()
    try:
        _insert(held, table, "gone")
        held_tx.rollback()
    finally:
        held.close()
    with engine.begin() as conn:
        _insert(conn, table, "kept")
    bound = capture_bound()
    with engine.begin() as conn:
        page, _has_more = _read(conn, entity_id, table, bound)
    assert [entry.after["sku"] for entry, _xact in page] == ["kept"]


def test_purge_mark_records_the_greatest_deleted_position(change_log_database) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "old")
    with engine.begin() as conn:
        _insert(conn, table, "new")
        positions = _positions(conn, entity_id)
    assert len(positions) == 2
    with engine.begin() as conn:
        delete_entries_before(conn, entity_id, utc_now() - timedelta(days=1))
        assert read_purge_mark(conn, entity_id) is None
        delete_entries(conn, entity_id)
        assert read_purge_mark(conn, entity_id) == (positions[-1][0], positions[-1][1])
        delete_entries_before(conn, entity_id, utc_now() + timedelta(days=1))
        assert read_purge_mark(conn, entity_id) == (positions[-1][0], positions[-1][1])


def _node(entity_id: str, **config: object) -> dict[str, object]:
    body = {"entity_id": entity_id, "limit": 1000, "shape": "entries"}
    body.update(config)
    return {"id": "nd_read", "type": "read.changes", "config": body}


def _hooks(bound: int) -> FakeHooks:
    hooks = FakeHooks(run_id="run_1", channel_id="chn_1")
    hooks.checkpoints.bound_value = bound
    return hooks


def test_read_changes_pages_and_folds_one_execution(change_log_database) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "SO001")
        _update_qty(conn, table, "SO001", 2)
        _insert(conn, table, "SO002")
        _delete(conn, table, "SO002")
    bound = capture_bound()
    hooks = _hooks(bound)
    first = NODE_TYPE.execute(_node(entity_id, limit=1), hooks)
    assert first.status == "succeeded"
    assert first.output["has_more"] is True
    assert first.output["count"] == 1
    assert first.output["entries"][0]["operation"] == "insert"
    assert first.output["entries"][0]["business_key"] == "SO001"
    second = NODE_TYPE.execute(_node(entity_id, limit=10), hooks)
    assert second.output["has_more"] is False
    assert [item["operation"] for item in second.output["entries"]] == [
        "update",
        "insert",
        "delete",
    ]
    net = NODE_TYPE.execute(_node(entity_id, shape="net", limit=10), hooks)
    # The same hooks already proposed past the page, so this execution sees nothing.
    assert net.output["entries"] == []
    fresh = _hooks(bound)
    folded = NODE_TYPE.execute(_node(entity_id, shape="net"), fresh)
    assert folded.status == "succeeded"
    assert folded.output["count"] == 1
    assert folded.output["entries"][0]["operation"] == "insert"
    assert folded.output["entries"][0]["business_key"] == "SO001"
    assert folded.output["entries"][0]["after"]["qty"] == 2
    assert folded.output["entries"][0]["before"] is None
    assert "first_sequence" in folded.output["entries"][0]


def test_source_filter_hides_rows_without_leaving_them_behind(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "user-row")
        conn.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": SOURCE_GUC, "value": SOURCE_CHANNEL_RUN},
        )
        conn.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": SUBJECT_GUC, "value": "run_9"},
        )
        _insert(conn, table, "channel-row")
    hooks = _hooks(capture_bound())
    result = NODE_TYPE.execute(
        _node(entity_id, sources=["channel_run"]),
        hooks,
    )
    assert result.status == "succeeded"
    assert [item["business_key"] for item in result.output["entries"]] == [
        "channel-row"
    ]
    assert result.output["last_sequence"] == result.output["entries"][0]["sequence"]
    again = NODE_TYPE.execute(_node(entity_id, sources=["channel_run"]), hooks)
    assert again.output["entries"] == []
    assert again.output["has_more"] is False


def test_recording_off_and_an_invalid_cursor(change_log_database) -> None:
    engine = get_entity_engine()
    quiet_id, _table = _arm(engine, recording=False)
    off = NODE_TYPE.execute(_node(quiet_id), _hooks(1))
    assert off.status == "failed"
    assert off.error_code == "CHANNEL_CHANGE_LOG_OFF"

    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "kept")
        _insert(conn, table, "dropped")
    with engine.begin() as conn:
        positions = _positions(conn, entity_id)
        delete_entries_before(conn, entity_id, utc_now() + timedelta(days=1))
    hooks = _hooks(capture_bound())
    hooks.checkpoints.durable_positions[("nd_read", entity_id)] = CheckpointPosition(
        xact=positions[0][0], seq=positions[0][1]
    )
    invalid = NODE_TYPE.execute(_node(entity_id), hooks)
    assert invalid.status == "failed"
    assert invalid.error_code == "CHANNEL_CHECKPOINT_INVALID"

    hooks.ignore_checkpoints = True
    recovered = NODE_TYPE.execute(_node(entity_id), hooks)
    assert recovered.status == "succeeded"
    assert recovered.output["entries"] == []
