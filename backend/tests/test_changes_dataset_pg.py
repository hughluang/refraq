"""Changes Dataset lands a bounded Change Log range on Postgres."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from backend.admin.user_store import get_user_store
from backend.channel.checkpoints import CheckpointPosition
from backend.channel.nodes.read.changes import NODE_TYPE as READ_CHANGES
from backend.channel.nodes.volume.changes_dataset import NODE_TYPE
from backend.core.config import reset_settings_cache
from backend.core.time import utc_now
from backend.entity.access.records import (
    GrantRecord,
    LadderRecord,
    ProfileRecord,
    RestrictionRecord,
)
from backend.entity.access.seed import ensure_creator_grant, ensure_system_grant
from backend.entity.access.store import get_access_store
from backend.entity.ids import (
    new_access_grant_id,
    new_access_profile_id,
    new_access_restriction_id,
)
from backend.entity.change_log import (
    SOURCE_GUC,
    SUBJECT_GUC,
    ChangeLogEffective,
    delete_entries,
    delete_entries_before,
    ensure_shared_relations,
    install_triggers,
    write_effective,
)
from backend.entity.changes import capture_bound
from backend.entity.history.service import read_incremental
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
from backend.entity.table_port import PostgresEntityTablePort
from backend.tests.channel_hooks_fake import FakeHooks
from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_NODE_ID = "nd_changes"
_COLUMNS = (
    "sequence",
    "operation",
    "occurred_at",
    "source",
    "subject",
    "physical_table",
    "version_id",
    "version_number",
    "row_id",
    "business_key",
    "before",
    "after",
)
_NORMALIZED = {
    "sequence": "integer",
    "operation": "string",
    "occurred_at": "string",
    "source": "string",
    "subject": "string",
    "physical_table": "string",
    "version_id": "string",
    "version_number": "integer",
    "row_id": "integer",
    "business_key": "json",
    "before": "json",
    "after": "json",
}
_PHYSICAL = {
    "sequence": "bigint",
    "operation": "text",
    "occurred_at": "text",
    "source": "text",
    "subject": "text",
    "physical_table": "text",
    "version_id": "text",
    "version_number": "bigint",
    "row_id": "bigint",
    "business_key": "jsonb",
    "before": "jsonb",
    "after": "jsonb",
}
_NULLABLE = {
    "sequence": False,
    "operation": False,
    "occurred_at": False,
    "source": True,
    "subject": True,
    "physical_table": False,
    "version_id": False,
    "version_number": False,
    "row_id": True,
    "business_key": True,
    "before": True,
    "after": True,
}

_PLAIN = AttributeRecord(
    name="sku",
    type="string",
    required=True,
    unique=True,
    max_length=32,
    attribute_id="att_sku",
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
def changes_database():
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_cdset") as urls:
        previous = os.environ.get("ENTITY_DATABASE_URL")
        os.environ["ENTITY_DATABASE_URL"] = urls.owner_url
        reset_settings_cache()
        reset_entity_engine()
        try:
            yield
        finally:
            reset_entity_engine()
            if previous is None:
                os.environ.pop("ENTITY_DATABASE_URL", None)
            else:
                os.environ["ENTITY_DATABASE_URL"] = previous
            reset_settings_cache()


@pytest.fixture
def fresh_datasets(changes_database):
    from backend.admin.system_parameters import reset_parameter_registry
    from backend.channel.dataset_registry import reset_dataset_store
    from backend.worker.parameters import assemble_system_parameters

    assemble_system_parameters()
    reset_dataset_store()
    yield
    reset_dataset_store()
    reset_parameter_registry()


def _relation(table: str) -> str:
    return qualified_table(ENTITY_DATA_SCHEMA, table)


def _create_table(table: str, attributes: list[AttributeRecord]) -> None:
    PostgresEntityTablePort().create_physical_table(
        ENTITY_DATA_SCHEMA, table, attributes
    )


def _insert(conn: Connection, table: str, sku: str, qty: int | None = None) -> int:
    if qty is None:
        row_id = conn.execute(
            text(
                f"INSERT INTO {_relation(table)} (sku) VALUES (:sku) RETURNING row_id"
            ),
            {"sku": sku},
        ).scalar_one()
    else:
        row_id = conn.execute(
            text(
                f"INSERT INTO {_relation(table)} (sku, qty) "
                "VALUES (:sku, :qty) RETURNING row_id"
            ),
            {"sku": sku, "qty": qty},
        ).scalar_one()
    return int(row_id)


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
    _create_table(table, attrs)
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
    ensure_system_grant(entity_id, attrs)
    return entity_id, table


def _node(entity_id: str, **config: object) -> dict[str, object]:
    body: dict[str, object] = {"entity_id": entity_id}
    body.update(config)
    return {"id": _NODE_ID, "type": "volume.changes_dataset", "config": body}


def _hooks(bound: int, *, run_id: str = "run_changes") -> FakeHooks:
    hooks = FakeHooks(run_id=run_id, channel_id="chn_1")
    hooks.checkpoints.bound_value = bound
    return hooks


def _update_qty(conn: Connection, table: str, sku: str, qty: int) -> None:
    conn.execute(
        text(f"UPDATE {_relation(table)} SET qty = :qty WHERE sku = :sku"),
        {"sku": sku, "qty": qty},
    )


def _delete_row(conn: Connection, table: str, sku: str) -> None:
    conn.execute(
        text(f"DELETE FROM {_relation(table)} WHERE sku = :sku"),
        {"sku": sku},
    )


def _set_source(conn: Connection, source: str, subject: str) -> None:
    conn.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": SOURCE_GUC, "value": source},
    )
    conn.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": SUBJECT_GUC, "value": subject},
    )


def _positions(conn: Connection, entity_id: str) -> list[tuple[int, int]]:
    rows = conn.execute(
        text(
            "SELECT commit_seq, seq "
            "FROM entity_change_log.entry "
            "WHERE entity_id = :entity_id AND commit_seq IS NOT NULL "
            "ORDER BY commit_seq"
        ),
        {"entity_id": entity_id},
    )
    return [(int(commit_seq), int(seq)) for commit_seq, seq in rows]


def _occurred_at(conn: Connection, entity_id: str) -> list[datetime]:
    rows = conn.execute(
        text(
            "SELECT occurred_at FROM entity_change_log.entry "
            "WHERE entity_id = :entity_id ORDER BY xact, seq"
        ),
        {"entity_id": entity_id},
    )
    return [occurred for (occurred,) in rows]


def _page(dataset_id: str, *, after_ord: int, limit: int) -> list[dict]:
    from backend.channel.dataset_registry import DatasetRegistry, get_dataset_store

    return DatasetRegistry(get_dataset_store()).read_page(
        dataset_id, after_ord=after_ord, limit=limit
    )


def _rows(dataset_id: str, *, limit: int = 1000) -> list[dict]:
    return _page(dataset_id, after_ord=0, limit=limit)


def _relations() -> list[str]:
    from backend.entity.datasets import list_dataset_relations

    return list_dataset_relations()


def _job_records(run_id: str):
    from backend.channel.dataset_registry import get_dataset_store

    return get_dataset_store().list_for_jobs([run_id])


def test_empty_range_lands_an_empty_dataset_and_proposes_nothing(
    fresh_datasets,
) -> None:
    engine = get_entity_engine()
    entity_id, _table = _arm(engine)
    hooks = _hooks(capture_bound(entity_id))
    result = NODE_TYPE.execute(_node(entity_id), hooks)
    assert result.status == "succeeded", result.error_message
    assert set(result.output) == {"dataset", "count"}
    assert result.output["count"] == 0
    dataset = result.output["dataset"]
    assert dataset["count"] == 0
    assert [column["name"] for column in dataset["columns"]] == list(_COLUMNS)
    assert [
        (column["name"], column["type"], column["nullable"])
        for column in dataset["columns"]
    ] == [(name, _NORMALIZED[name], _NULLABLE[name]) for name in _COLUMNS]
    from backend.channel.dataset_registry import get_dataset_store

    stored = get_dataset_store().get(dataset["dataset_id"])
    assert stored is not None
    assert stored.status == "ready"
    assert stored.row_count == 0
    assert [(column["name"], column["type"]) for column in stored.columns] == [
        (name, _PHYSICAL[name]) for name in _COLUMNS
    ]
    assert _rows(dataset["dataset_id"]) == []
    assert hooks.checkpoints.proposals == {}


def test_changes_dataset_declares_a_bounded_volume_load() -> None:
    node = NODE_TYPE
    assert node.type_id == "volume.changes_dataset"
    assert node.family == "volume"
    assert node.label == "Changes Dataset"
    assert node.trigger is False
    assert node.container is None
    assert node.permission is None
    assert node.execute is not None
    assert [port.port for port in node.inputs] == ["main"]
    assert [port.port for port in node.outputs] == ["main", "error"]
    assert node.output_view.kind == "dataset"
    assert node.output_view.dataset == "dataset"
    assert node.output_view.metrics == ("count",)
    schema = node.config_schema
    assert schema["required"] == ["entity_id"]
    assert "shape" not in schema["properties"]
    limit = schema["properties"]["limit"]
    assert limit["type"] == "integer"
    assert limit["minimum"] == 1
    assert limit["maximum"] == 10000000
    assert limit["default"] == 1000000
    timeout = schema["properties"]["statement_timeout_sec"]
    assert timeout["minimum"] == 1
    assert timeout["maximum"] == 3600
    assert timeout["default"] == 300
    assert schema["properties"]["sources"]["items"]["enum"] == [
        "user",
        "channel_run",
        "unattributed",
    ]
    assert schema["properties"]["entity_id"]["x-refraq-ref"] == "entity"


def test_rows_match_read_changes_entries_in_xact_seq_order(fresh_datasets) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "SO001")
        _update_qty(conn, table, "SO001", 2)
    with engine.begin() as conn:
        _set_source(conn, "channel_run", "run_9")
        _insert(conn, table, "SO002")
        _delete_row(conn, table, "SO002")
    bound = capture_bound(entity_id)
    read_hooks = _hooks(bound, run_id="run_read")
    read = READ_CHANGES.execute(
        {
            "id": "nd_read",
            "type": "read.changes",
            "config": {"entity_id": entity_id, "limit": 100, "shape": "entries"},
        },
        read_hooks,
    )
    assert read.status == "succeeded", read.error_message
    hooks = _hooks(bound)
    result = NODE_TYPE.execute(_node(entity_id), hooks)
    assert result.status == "succeeded", result.error_message
    assert "has_more" not in result.output
    assert "last_sequence" not in result.output
    rows = _rows(result.output["dataset"]["dataset_id"])
    entries = read.output["entries"]
    assert result.output["count"] == len(rows) == len(entries)
    assert [row["_ord"] for row in rows] == list(range(1, len(rows) + 1))
    assert "commit_seq" not in rows[0]
    shared = (
        "sequence",
        "operation",
        "occurred_at",
        "source",
        "subject",
        "physical_table",
        "version_id",
        "version_number",
        "before",
        "after",
    )
    assert [{name: row[name] for name in shared} for row in rows] == [
        {name: item[name] for name in shared} for item in entries
    ]
    assert [row["business_key"] for row in rows] == ["SO001", "SO001", "SO002", "SO002"]
    position = hooks.checkpoints.proposed(_NODE_ID, entity_id)
    assert position is not None
    assert position.seq == rows[-1]["sequence"]


def test_source_filter_omits_hidden_entries_and_the_proposal_passes_them(
    fresh_datasets,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _set_source(conn, "user", "alice")
        _insert(conn, table, "kept")
        _set_source(conn, "channel_run", "run_9")
        _insert(conn, table, "hidden")
    bound = capture_bound(entity_id)
    oracle = read_incremental(entity_id, after=None, bound=bound, limit=10)
    hooks = _hooks(bound)
    result = NODE_TYPE.execute(_node(entity_id, sources=["user"]), hooks)
    assert result.status == "succeeded", result.error_message
    rows = _rows(result.output["dataset"]["dataset_id"])
    assert result.output["count"] == 1
    assert [row["business_key"] for row in rows] == ["kept"]
    hidden = oracle.events[-1]
    assert hidden.after.values["sku"] == "hidden"
    assert hooks.checkpoints.proposed(_NODE_ID, entity_id) == CheckpointPosition(
        xact=hidden.commit_seq, seq=hidden.sequence
    )
    again = NODE_TYPE.execute(_node(entity_id, sources=["user"]), hooks)
    assert again.status == "succeeded", again.error_message
    assert again.output["count"] == 0


def test_limit_counts_hidden_entries_and_the_next_execution_continues(
    fresh_datasets,
) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _set_source(conn, "user", "alice")
        _insert(conn, table, "first")
        _set_source(conn, "channel_run", "run_9")
        _insert(conn, table, "hidden")
        _set_source(conn, "user", "alice")
        _insert(conn, table, "third")
    bound = capture_bound(entity_id)
    oracle = read_incremental(entity_id, after=None, bound=bound, limit=10)
    hooks = _hooks(bound)
    first = NODE_TYPE.execute(_node(entity_id, sources=["user"], limit=2), hooks)
    assert first.status == "succeeded", first.error_message
    assert first.output["count"] == 1
    assert [
        row["business_key"] for row in _rows(first.output["dataset"]["dataset_id"])
    ] == ["first"]
    cut = oracle.events[1]
    assert cut.after.values["sku"] == "hidden"
    assert hooks.checkpoints.proposed(_NODE_ID, entity_id) == CheckpointPosition(
        xact=cut.commit_seq, seq=cut.sequence
    )
    second = NODE_TYPE.execute(_node(entity_id, sources=["user"], limit=2), hooks)
    assert second.status == "succeeded", second.error_message
    assert [
        row["business_key"] for row in _rows(second.output["dataset"]["dataset_id"])
    ] == ["third"]
    tail = oracle.events[2]
    assert hooks.checkpoints.proposed(_NODE_ID, entity_id) == CheckpointPosition(
        xact=tail.commit_seq, seq=tail.sequence
    )


def test_an_open_transaction_does_not_hold_later_commits(fresh_datasets) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    held = engine.connect()
    held_tx = held.begin()
    try:
        _insert(held, table, "early")
        with engine.begin() as conn:
            _insert(conn, table, "later")
        hooks = _hooks(capture_bound(entity_id))
        hidden = NODE_TYPE.execute(_node(entity_id), hooks)
        assert hidden.status == "succeeded", hidden.error_message
        assert [
            row["business_key"] for row in _rows(hidden.output["dataset"]["dataset_id"])
        ] == ["later"]
        assert hooks.checkpoints.proposals != {}
        held_tx.commit()
    finally:
        held.close()
    seen = NODE_TYPE.execute(
        _node(entity_id), _hooks(capture_bound(entity_id), run_id="run_after")
    )
    assert seen.status == "succeeded", seen.error_message
    assert [
        row["business_key"] for row in _rows(seen.output["dataset"]["dataset_id"])
    ] == ["later", "early"]


def test_recording_off_invalid_cursor_and_ignore_checkpoints(fresh_datasets) -> None:
    engine = get_entity_engine()
    quiet_id, _table = _arm(engine, recording=False)
    off_hooks = _hooks(1, run_id="run_off")
    off = NODE_TYPE.execute(_node(quiet_id), off_hooks)
    assert off.status == "failed"
    assert off.error_code == "CHANNEL_CHANGE_LOG_OFF"
    assert off.error_message == "Change recording is off for this entity."
    assert off_hooks.checkpoints.proposals == {}
    assert _job_records("run_off") == []

    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "kept")
        _insert(conn, table, "dropped")
    with engine.begin() as conn:
        positions = _positions(conn, entity_id)
        delete_entries_before(conn, entity_id, utc_now() + timedelta(days=1))
    hooks = _hooks(capture_bound(entity_id), run_id="run_invalid")
    hooks.checkpoints.durable_positions[(_NODE_ID, entity_id)] = CheckpointPosition(
        xact=positions[0][0], seq=positions[0][1]
    )
    before = set(_relations())
    invalid = NODE_TYPE.execute(_node(entity_id), hooks)
    assert invalid.status == "failed"
    assert invalid.error_code == "CHANNEL_CHECKPOINT_INVALID"
    assert invalid.error_message == "Checkpoint is behind deleted change-log entries."
    assert hooks.checkpoints.proposals == {}
    assert _job_records("run_invalid") == []
    assert set(_relations()) == before

    hooks.ignore_checkpoints = True
    recovered = NODE_TYPE.execute(_node(entity_id), hooks)
    assert recovered.status == "succeeded", recovered.error_message
    assert recovered.output["count"] == 0
    assert hooks.checkpoints.proposals == {}
    stored = _job_records("run_invalid")
    assert len(stored) == 1
    assert stored[0].status == "ready"
    assert stored[0].row_count == 0


def test_a_missing_entity_fails_without_a_proposal(fresh_datasets) -> None:
    engine = get_entity_engine()
    entity_id = new_entity_id()
    with engine.begin() as conn:
        ensure_shared_relations(conn)
        write_effective(
            conn,
            ChangeLogEffective(
                entity_id=entity_id,
                recording=True,
                retention_days=None,
                applied_version_id="missing",
            ),
        )
    hooks = _hooks(capture_bound(entity_id), run_id="run_missing")
    before = set(_relations())
    result = NODE_TYPE.execute(_node(entity_id), hooks)
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert result.error_message == "Entity does not resolve"
    assert hooks.checkpoints.proposals == {}
    assert set(_relations()) == before
    records = _job_records("run_missing")
    assert len(records) == 1
    assert records[0].status == "dropped"


def test_a_historical_purge_still_lands_the_rows_that_remain(fresh_datasets) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "old")
    with engine.begin() as conn:
        _insert(conn, table, "new")
    with engine.begin() as conn:
        occurred = _occurred_at(conn, entity_id)
        delete_entries_before(conn, entity_id, occurred[1])
    hooks = _hooks(capture_bound(entity_id), run_id="run_history")
    result = NODE_TYPE.execute(_node(entity_id), hooks)
    assert result.status == "succeeded", result.error_message
    assert [
        row["business_key"] for row in _rows(result.output["dataset"]["dataset_id"])
    ] == ["new"]
    position = hooks.checkpoints.proposed(_NODE_ID, entity_id)
    assert position is not None
    assert position.seq == _rows(result.output["dataset"]["dataset_id"])[0]["sequence"]


def test_a_purge_during_the_load_drops_the_table_and_proposes_nothing(
    fresh_datasets, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.channel.nodes.volume.changes_dataset as changes_dataset

    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "read")
        _insert(conn, table, "also")
    bound = capture_bound(entity_id)
    real = changes_dataset.read_change_range
    purged = {"done": False}

    def wrapped(opened, *, limit, after=None):
        page = real(opened, limit=limit, after=after)
        if page.progress is not None and not purged["done"]:
            purged["done"] = True
            with get_entity_engine().begin() as conn:
                delete_entries(conn, opened.entity_id)
        return page

    monkeypatch.setattr(changes_dataset, "read_change_range", wrapped)
    hooks = _hooks(bound, run_id="run_purge")
    before = set(_relations())
    result = NODE_TYPE.execute(_node(entity_id), hooks)
    assert purged["done"] is True
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_CHECKPOINT_INVALID"
    assert result.error_message == "Checkpoint is behind deleted change-log entries."
    assert hooks.checkpoints.proposals == {}
    assert set(_relations()) == before
    records = _job_records("run_purge")
    assert len(records) == 1
    assert records[0].status == "dropped"


def test_capacity_ceiling_drops_the_table_and_proposes_nothing(
    fresh_datasets, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.channel.dataset_registry import DatasetRecord, get_dataset_store
    from backend.entity.datasets import physical_relation

    monkeypatch.setattr(
        "backend.channel.dataset_registry.channel_dataset_max_total_gb",
        lambda: 1,
    )
    get_dataset_store().save(
        DatasetRecord(
            id="dplanted",
            job_id="job_other",
            node_id="nd_other",
            seq=1,
            relation=physical_relation("dplanted"),
            columns=[],
            row_count=0,
            size_bytes=1024**3 - 1,
            status="ready",
            created_at=utc_now(),
        )
    )
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "one")
    hooks = _hooks(capture_bound(entity_id), run_id="run_quota")
    before = set(_relations())
    result = NODE_TYPE.execute(_node(entity_id), hooks)
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_DATASET_QUOTA_EXCEEDED"
    assert result.error_message == "Dataset storage is already at the capacity ceiling"
    assert hooks.checkpoints.proposals == {}
    assert set(_relations()) == before
    records = _job_records("run_quota")
    assert len(records) == 1
    assert records[0].status == "dropped"


def test_cancel_between_pages_drops_the_table_and_proposes_nothing(
    fresh_datasets, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.channel.nodes.volume.changes_dataset as changes_dataset

    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "one")
        _insert(conn, table, "two")
    hooks = _hooks(capture_bound(entity_id), run_id="run_cancel")
    real = changes_dataset.read_change_range

    def wrapped(opened, *, limit, after=None):
        page = real(opened, limit=limit, after=after)
        hooks.cancel_after = _NODE_ID
        return page

    monkeypatch.setattr(changes_dataset, "read_change_range", wrapped)
    before = set(_relations())
    with pytest.raises(changes_dataset._LoadHalted, match="^cancelled$"):
        NODE_TYPE.execute(_node(entity_id), hooks)
    assert hooks.checkpoints.proposals == {}
    assert set(_relations()) == before
    records = _job_records("run_cancel")
    assert len(records) == 1
    assert records[0].status == "dropped"


def test_supersede_between_pages_drops_the_table_and_proposes_nothing(
    fresh_datasets, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.channel.nodes.volume.changes_dataset as changes_dataset

    class _Hooks(FakeHooks):
        def __init__(self, bound: int) -> None:
            super().__init__(run_id="run_supersede", channel_id="chn_1")
            self.checkpoints.bound_value = bound
            self.stop = False

        def superseded(self) -> bool:
            return self.stop

    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "one")
    hooks = _Hooks(capture_bound(entity_id))
    real = changes_dataset.read_change_range

    def wrapped(opened, *, limit, after=None):
        page = real(opened, limit=limit, after=after)
        hooks.stop = True
        return page

    monkeypatch.setattr(changes_dataset, "read_change_range", wrapped)
    before = set(_relations())
    with pytest.raises(changes_dataset._LoadHalted, match="^superseded$"):
        NODE_TYPE.execute(_node(entity_id), hooks)
    assert hooks.checkpoints.proposals == {}
    assert set(_relations()) == before
    records = _job_records("run_supersede")
    assert len(records) == 1
    assert records[0].status == "dropped"


def test_the_deadline_between_pages_fails_the_node_and_drops_the_table(
    fresh_datasets, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.channel.nodes.volume.changes_dataset as changes_dataset

    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "one")
        _insert(conn, table, "two")
    hooks = _hooks(capture_bound(entity_id), run_id="run_deadline")
    clock = {"now": 0.0}
    monkeypatch.setattr(changes_dataset.time, "monotonic", lambda: clock["now"])
    real = changes_dataset.read_change_range

    def wrapped(opened, *, limit, after=None):
        page = real(opened, limit=limit, after=after)
        clock["now"] = 10_000.0
        return page

    monkeypatch.setattr(changes_dataset, "read_change_range", wrapped)
    before = set(_relations())
    result = NODE_TYPE.execute(_node(entity_id), hooks)
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert result.error_message == "Changes Dataset exceeded the statement timeout"
    assert hooks.checkpoints.proposals == {}
    assert set(_relations()) == before
    records = _job_records("run_deadline")
    assert len(records) == 1
    assert records[0].status == "dropped"


def test_a_range_past_one_page_is_scanned_in_pages_of_10000(
    fresh_datasets, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.channel.nodes.volume.changes_dataset as changes_dataset

    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {_relation(table)} (sku) "
                "SELECT 's' || g FROM generate_series(1, 10001) AS g"
            )
        )
    bound = capture_bound(entity_id)
    limits: list[int] = []
    real = changes_dataset.read_change_range

    def wrapped(opened, *, limit, after=None):
        limits.append(limit)
        return real(opened, limit=limit, after=after)

    monkeypatch.setattr(changes_dataset, "read_change_range", wrapped)
    hooks = _hooks(bound, run_id="run_pages")
    result = NODE_TYPE.execute(_node(entity_id, limit=10001), hooks)
    assert result.status == "succeeded", result.error_message
    assert result.output["count"] == 10001
    assert limits == [10000, 1]
    dataset_id = result.output["dataset"]["dataset_id"]
    first = _page(dataset_id, after_ord=0, limit=1)
    last = _page(dataset_id, after_ord=10000, limit=1)
    assert first[0]["business_key"] == "s1"
    assert first[0]["_ord"] == 1
    assert last[0]["business_key"] == "s10001"
    assert last[0]["_ord"] == 10001
    assert "xact" not in first[0]
    position = hooks.checkpoints.proposed(_NODE_ID, entity_id)
    assert position is not None
    assert position.seq == last[0]["sequence"]


def _restrict_system(
    entity_id: str,
    *,
    row_rule: dict[str, object] | None = None,
    deny_columns: list[str] | None = None,
) -> None:
    from backend.admin.user_store import SYSTEM_USER_ID

    now = utc_now()
    store = get_access_store()
    store.insert_restriction(
        RestrictionRecord(
            id=new_access_restriction_id(),
            entity_id=entity_id,
            applies_to={
                "mode": "only",
                "subjects": [{"type": "user", "id": SYSTEM_USER_ID}],
            },
            row_rule=row_rule,
            deny_columns=list(deny_columns or []),
            ceilings=[],
            actions=["read"],
            created_at=now,
            updated_at=now,
        )
    )
    store.set_revision(entity_id, store.revision(entity_id) + 1)


def test_a_system_restriction_omits_the_event_and_still_advances(
    fresh_datasets,
) -> None:
    """The triggering user can see the row. System Identity cannot.

    The omitted event writes no dataset row and the proposal is that event.
    """
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    outsider = get_user_store().create_user(
        account=f"out-{entity_id[-8:]}",
        display_name="Outsider",
        password_hash=None,
        role_id=None,
        status="active",
    )
    ensure_creator_grant(entity_id, outsider.id, [_SKU, _QTY])
    _restrict_system(entity_id, row_rule={"eq": {"attr": "att_qty", "value": 9}})
    with engine.begin() as conn:
        _insert(conn, table, "hidden", qty=1)
        _insert(conn, table, "shown", qty=9)
    with engine.begin() as conn:
        positions = _positions(conn, entity_id)
    hooks = _hooks(capture_bound(entity_id))
    hooks.user = outsider
    hidden = NODE_TYPE.execute(_node(entity_id, limit=1), hooks)
    assert hidden.status == "succeeded", hidden.error_message
    assert hidden.output["count"] == 0
    assert _rows(hidden.output["dataset"]["dataset_id"]) == []
    assert hooks.checkpoints.proposed(_NODE_ID, entity_id) == CheckpointPosition(
        xact=positions[0][0], seq=positions[0][1]
    )
    shown = NODE_TYPE.execute(_node(entity_id, limit=1), hooks)
    assert shown.status == "succeeded", shown.error_message
    rows = _rows(shown.output["dataset"]["dataset_id"])
    assert [row["business_key"] for row in rows] == ["shown"]
    assert rows[0]["row_id"] != rows[0]["business_key"]
    assert hooks.checkpoints.proposed(_NODE_ID, entity_id) == CheckpointPosition(
        xact=positions[1][0], seq=positions[1][1]
    )


def test_an_equal_projected_update_is_written(fresh_datasets) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    _restrict_system(entity_id, deny_columns=["att_qty"])
    with engine.begin() as conn:
        row_id = _insert(conn, table, "EQ", qty=1)
        _update_qty(conn, table, "EQ", 5)
    hooks = _hooks(capture_bound(entity_id))
    result = NODE_TYPE.execute(_node(entity_id), hooks)
    assert result.status == "succeeded", result.error_message
    rows = _rows(result.output["dataset"]["dataset_id"])
    assert [row["operation"] for row in rows] == ["insert", "update"]
    update = rows[1]
    assert update["business_key"] == "EQ"
    assert update["row_id"] == row_id
    assert update["before"]["state"] == "visible"
    assert update["after"]["state"] == "visible"
    assert update["before"]["values"] == update["after"]["values"]
    assert update["after"]["values"]["sku"] == "EQ"
    assert "qty" not in update["after"]["values"]
    assert "commit_seq" not in update
    assert update["version_number"] == 1
    assert table in update["physical_table"]
    position = hooks.checkpoints.proposed(_NODE_ID, entity_id)
    assert position is not None
    assert position.seq == update["sequence"]


def test_a_withheld_business_key_is_an_empty_cell(fresh_datasets) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    _restrict_system(entity_id, deny_columns=["att_sku"])
    with engine.begin() as conn:
        row_id = _insert(conn, table, "HIDDEN", qty=1)
    hooks = _hooks(capture_bound(entity_id))
    result = NODE_TYPE.execute(_node(entity_id), hooks)
    assert result.status == "succeeded", result.error_message
    rows = _rows(result.output["dataset"]["dataset_id"])
    assert len(rows) == 1
    assert rows[0]["business_key"] is None
    assert rows[0]["row_id"] == row_id
    assert "sku" not in rows[0]["after"]["values"]
    assert hooks.checkpoints.proposals != {}


def test_a_masked_business_key_is_an_empty_cell(fresh_datasets) -> None:
    from dataclasses import replace

    from backend.admin.user_store import SYSTEM_USER_ID

    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    now = utc_now()
    store = get_access_store()
    store.save_ladder(
        LadderRecord(
            entity_id=entity_id,
            attribute_id="att_sku",
            levels=[
                {"key": "clear", "mode": "clear"},
                {"key": "masked", "mode": {"type": "partial", "keep_first": 1, "keep_last": 1}},
            ],
            updated_at=now,
        )
    )
    for grant in store.grants(entity_id):
        if grant.subject_id == SYSTEM_USER_ID:
            store.update_grant(
                replace(
                    grant,
                    row_rule={"eq": {"attr": "att_qty", "value": 9}},
                    updated_at=now,
                )
            )
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
            row_rule={"eq": {"attr": "att_qty", "value": 1}},
            actions=["read"],
            status="active",
            valid_until=None,
            created_at=now,
            updated_at=now,
        )
    )
    store.set_revision(entity_id, store.revision(entity_id) + 1)
    with engine.begin() as conn:
        row_id = _insert(conn, table, "abcdef", qty=1)
    result = NODE_TYPE.execute(_node(entity_id), _hooks(capture_bound(entity_id)))
    assert result.status == "succeeded", result.error_message
    rows = _rows(result.output["dataset"]["dataset_id"])
    assert len(rows) == 1
    assert rows[0]["business_key"] is None
    assert rows[0]["row_id"] == row_id
    assert rows[0]["after"]["values"]["sku"] == "a****f"


def test_an_undeclared_business_key_leaves_the_cell_empty(fresh_datasets) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine, attributes=[_PLAIN, _QTY])
    with engine.begin() as conn:
        row_id = _insert(conn, table, "KEEP")
    result = NODE_TYPE.execute(_node(entity_id), _hooks(capture_bound(entity_id)))
    assert result.status == "succeeded", result.error_message
    rows = _rows(result.output["dataset"]["dataset_id"])
    assert len(rows) == 1
    assert rows[0]["business_key"] is None
    assert rows[0]["row_id"] == row_id
    assert rows[0]["after"]["values"]["sku"] == "KEEP"


def test_disagreeing_visible_keys_leave_the_cell_empty(fresh_datasets) -> None:
    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        row_id = _insert(conn, table, "ALPHA")
        conn.execute(
            text(f"UPDATE {_relation(table)} SET sku = :sku WHERE sku = 'ALPHA'"),
            {"sku": "BETA"},
        )
    result = NODE_TYPE.execute(_node(entity_id), _hooks(capture_bound(entity_id)))
    assert result.status == "succeeded", result.error_message
    rows = _rows(result.output["dataset"]["dataset_id"])
    assert [row["operation"] for row in rows] == ["insert", "update"]
    assert rows[0]["business_key"] == "ALPHA"
    assert rows[1]["business_key"] is None
    assert rows[1]["row_id"] == row_id
    assert rows[1]["before"]["values"]["sku"] == "ALPHA"
    assert rows[1]["after"]["values"]["sku"] == "BETA"


def test_a_later_page_that_fails_authorization_proposes_nothing(
    fresh_datasets, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.channel.nodes.volume.changes_dataset as changes_dataset
    from backend.admin.user_store import SYSTEM_USER_ID

    engine = get_entity_engine()
    entity_id, table = _arm(engine)
    with engine.begin() as conn:
        _insert(conn, table, "one")
        _insert(conn, table, "two")
    monkeypatch.setattr(changes_dataset, "_PAGE", 1)
    real = changes_dataset.read_change_range
    calls = {"n": 0}

    def wrapped(opened, *, limit, after=None):
        calls["n"] += 1
        if calls["n"] >= 2:
            store = get_access_store()
            for grant in store.grants(opened.entity_id):
                if grant.subject_id == SYSTEM_USER_ID:
                    store.delete_grant(grant.id)
            store.set_revision(opened.entity_id, store.revision(opened.entity_id) + 1)
        return real(opened, limit=limit, after=after)

    monkeypatch.setattr(changes_dataset, "read_change_range", wrapped)
    hooks = _hooks(capture_bound(entity_id), run_id="run_auth")
    before = set(_relations())
    result = NODE_TYPE.execute(_node(entity_id), hooks)
    assert calls["n"] >= 2
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert hooks.checkpoints.proposals == {}
    assert set(_relations()) == before
    records = _job_records("run_auth")
    assert len(records) == 1
    assert records[0].status == "dropped"
