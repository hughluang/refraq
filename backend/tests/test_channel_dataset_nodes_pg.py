"""Dataset Query and Materialize. Postgres cases use a throwaway entity database."""

from __future__ import annotations

import importlib
import os

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine, text

from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA
from backend.channel.nodes import list_node_types
from backend.tests.channel_hooks_fake import FakeHooks
from backend.tests.entity_pg import bootstrapped_entity_database

_MAINTENANCE = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_LIST_LIMIT = "Use Materialize or Dataset Query, then Batch Read."


def _execute(type_id: str):
    return next(item.execute for item in list_node_types() if item.type_id == type_id)


def _query(sql: str, *, timeout: int = 300, node_id: str = "nd_query") -> dict:
    config: dict = {"source": {"kind": "entity"}, "sql": sql}
    if timeout != 300:
        config["statement_timeout_sec"] = timeout
    return {"id": node_id, "type": "volume.dataset_query", "config": config}


def test_item_limit_has_one_definition() -> None:
    from backend.channel import item_limit, sql_read
    from backend.channel.nodes.write import entity as write_entity

    modules = [
        sql_read,
        write_entity,
        importlib.import_module("backend.channel.nodes.volume.for"),
        importlib.import_module("backend.channel.nodes.volume.materialize"),
        importlib.import_module("backend.channel.nodes.transform.filter"),
        importlib.import_module("backend.channel.nodes.transform.merge"),
        importlib.import_module("backend.channel.nodes.transform.deduplicate"),
    ]
    assert item_limit.ITEM_LIMIT == 100_000
    for module in modules:
        assert module.ITEM_LIMIT is item_limit.ITEM_LIMIT


def test_dataset_query_rejects_more_than_one_external_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rendered external SQL is counted in the source dialect before any connector."""
    from backend.core.time import utc_now
    from backend.metadata.sources.store import SourceRecord, get_source_store

    def forbid(*_args, **_kwargs):
        raise AssertionError("source connector was called")

    monkeypatch.setattr("backend.metadata.connectors.runtime.prepare", forbid)
    monkeypatch.setattr("backend.metadata.source_statements.prepare", forbid)
    monkeypatch.setattr(
        "backend.channel.dataset_registry.DatasetRegistry.create_from_query",
        forbid,
    )
    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id="src_live",
            key="live",
            locator_key="src/postgresql/live",
            name="Live",
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext="sealed",
            access_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    seen: list[str] = []

    def evaluate(expression: str) -> str:
        seen.append(expression)
        return "SELECT 1; SELECT 2"

    result = _execute("volume.dataset_query")(
        {
            "id": "nd_query",
            "type": "volume.dataset_query",
            "config": {
                "source": {"kind": "source", "source_id": "src_live"},
                "sql": "{{ body }}",
            },
        },
        FakeHooks(evaluate=evaluate),
    )
    assert seen == ["body"]
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_SQL_NOT_ONE_STATEMENT"
    assert result.error_message == "SQL must be exactly one statement"


def test_dataset_query_rejects_more_than_one_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid(*_args, **_kwargs):
        raise AssertionError("query ran")

    monkeypatch.setattr(
        "backend.channel.dataset_registry.DatasetRegistry.create_from_query",
        forbid,
    )
    result = _execute("volume.dataset_query")(
        _query("SELECT 1; SELECT 2"),
        FakeHooks(),
    )
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_SQL_NOT_ONE_STATEMENT"
    assert result.error_message == "SQL must be exactly one statement"


def test_materialize_rejects_an_empty_list_a_order_column_and_the_item_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = _execute("volume.materialize")(
        {"id": "nd_empty", "type": "volume.materialize", "config": {"items": "[]"}},
        FakeHooks(),
    )
    assert empty.status == "failed"
    assert empty.error_code == "CHANNEL_NODE_FAILED"
    assert empty.error_message == "Materialize list has no fields"

    collision = _execute("volume.materialize")(
        {
            "id": "nd_ord",
            "type": "volume.materialize",
            "config": {"items": '[{"_ord": 1}]'},
        },
        FakeHooks(),
    )
    assert collision.status == "failed"
    assert collision.error_message == "Column name _ord collides with the dataset order column"

    monkeypatch.setattr("backend.channel.nodes.volume.materialize.ITEM_LIMIT", 1)
    limited = _execute("volume.materialize")(
        {"id": "nd_load", "type": "volume.materialize", "config": {"items": "{{ rows }}"}},
        FakeHooks(evaluate=lambda _expression: [{"n": 1}, {"n": 2}]),
    )
    assert limited.status == "failed"
    assert limited.error_code == "CHANNEL_ITEM_LIMIT_EXCEEDED"
    assert limited.error_message == _LIST_LIMIT


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture
def entity_db(monkeypatch: pytest.MonkeyPatch):
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE, "refraq_dnode") as urls:
        monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
        monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
        from backend.admin.system_parameters import reset_parameter_registry
        from backend.channel.dataset_registry import reset_dataset_store
        from backend.core.config import reset_settings_cache
        from backend.entity.entity_db import get_entity_engine, reset_entity_engine
        from backend.worker.parameters import assemble_system_parameters

        reset_settings_cache()
        reset_entity_engine()
        assemble_system_parameters()
        reset_dataset_store()
        with get_entity_engine().begin() as conn:
            conn.exec_driver_sql("CREATE TABLE entity_data.probe (code text)")
            conn.exec_driver_sql("INSERT INTO entity_data.probe (code) VALUES ('kept')")
        try:
            yield
        finally:
            reset_dataset_store()
            reset_parameter_registry()
            reset_entity_engine()
            reset_settings_cache()


def _page(dataset_id: str, *, after_ord: int, limit: int) -> list[dict]:
    from backend.channel.dataset_registry import DatasetRegistry, get_dataset_store

    return DatasetRegistry(get_dataset_store()).read_page(
        dataset_id, after_ord=after_ord, limit=limit
    )


def _record(dataset_id: str):
    from backend.channel.dataset_registry import get_dataset_store

    return get_dataset_store().get(dataset_id)


@pytest.mark.integration
def test_dataset_query_loads_entity_data_and_pages_arrival_order(
    entity_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.channel.dataset_registry as registry_mod

    def forbid(*_args, **_kwargs):
        raise AssertionError("execute_entity_statement was called")

    monkeypatch.setattr("backend.entity.statements.execute_entity_statement", forbid)
    queries: list[str] = []
    real = registry_mod.create_table_from_query

    def wrapped(relation: str, query: str) -> tuple[int, int]:
        queries.append(query)
        return real(relation, query)

    monkeypatch.setattr(registry_mod, "create_table_from_query", wrapped)
    hooks = FakeHooks(run_id="job_dataset_query")
    loaded = _execute("volume.dataset_query")(
        _query(
            "SELECT code, current_setting('search_path') AS path, "
            "current_setting('statement_timeout') AS timeout FROM probe",
            timeout=42,
            node_id="nd_probe",
        ),
        hooks,
    )
    assert loaded.status == "succeeded", loaded.error_message
    probe = loaded.output
    Draft202012Validator(DATASET_REFERENCE_SCHEMA).validate(probe["dataset"])
    assert "relation" not in probe["dataset"]
    assert probe["count"] == probe["dataset"]["count"] == 1
    assert probe["dataset"]["columns"] == [
        {
            "name": "code",
            "type": "string",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "path",
            "type": "string",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "timeout",
            "type": "string",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
    ]
    stored = _record(probe["dataset"]["dataset_id"])
    assert stored is not None
    assert {column["name"]: column["type"] for column in stored.columns} == {
        "code": "text",
        "path": "text",
        "timeout": "text",
    }
    page = _page(probe["dataset"]["dataset_id"], after_ord=0, limit=1)
    assert page[0]["code"] == "kept"
    assert page[0]["path"] == "entity_data"
    assert "42" in str(page[0]["timeout"])
    assert queries[0].startswith("SELECT code")
    assert "CREATE" not in queries[0].upper()

    ordered = _execute("volume.dataset_query")(
        _query(
            "SELECT n, label FROM (VALUES (1, 'a'), (2, 'b'), (3, 'c')) AS t(n, label)",
            timeout=42,
            node_id="nd_values",
        ),
        hooks,
    )
    assert ordered.status == "succeeded", ordered.error_message
    dataset = ordered.output["dataset"]
    Draft202012Validator(DATASET_REFERENCE_SCHEMA).validate(dataset)
    assert dataset["columns"] == [
        {
            "name": "n",
            "type": "integer",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "label",
            "type": "string",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
    ]
    assert ordered.output["count"] == 3
    first = _page(dataset["dataset_id"], after_ord=0, limit=2)
    second = _page(dataset["dataset_id"], after_ord=2, limit=2)
    assert [(row["_ord"], row["n"], row["label"]) for row in first] == [
        (1, 1, "a"),
        (2, 2, "b"),
    ]
    assert [(row["_ord"], row["n"], row["label"]) for row in second] == [(3, 3, "c")]


@pytest.mark.integration
def test_dataset_query_rejects_writes_order_collisions_and_a_short_timeout(
    entity_db,
) -> None:
    from backend.entity.datasets import list_dataset_relations
    from backend.entity.entity_db import get_entity_engine

    hooks = FakeHooks(run_id="job_dataset_reject")
    written = _execute("volume.dataset_query")(
        _query("INSERT INTO probe (code) VALUES ('z')", node_id="nd_write"),
        hooks,
    )
    assert written.status == "failed"
    assert written.error_code == "CHANNEL_NODE_FAILED"
    assert written.error_message == "dataset query must be one SELECT"
    with get_entity_engine().connect() as conn:
        left = conn.execute(text("SELECT count(*) FROM entity_data.probe")).scalar_one()
    assert left == 1

    collided = _execute("volume.dataset_query")(
        _query("SELECT 1 AS _ord", node_id="nd_ord"),
        hooks,
    )
    assert collided.status == "failed"
    assert collided.error_code == "CHANNEL_NODE_FAILED"
    assert "_ord" in (collided.error_message or "")

    timed = _execute("volume.dataset_query")(
        _query("SELECT pg_sleep(5)", timeout=1, node_id="nd_sleep"),
        hooks,
    )
    assert timed.status == "failed"
    assert timed.error_code == "CHANNEL_NODE_FAILED"
    assert list_dataset_relations() == []


@pytest.mark.integration
def test_dataset_query_fails_when_capacity_is_already_full(
    entity_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.channel.dataset_registry import DatasetRecord, get_dataset_store
    from backend.core.time import utc_now
    from backend.entity.datasets import list_dataset_relations, physical_relation

    monkeypatch.setattr(
        "backend.channel.dataset_registry.channel_dataset_max_total_gb",
        lambda: 1,
    )

    def forbid(relation: str, query: str) -> tuple[int, int]:
        raise AssertionError(f"created {relation} {query}")

    monkeypatch.setattr("backend.channel.dataset_registry.create_table_from_query", forbid)
    get_dataset_store().save(
        DatasetRecord(
            id="dplanted",
            job_id="job_other",
            node_id="nd_other",
            seq=1,
            relation=physical_relation("dplanted"),
            columns=[],
            row_count=0,
            size_bytes=1024**3,
            status="ready",
            created_at=utc_now(),
        )
    )
    result = _execute("volume.dataset_query")(
        _query("SELECT 1 AS n", node_id="nd_quota"),
        FakeHooks(run_id="job_dataset_quota"),
    )
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_DATASET_QUOTA_EXCEEDED"
    assert list_dataset_relations() == []


@pytest.mark.integration
def test_materialize_infers_types_and_copies_chunks(
    entity_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend.channel.dataset_registry as registry_mod

    seen: list[list[int]] = []
    real = registry_mod.copy_chunks

    def spy(relation, columns, chunks, on_chunk_size=None):
        listed = [list(chunk) for chunk in chunks]
        seen.append([len(chunk) for chunk in listed])
        return real(relation, columns, listed, on_chunk_size=on_chunk_size)

    monkeypatch.setattr(registry_mod, "copy_chunks", spy)
    monkeypatch.setattr("backend.channel.nodes.volume.materialize._CHUNK_ROWS", 1)
    big = 2**63
    rows = [
        {
            "flag": True,
            "n": 1,
            "qty": 1.5,
            "name": "a",
            "big": big,
            "payload": {"k": 1},
            "tags": [1],
            "mixed": 1,
            "blank": None,
        },
        {
            "flag": False,
            "n": 2,
            "qty": 2,
            "name": "b",
            "big": 3,
            "payload": [1],
            "tags": [],
            "mixed": "x",
            "blank": None,
        },
    ]
    result = _execute("volume.materialize")(
        {"id": "nd_load", "type": "volume.materialize", "config": {"items": "{{ rows }}"}},
        FakeHooks(run_id="job_materialize", evaluate=lambda _expression: rows),
    )
    assert result.status == "succeeded", result.error_message
    dataset = result.output["dataset"]
    Draft202012Validator(DATASET_REFERENCE_SCHEMA).validate(dataset)
    assert result.output["count"] == dataset["count"] == 2
    assert dataset["columns"] == [
        {
            "name": "flag",
            "type": "boolean",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "n",
            "type": "integer",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "qty",
            "type": "number",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "name",
            "type": "string",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "big",
            "type": "decimal",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "payload",
            "type": "json",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "tags",
            "type": "json",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "mixed",
            "type": "json",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
        {
            "name": "blank",
            "type": "string",
            "temporal_kind": None,
            "precision": None,
            "nullable": None,
        },
    ]
    stored = _record(dataset["dataset_id"])
    assert stored is not None
    assert [column["type"] for column in stored.columns] == [
        "boolean",
        "bigint",
        "double precision",
        "text",
        "numeric",
        "jsonb",
        "jsonb",
        "jsonb",
        "text",
    ]
    assert seen == [[1, 1]]
    first = _page(dataset["dataset_id"], after_ord=0, limit=1)
    second = _page(dataset["dataset_id"], after_ord=1, limit=1)
    assert first[0]["_ord"] == 1
    assert first[0]["flag"] is True
    assert first[0]["n"] == 1
    assert first[0]["qty"] == 1.5
    assert first[0]["name"] == "a"
    assert int(first[0]["big"]) == big
    assert first[0]["payload"] == {"k": 1}
    assert first[0]["tags"] == [1]
    assert first[0]["mixed"] == 1
    assert first[0]["blank"] is None
    assert second[0]["_ord"] == 2
    assert second[0]["flag"] is False
    assert second[0]["qty"] == 2.0
    assert int(second[0]["big"]) == 3
    assert second[0]["payload"] == [1]
    assert second[0]["mixed"] == "x"
