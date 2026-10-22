"""Write Entity reads a dataset on a separate owner connection."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration


@pytest.fixture()
def data_client(monkeypatch: pytest.MonkeyPatch):
    from backend.tests.test_entity_data import (
        _MAINTENANCE_DATABASE_URL,
        _postgres_available,
        _serve,
    )

    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_wdata") as urls:
        yield from _serve(monkeypatch, urls)


@pytest.fixture()
def dataset_store(data_client):
    from backend.channel.dataset_registry import get_dataset_store, reset_dataset_store
    from backend.worker.parameters import assemble_system_parameters

    reset_dataset_store()
    assemble_system_parameters()
    store = get_dataset_store()
    try:
        yield data_client, store
    finally:
        reset_dataset_store()


def _execute():
    from backend.channel.nodes import list_node_types

    return next(item.execute for item in list_node_types() if item.type_id == "write.entity")


def _five(result) -> tuple[int, int, int, int, int]:
    output = result.output
    return (
        output["inserted"],
        output["updated"],
        output["unchanged"],
        output["deleted"],
        output["unmatched"],
    )


def _stored(entity_id: str, user):
    from backend.entity.rows import read_rows

    rows, _total = read_rows(entity_id, filters=[], user=user, limit=20)
    return sorted((row["sku"], row["qty"], row["note"]) for row in rows)


def _run(entity_id: str, source: str, user):
    from backend.tests.channel_hooks_fake import FakeHooks

    return _execute()(
        {
            "id": "nd_write",
            "type": "write.entity",
            "config": {
                "entity_id": entity_id,
                "mode": "upsert",
                "match_key": "sku",
                "source": source,
                "mapping": [{"attribute": "sku", "key": "product_code"}],
                "on_incompatible_head": "fail",
            },
        },
        FakeHooks(user=user, run_id="run"),
    )


def _load(store, rows: list[tuple]):
    from backend.channel.dataset_registry import DatasetColumnSpec, DatasetRegistry

    return DatasetRegistry(store).create_from_chunks(
        job_id="run",
        node_id="nd_load",
        seq=1,
        columns=[
            DatasetColumnSpec("product_code", "string"),
            DatasetColumnSpec("qty", "integer"),
            DatasetColumnSpec("note", "string"),
        ],
        chunks=[rows],
    )


def test_dataset_write_matches_the_list_write(dataset_store) -> None:
    from backend.admin.user_store import get_user_store
    from backend.channel.dataset_ref import dataset_reference
    from backend.entity.rows import write_rows

    (_client, _stem, _physical, entity_id), store = dataset_store
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    logical = [
        {"product_code": "A", "qty": 1, "note": "n"},
        {"product_code": "B", "qty": 2, "note": "m"},
    ]
    listed = _run(entity_id, json.dumps(logical), admin)
    assert listed.status == "succeeded"
    listed_rows = _stored(entity_id, admin)
    listed_counts = _five(listed)
    write_rows(
        entity_id,
        mode="delete",
        match_key="sku",
        rows=[{"sku": "A"}, {"sku": "B"}],
        user=admin,
        statement_timeout_ms=5000,
    )
    assert _stored(entity_id, admin) == []
    record = _load(store, [("A", 1, "n"), ("B", 2, "m")])
    reference = dataset_reference(
        dataset_id=record.id, columns=record.columns, count=record.row_count
    )
    lied = {**reference, "count": 0, "columns": [{"name": "other", "type": "string"}]}
    written = _run(entity_id, json.dumps(lied), admin)
    assert written.status == "succeeded", written.error_message
    assert _five(written) == listed_counts == (2, 0, 0, 0, 0)
    assert _stored(entity_id, admin) == listed_rows == [("A", 1, "n"), ("B", 2, "m")]


def test_invalid_row_in_the_last_dataset_chunk_leaves_the_target_unchanged(
    dataset_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.admin.user_store import get_user_store

    (_client, _stem, _physical, entity_id), store = dataset_store
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    monkeypatch.setattr("backend.entity.rows.WRITE_CHUNK_SIZE", 2)
    record = _load(
        store,
        [
            ("A", 1, "n"),
            ("B", 2, "n"),
            ("C", 3, "n"),
            ("D", 4, "n"),
            (None, 5, "bad"),
        ],
    )
    result = _run(
        entity_id,
        json.dumps(
            {
                "dataset_id": record.id,
                "columns": [{"name": "product_code", "type": "string"}],
                "count": record.row_count,
            }
        ),
        admin,
    )
    assert result.status == "failed"
    assert result.error_detail["row_index"] == 5
    assert result.error_detail["reason"] == "invalid"
    assert result.error_message.startswith("Source object 5:")
    assert _stored(entity_id, admin) == []


def test_dataset_pages_use_a_readonly_owner_connection(
    dataset_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.admin.user_store import get_user_store
    from backend.entity.data import sql as data_sql
    from backend.entity.entity_db import get_entity_engine
    from backend.entity.rows import write_rows

    (_client, _stem, _physical, entity_id), store = dataset_store
    admin = get_user_store().get_by_account("admin")
    assert admin is not None
    monkeypatch.setattr("backend.entity.rows.WRITE_CHUNK_SIZE", 2)
    record = _load(
        store,
        [("A", 1, "n"), ("B", 2, "n"), ("C", 3, "n"), ("D", 4, "n"), ("E", 5, "n")],
    )
    events: list[str] = []
    read_identity: list[tuple[int, str, str]] = []
    write_pids: list[int] = []
    real_engine = get_entity_engine()

    class ProxyConn:
        def __init__(self, conn) -> None:
            self._conn = conn

        def begin(self):
            return self._conn.begin()

        def close(self):
            self._conn.close()

        def __enter__(self):
            self._conn.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._conn.__exit__(exc_type, exc, tb)

        def execute(self, statement, *args, **kwargs):
            sql = str(getattr(statement, "text", statement))
            events.append(sql)
            result = self._conn.execute(statement, *args, **kwargs)
            if "READ ONLY" in sql.upper() and not read_identity:
                row = self._conn.execute(
                    text(
                        "SELECT pg_backend_pid(), current_user, "
                        "current_setting('transaction_read_only')"
                    )
                ).one()
                read_identity.append((int(row[0]), str(row[1]), str(row[2])))
            return result

    class ProxyEngine:
        def connect(self):
            return ProxyConn(real_engine.connect())

    real_copy = data_sql.copy_write_stage

    def copy_write_stage(conn, *args, **kwargs):
        write_pids.append(int(conn.execute(text("SELECT pg_backend_pid()")).scalar_one()))
        return real_copy(conn, *args, **kwargs)

    real_write = write_rows

    def wrapped_write(*args, **kwargs):
        assert not isinstance(kwargs["rows"], (list, tuple))
        return real_write(*args, **kwargs)

    monkeypatch.setattr("backend.entity.datasets.get_entity_engine", lambda: ProxyEngine())
    monkeypatch.setattr("backend.entity.data.sql.copy_write_stage", copy_write_stage)
    monkeypatch.setattr("backend.channel.nodes.write.entity.write_rows", wrapped_write)
    result = _run(
        entity_id,
        json.dumps(
            {
                "dataset_id": record.id,
                "columns": [{"name": "product_code", "type": "string"}],
                "count": 0,
            }
        ),
        admin,
    )
    assert result.status == "succeeded", result.error_message
    assert _five(result) == (5, 0, 0, 0, 0)
    readonly = [sql for sql in events if "SET TRANSACTION" in sql.upper()]
    assert len(readonly) == 1
    assert readonly[0].upper().count("READ ONLY") == 1
    pages = [sql for sql in events if "LIMIT" in sql]
    assert len(pages) == 3
    assert all("channel_dataset" in sql for sql in pages)
    assert read_identity == [(read_identity[0][0], "refraq_entity_owner", "on")]
    assert write_pids
    assert set(write_pids) == {write_pids[0]}
    assert write_pids[0] != read_identity[0][0]
