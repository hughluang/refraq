"""Focused PG smoke tests for Dataset bindings, Dataset Buffer, and Write Entity replace."""

from __future__ import annotations

import pytest

from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration


@pytest.fixture()
def data_client(monkeypatch: pytest.MonkeyPatch):
    from backend.tests.test_entity_data import (
        _MAINTENANCE_DATABASE_URL,
        _postgres_available,
        _serve,
    )
    from backend.worker.parameters import assemble_system_parameters

    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_cprim") as urls:
        assemble_system_parameters()
        yield from _serve(monkeypatch, urls)


@pytest.fixture()
def dataset_store(data_client):
    from backend.channel.dataset_registry import get_dataset_store, reset_dataset_store

    reset_dataset_store()
    store = get_dataset_store()
    try:
        yield data_client, store
    finally:
        reset_dataset_store()


def _node(type_id: str):
    from backend.channel.nodes import list_node_types

    return next(item for item in list_node_types() if item.type_id == type_id)


def test_bind_dataset_sql_rewrites_unshadowed_aliases() -> None:
    from backend.channel.dataset_bindings import bind_dataset_sql

    sql = (
        'WITH src_a AS (SELECT 1 AS id) '
        'SELECT a.sku, b.qty, s.id FROM src_b AS b '
        'JOIN src_a AS s ON true '
        'JOIN entity_tbl AS a ON a.sku = b.sku'
    )
    bound = bind_dataset_sql(
        sql,
        {
            "src_a": '"channel_dataset"."ds_d111"',
            "src_b": '"channel_dataset"."ds_d222"',
        },
    )
    assert '"channel_dataset"."ds_d222" AS b' in bound
    assert '"channel_dataset"."ds_d111"' not in bound
    assert "entity_tbl AS a" in bound


def test_dataset_query_and_sql_bind_multiple_datasets_in_pg(dataset_store) -> None:
    from backend.admin.user_store import get_user_store
    from backend.channel.dataset_registry import DatasetColumnSpec, DatasetRegistry
    from backend.tests.channel_hooks_fake import FakeHooks

    (_client, _stem, _physical, _entity_id), store = dataset_store
    admin = get_user_store().get_by_account("admin")
    assert admin is not None

    reg = DatasetRegistry(store)
    ds_a = reg.create_from_chunks(
        job_id="run_bind",
        node_id="n_a",
        seq=1,
        columns=[DatasetColumnSpec("sku", "string"), DatasetColumnSpec("qty", "integer")],
        chunks=[[("A1", 10), ("A2", 20)]],
    )
    ds_b = reg.create_from_chunks(
        job_id="run_bind",
        node_id="n_b",
        seq=2,
        columns=[DatasetColumnSpec("sku", "string"), DatasetColumnSpec("note", "string")],
        chunks=[[("A1", "first"), ("A2", "second")]],
    )
    hooks = FakeHooks(user=admin, run_id="run_bind")

    dq = _node("volume.dataset_query")
    res = dq.execute(
        {
            "id": "n_join",
            "type": "volume.dataset_query",
            "config": {
                "source": {"kind": "entity"},
                "sql": "SELECT a.sku, a.qty, b.note FROM left_ds AS a JOIN right_ds AS b ON a.sku = b.sku ORDER BY a.sku",
                "datasets": {
                    "left_ds": f'{{"dataset_id": "{ds_a.id}", "columns": [], "count": 2}}',
                    "right_ds": f'{{"dataset_id": "{ds_b.id}", "columns": [], "count": 2}}',
                },
            },
        },
        hooks,
    )
    assert res.status == "succeeded", res.error_message
    assert res.output["count"] == 2

    sql_node = _node("read.sql")
    read_res = sql_node.execute(
        {
            "id": "n_read",
            "type": "read.sql",
            "config": {
                "source": {"kind": "entity"},
                "sql": "SELECT sku, note FROM joined WHERE sku = %s",
                "params": ['"A2"'],
                "datasets": {
                    "joined": f'{{"dataset_id": "{res.output["dataset"]["dataset_id"]}", "columns": [], "count": 2}}',
                },
            },
        },
        hooks,
    )
    assert read_res.status == "succeeded", read_res.error_message
    assert read_res.output["rows"] == [{"sku": "A2", "note": "second"}]


def test_dataset_buffer_append_and_empty_get_in_pg(dataset_store) -> None:
    from backend.admin.user_store import get_user_store
    from backend.channel.dataset_registry import DatasetColumnSpec, DatasetRegistry
    from backend.tests.channel_hooks_fake import FakeHooks

    (_client, _stem, _physical, _entity_id), store = dataset_store
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    hooks = FakeHooks(user=admin, run_id="run_buf")
    buf = _node("volume.dataset_buffer")

    empty_get = buf.execute(
        {"id": "n_empty", "type": "volume.dataset_buffer", "config": {"operation": "get", "name": "empty_buf"}},
        hooks,
    )
    assert empty_get.status == "succeeded", empty_get.error_message
    assert empty_get.output["count"] == 0
    assert empty_get.output["dataset"]["columns"] == []

    app1 = buf.execute(
        {
            "id": "n_a1",
            "type": "volume.dataset_buffer",
            "config": {
                "operation": "append",
                "name": "items_buf",
                "source": '[{"sku": "S1", "qty": 1}, {"sku": "S2", "qty": 2}]',
            },
        },
        hooks,
    )
    assert app1.status == "succeeded", app1.error_message
    assert app1.output["count"] == 2

    ds_page2 = DatasetRegistry(store).create_from_chunks(
        job_id="run_buf",
        node_id="n_src2",
        seq=10,
        columns=[DatasetColumnSpec("sku", "string"), DatasetColumnSpec("qty", "integer")],
        chunks=[[("S3", 3)]],
    )
    app2 = buf.execute(
        {
            "id": "n_a2",
            "type": "volume.dataset_buffer",
            "config": {
                "operation": "append",
                "name": "items_buf",
                "source": f'{{"dataset_id": "{ds_page2.id}", "columns": [], "count": 1}}',
            },
        },
        hooks,
    )
    assert app2.status == "succeeded", app2.error_message
    assert app2.output["count"] == 3

    got = buf.execute(
        {"id": "n_get", "type": "volume.dataset_buffer", "config": {"operation": "get", "name": "items_buf"}},
        hooks,
    )
    assert got.status == "succeeded"
    assert got.output["count"] == 3
    assert [c["name"] for c in got.output["dataset"]["columns"]] == ["sku", "qty"]


def test_write_entity_replace_reconciles_and_clears_in_pg(dataset_store) -> None:
    from backend.admin.user_store import get_user_store
    from backend.entity.rows import read_rows
    from backend.tests.channel_hooks_fake import FakeHooks

    (_client, _stem, _physical, entity_id), _store = dataset_store
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    hooks = FakeHooks(user=admin, run_id="run_rep")
    we = _node("write.entity")

    seed = we.execute(
        {
            "id": "n_w1",
            "type": "write.entity",
            "config": {
                "entity_id": entity_id,
                "mode": "replace",
                "match_key": "sku",
                "source": '[{"sku": "A", "qty": 1, "note": "one"}, {"sku": "B", "qty": 2, "note": "two"}]',
                "mapping": [],
                "on_incompatible_head": "fail",
            },
        },
        hooks,
    )
    assert seed.status == "succeeded", seed.error_message
    assert (seed.output["inserted"], seed.output["deleted"]) == (2, 0)

    reconcile = we.execute(
        {
            "id": "n_w2",
            "type": "write.entity",
            "config": {
                "entity_id": entity_id,
                "mode": "replace",
                "match_key": "sku",
                "source": '[{"sku": "A", "qty": 1, "note": "one"}, {"sku": "B", "qty": 9, "note": "updated"}, {"sku": "C", "qty": 3, "note": "three"}]',
                "mapping": [],
                "on_incompatible_head": "fail",
            },
        },
        hooks,
    )
    assert reconcile.status == "succeeded", reconcile.error_message
    assert reconcile.output == {
        "inserted": 1,
        "updated": 1,
        "unchanged": 1,
        "deleted": 0,
        "unmatched": 0,
    }

    shrink = we.execute(
        {
            "id": "n_w3",
            "type": "write.entity",
            "config": {
                "entity_id": entity_id,
                "mode": "replace",
                "match_key": "sku",
                "source": '[{"sku": "C", "qty": 3, "note": "three"}]',
                "mapping": [],
                "on_incompatible_head": "fail",
            },
        },
        hooks,
    )
    assert shrink.status == "succeeded", shrink.error_message
    assert shrink.output == {
        "inserted": 0,
        "updated": 0,
        "unchanged": 1,
        "deleted": 2,
        "unmatched": 0,
    }

    cleared = we.execute(
        {
            "id": "n_w4",
            "type": "write.entity",
            "config": {
                "entity_id": entity_id,
                "mode": "replace",
                "match_key": "sku",
                "source": "[]",
                "mapping": [],
                "on_incompatible_head": "fail",
            },
        },
        hooks,
    )
    assert cleared.status == "succeeded", cleared.error_message
    assert cleared.output["deleted"] == 1
    rows, total = read_rows(entity_id, filters=[], user=admin, limit=20)
    assert total == 0
    assert rows == []
