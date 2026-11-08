"""Forward change-log reads and the Read Changes node, on Postgres."""

from __future__ import annotations

import os
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from backend.admin.system_parameters import is_registry_frozen, register_parameters
from backend.admin.user_store import SYSTEM_USER_ID, UserRecord
from backend.channel.checkpoints import CheckpointPosition
from backend.channel.nodes.read.changes import NODE_TYPE
from backend.core.config import reset_settings_cache
from backend.core.time import utc_now
from backend.entity.access.records import (
    GrantRecord,
    LadderRecord,
    ProfileRecord,
    RestrictionRecord,
)
from backend.entity.access.seed import ensure_system_grant
from backend.entity.access.store import get_access_store
from backend.entity.ids import (
    new_access_grant_id,
    new_access_profile_id,
    new_access_restriction_id,
)
from backend.entity.parameters import ENTITY_PARAMETER_SPECS
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
    map_legacy_cursor,
    read_change_log,
    read_entries_after,
    read_purge_mark,
    write_effective,
)
from backend.entity.changes import capture_bound, purge_mark, recording_enabled
from backend.entity.history.service import read_incremental
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
    attribute_id="att_sku",
)
_QTY = AttributeRecord(name="qty", type="integer", attribute_id="att_qty")
_PLAIN = AttributeRecord(
    name="sku",
    type="string",
    required=True,
    unique=True,
    max_length=32,
    attribute_id="att_sku",
)
_ITEM = AttributeRecord(
    name="item_code",
    type="string",
    required=True,
    unique=True,
    max_length=32,
    attribute_id="att_sku",
)
_QTY_KEY = AttributeRecord(
    name="qty",
    type="integer",
    business_key=True,
    attribute_id="att_qty",
)
_PARTIAL = {"type": "partial", "keep_first": 1, "keep_last": 1}


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
        if not is_registry_frozen():
            register_parameters(
                ENTITY_PARAMETER_SPECS, group_order=("entity_access", "entity")
            )
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


def _insert(conn: Connection, table: str, sku: str, qty: int | None = None) -> int:
    row_id = conn.execute(
        text(
            f"INSERT INTO {_relation(table)} (sku, qty) "
            "VALUES (:sku, :qty) RETURNING row_id"
        ),
        {"sku": sku, "qty": qty},
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


def _arm(
    engine: Engine,
    *,
    recording: bool = True,
    attributes: list[AttributeRecord] | None = None,
) -> tuple[str, str]:
    entity_id = new_entity_id()
    version_id = uuid.uuid4().hex[:16]
    stem = f"m{uuid.uuid4().hex[:8]}"
    attrs = list(attributes or [_SKU, _QTY])
    table, _comment = compose_physical_table_name(stem, 1, version_id)
    PostgresEntityTablePort().create_physical_table(ENTITY_DATA_SCHEMA, table, attrs)
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
            attributes=attrs,
            materialized_attributes=[],
            publish_status=PUBLISHED,
            latest_reconcile_job_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    ensure_system_grant(entity_id, attrs)
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
            "SELECT commit_seq, seq, operation "
            "FROM entity_change_log.entry "
            "WHERE entity_id = :entity_id AND commit_seq IS NOT NULL "
            "ORDER BY commit_seq"
        ),
        {"entity_id": entity_id},
    )
    return [
        (int(commit_seq), int(seq), str(operation))
        for commit_seq, seq, operation in rows
    ]


def _read(conn: Connection, entity_id: str, table: str, bound: int):
    return read_entries_after(
        conn,
        entity_id,
        [_table(table)],
        after_commit=None,
        bound_commit=bound,
        limit=100,
    )


def test_an_open_transaction_does_not_hide_later_committed_rows(
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
        bound = capture_bound(entity_id)
        with engine.begin() as conn:
            page, has_more = _read(conn, entity_id, table, bound)
        assert [entry.after["sku"] for entry, _commit in page] == ["later"]
        assert has_more is False
        held_tx.commit()
    finally:
        held.close()
    bound = capture_bound(entity_id)
    with engine.begin() as conn:
        page, _has_more = _read(conn, entity_id, table, bound)
    keys = [entry.after["sku"] for entry, _commit in page]
    assert keys == ["later", "early"]
    positions = [(commit, entry.sequence) for entry, commit in page]
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
        bound = capture_bound(entity_id)
        hidden = read_incremental(entity_id, after=None, bound=bound, limit=100)
        assert [entry.after.values["sku"] for entry in hidden.events] == ["later"]
        assert hidden.has_more is False
        result = NODE_TYPE.execute(_node(entity_id), _hooks(bound))
        assert result.status == "succeeded"
        assert result.output["count"] == 1
        with engine.begin() as conn:
            listed = read_change_log(conn, entity_id, [_table(table)])
        assert [item.after["sku"] for item in listed.items] == ["later"]
        held_tx.commit()
    finally:
        held.close()
        reset_entity_table_port()
    bound = capture_bound(entity_id)
    visible = read_incremental(entity_id, after=None, bound=bound, limit=100)
    assert [entry.after.values["sku"] for entry in visible.events] == ["later", "early"]


def test_a_rolled_back_sequence_does_not_block_the_next_read(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    held = engine.connect()
    held_tx = held.begin()
    try:
        _insert(held, table, "gone")
        held.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        held_tx.rollback()
    finally:
        held.close()
    with engine.begin() as conn:
        _insert(conn, table, "kept")
    bound = capture_bound(entity_id)
    with engine.begin() as conn:
        page, _has_more = _read(conn, entity_id, table, bound)
    assert [entry.after["sku"] for entry, commit in page] == ["kept"]
    assert page[0][1] == 1
    with engine.begin() as conn:
        _insert(conn, table, "after")
    bound = capture_bound(entity_id)
    with engine.begin() as conn:
        page, _has_more = _read(conn, entity_id, table, bound)
    commits = [commit for _entry, commit in page]
    assert [entry.after["sku"] for entry, _commit in page] == ["kept", "after"]
    assert commits[1] == commits[0] + 1


def test_an_open_xid_does_not_hide_a_committed_row(change_log_database) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    held = engine.connect()
    held_tx = held.begin()
    try:
        held.execute(text("SELECT pg_current_xact_id()"))
        with engine.begin() as conn:
            _insert(conn, table, "visible")
        page = read_incremental(
            entity_id, after=None, bound=capture_bound(entity_id), limit=100
        )
        assert [entry.after.values["sku"] for entry in page.events] == ["visible"]
        held_tx.rollback()
    finally:
        held.close()


def test_commit_sequences_are_per_entity(change_log_database) -> None:
    engine = get_entity_engine()
    left_id, left = _arm(engine)
    right_id, right = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, left, "left")
    with engine.begin() as conn:
        _insert(conn, right, "right")
    assert capture_bound(left_id) == 1
    assert capture_bound(right_id) == 1


def test_a_legacy_cursor_maps_onto_the_commit_sequence(change_log_database) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "old")
    with engine.begin() as conn:
        _insert(conn, table, "new")
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT xact::text::bigint, seq, commit_seq "
                "FROM entity_change_log.entry "
                "WHERE entity_id = :entity_id ORDER BY commit_seq"
            ),
            {"entity_id": entity_id},
        ).all()
        kept = map_legacy_cursor(conn, entity_id, int(rows[1][0]), int(rows[1][1]))
        assert kept == (int(rows[1][2]), int(rows[1][1]))
        delete_entries(conn, entity_id)
        behind = map_legacy_cursor(conn, entity_id, int(rows[0][0]), int(rows[0][1]))
        same = map_legacy_cursor(conn, entity_id, int(rows[1][0]), int(rows[1][1]))
        mark = read_purge_mark(conn, entity_id)
    assert mark == (int(rows[1][2]), int(rows[1][1]))
    assert same == mark
    assert behind < mark


def test_purge_mark_records_the_greatest_deleted_position(change_log_database) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "old")
    with engine.begin() as conn:
        _insert(conn, table, "new")
    with engine.begin() as conn:
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
        so001 = _insert(conn, table, "SO001")
        _update_qty(conn, table, "SO001", 2)
        _insert(conn, table, "SO002")
        _delete(conn, table, "SO002")
    bound = capture_bound(entity_id)
    hooks = _hooks(bound)
    hooks.user = UserRecord(
        id="usr_not_the_reader",
        account="outsider",
        display_name="Outsider",
        password_hash=None,
        role_id=None,
        status="active",
        identity_source="local",
    )
    first = NODE_TYPE.execute(_node(entity_id, limit=1), hooks)
    assert first.status == "succeeded"
    assert first.output["has_more"] is True
    assert first.output["count"] == 1
    opened = first.output["entries"][0]
    assert opened["operation"] == "insert"
    assert opened["before"] == {"state": "absent"}
    assert opened["after"]["state"] == "visible"
    assert opened["after"]["values"]["sku"] == "SO001"
    assert opened["after"]["values"]["row_id"] == so001
    assert opened["version_number"] == 1
    assert table in opened["physical_table"]
    assert "business_key" not in opened
    assert "row_id" not in opened
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
    assert net.output["last_sequence"] is None
    fresh = _hooks(bound)
    folded = NODE_TYPE.execute(_node(entity_id, shape="net"), fresh)
    assert folded.status == "succeeded"
    assert folded.output["count"] == 1
    kept = folded.output["entries"][0]
    assert kept["operation"] == "insert"
    assert kept["business_key"] == "SO001"
    assert kept["before"] == {"state": "absent"}
    assert kept["after"]["state"] == "visible"
    assert kept["after"]["values"]["sku"] == "SO001"
    assert kept["after"]["values"]["qty"] == 2
    assert kept["after"]["values"]["row_id"] == so001
    assert kept["first_sequence"] != kept["last_sequence"]
    again = NODE_TYPE.execute(_node(entity_id, shape="net"), fresh)
    assert again.output["entries"] == []
    assert again.output["last_sequence"] is None


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
    hooks = _hooks(capture_bound(entity_id))
    result = NODE_TYPE.execute(
        _node(entity_id, sources=["channel_run"]),
        hooks,
    )
    assert result.status == "succeeded"
    assert [
        item["after"]["values"]["sku"] for item in result.output["entries"]
    ] == ["channel-row"]
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
    hooks = _hooks(capture_bound(entity_id))
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
    assert recovered.output["last_sequence"] is None


def _restrict(
    entity_id: str,
    *,
    row_rule: dict[str, object] | None = None,
    deny_columns: list[str] | None = None,
) -> None:
    now = utc_now()
    store = get_access_store()
    store.insert_restriction(
        RestrictionRecord(
            id=new_access_restriction_id(),
            entity_id=entity_id,
            applies_to={"mode": "all"},
            row_rule=row_rule,
            deny_columns=list(deny_columns or []),
            ceilings=[],
            actions=["read"],
            created_at=now,
            updated_at=now,
        )
    )
    store.set_revision(entity_id, store.revision(entity_id) + 1)


def _mask_ladder(entity_id: str) -> None:
    now = utc_now()
    store = get_access_store()
    store.save_ladder(
        LadderRecord(
            entity_id=entity_id,
            attribute_id="att_sku",
            levels=[
                {"key": "clear", "mode": "clear"},
                {"key": "masked", "mode": _PARTIAL},
            ],
            updated_at=now,
        )
    )
    store.set_revision(entity_id, store.revision(entity_id) + 1)


def _system_row_rule(entity_id: str, row_rule: dict[str, object] | None) -> None:
    now = utc_now()
    store = get_access_store()
    for grant in store.grants(entity_id):
        if grant.subject_type == "user" and grant.subject_id == SYSTEM_USER_ID:
            store.update_grant(replace(grant, row_rule=row_rule, updated_at=now))
    store.set_revision(entity_id, store.revision(entity_id) + 1)


def _mask_grant(entity_id: str, row_rule: dict[str, object] | None) -> None:
    now = utc_now()
    store = get_access_store()
    profile_id = new_access_profile_id()
    store.insert_profile(
        ProfileRecord(
            id=profile_id,
            entity_id=entity_id,
            key="sku_masked",
            name="SKU masked",
            description=None,
            columns=[
                {"attribute_id": "att_sku", "level": "masked"},
                {"attribute_id": "att_qty", "level": "clear"},
            ],
            created_at=now,
            updated_at=now,
        )
    )
    store.insert_grant(
        GrantRecord(
            id=new_access_grant_id(),
            entity_id=entity_id,
            subject_type="user",
            subject_id=SYSTEM_USER_ID,
            profile_id=profile_id,
            row_rule=row_rule,
            actions=["read"],
            status="active",
            valid_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    store.set_revision(entity_id, store.revision(entity_id) + 1)


def _publish_successor(entity_id: str, attributes: list[AttributeRecord]) -> None:
    entity = get_entity_store().get_entity(entity_id)
    assert entity is not None
    version_id = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc)
    table, _comment = compose_physical_table_name(entity.table_name, 2, version_id)
    PostgresEntityTablePort().create_physical_table(ENTITY_DATA_SCHEMA, table, attributes)
    get_entity_store().create_version(
        EntityVersionRecord(
            id=version_id,
            entity_id=entity_id,
            version=2,
            attributes=attributes,
            materialized_attributes=[],
            publish_status=PUBLISHED,
            latest_reconcile_job_id=None,
            created_at=now,
            updated_at=now,
        )
    )
    ensure_system_grant(entity_id, attributes)


def test_an_unreadable_event_advances_without_becoming_output(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    _restrict(entity_id, row_rule={"eq": {"attr": "att_qty", "value": 9}})
    with engine.begin() as conn:
        _insert(conn, table, "hidden", qty=1)
        _insert(conn, table, "shown", qty=9)
    hooks = _hooks(capture_bound(entity_id))
    hidden = NODE_TYPE.execute(_node(entity_id, limit=1), hooks)
    assert hidden.status == "succeeded"
    assert hidden.output["entries"] == []
    assert hidden.output["count"] == 0
    assert hidden.output["has_more"] is True
    assert isinstance(hidden.output["last_sequence"], int)
    shown = NODE_TYPE.execute(_node(entity_id, limit=1), hooks)
    assert shown.output["count"] == 1
    assert shown.output["entries"][0]["after"]["values"]["sku"] == "shown"
    assert shown.output["entries"][0]["after"]["values"]["qty"] == 9
    assert shown.output["has_more"] is False


def test_an_equal_projected_update_is_still_emitted(change_log_database) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    _restrict(entity_id, deny_columns=["att_qty"])
    with engine.begin() as conn:
        _insert(conn, table, "EQ", qty=1)
        _update_qty(conn, table, "EQ", 5)
    result = NODE_TYPE.execute(_node(entity_id), _hooks(capture_bound(entity_id)))
    assert result.status == "succeeded"
    update = next(item for item in result.output["entries"] if item["operation"] == "update")
    assert update["before"]["state"] == "visible"
    assert update["after"]["state"] == "visible"
    assert update["before"]["values"] == update["after"]["values"]
    assert update["after"]["values"]["sku"] == "EQ"
    assert "qty" not in update["after"]["values"]


def test_net_grouping_fails_when_the_business_key_is_outside_the_shape(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    _restrict(entity_id, deny_columns=["att_sku"])
    with engine.begin() as conn:
        _insert(conn, table, "HIDDEN", qty=1)
    hooks = _hooks(capture_bound(entity_id))
    failed = NODE_TYPE.execute(_node(entity_id, shape="net"), hooks)
    assert failed.status == "failed"
    assert failed.error_code == "CHANNEL_CHANGE_LOG_GROUPING_UNSAFE"
    assert failed.error_message == "Net grouping has no clear projected identity."
    seen = NODE_TYPE.execute(_node(entity_id, shape="entries"), hooks)
    assert seen.status == "succeeded"
    assert seen.output["count"] == 1
    assert "sku" not in seen.output["entries"][0]["after"]["values"]


def test_net_grouping_uses_row_id_when_the_head_declares_no_business_key(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine, attributes=[_PLAIN, _QTY])
    with engine.begin() as conn:
        kept = _insert(conn, table, "KEEP")
        _update_qty(conn, table, "KEEP", 2)
        _insert(conn, table, "GONE")
        _delete(conn, table, "GONE")
    result = NODE_TYPE.execute(
        _node(entity_id, shape="net"),
        _hooks(capture_bound(entity_id)),
    )
    assert result.status == "succeeded"
    assert result.output["count"] == 1
    item = result.output["entries"][0]
    assert item["operation"] == "insert"
    assert item["business_key"] is None
    assert item["row_id"] == kept
    assert item["before"] == {"state": "absent"}
    assert item["after"]["values"]["sku"] == "KEEP"
    assert item["after"]["values"]["qty"] == 2
    assert item["after"]["values"]["row_id"] == kept


def test_net_grouping_fails_when_the_business_key_is_masked(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    _mask_ladder(entity_id)
    _system_row_rule(entity_id, {"eq": {"attr": "att_qty", "value": 9}})
    _mask_grant(entity_id, {"eq": {"attr": "att_qty", "value": 1}})
    with engine.begin() as conn:
        _insert(conn, table, "abcdef", qty=1)
    hooks = _hooks(capture_bound(entity_id))
    failed = NODE_TYPE.execute(_node(entity_id, shape="net"), hooks)
    assert failed.status == "failed"
    assert failed.error_code == "CHANNEL_CHANGE_LOG_GROUPING_UNSAFE"
    assert failed.error_message == "Net grouping has no clear projected identity."
    seen = NODE_TYPE.execute(_node(entity_id, shape="entries"), hooks)
    assert seen.status == "succeeded"
    assert seen.output["count"] == 1
    values = seen.output["entries"][0]["after"]["values"]
    assert values["sku"] == "a****f"
    assert set(values) <= {"row_id", "sku", "qty", "__withheld"}


def test_a_clear_grant_keeps_the_business_key_when_another_grant_masks(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    _mask_ladder(entity_id)
    _mask_grant(entity_id, None)
    with engine.begin() as conn:
        _insert(conn, table, "abcdef", qty=1)
    result = NODE_TYPE.execute(
        _node(entity_id, shape="net"),
        _hooks(capture_bound(entity_id)),
    )
    assert result.status == "succeeded"
    assert result.output["count"] == 1
    item = result.output["entries"][0]
    assert item["business_key"] == "abcdef"
    assert item["after"]["values"]["sku"] == "abcdef"


def test_net_grouping_uses_the_version_key_when_the_head_key_differs(
    change_log_database,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    _publish_successor(entity_id, [_ITEM, _QTY_KEY])
    with engine.begin() as conn:
        _insert(conn, table, "ALPHA", qty=1)
        _insert(conn, table, "BETA", qty=1)
    result = NODE_TYPE.execute(
        _node(entity_id, shape="net"),
        _hooks(capture_bound(entity_id)),
    )
    assert result.status == "succeeded"
    assert result.output["count"] == 2
    keys = {item["business_key"] for item in result.output["entries"]}
    assert keys == {"ALPHA", "BETA"}
    for item in result.output["entries"]:
        assert item["operation"] == "insert"
        assert item["after"]["values"]["item_code"] == item["business_key"]
        assert "sku" not in item["after"]["values"]
