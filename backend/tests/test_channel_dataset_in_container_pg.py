"""Dataset Query and Materialize inside a container. Each execution owns one table.

Postgres cases use a throwaway entity database. They skip when Postgres is down.
"""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import create_engine, text

from backend.channel.dataset_registry import (
    DatasetColumnSpec,
    DatasetRegistry,
    get_dataset_store,
    reset_dataset_store,
)
from backend.channel.engine import execute
from backend.channel.graph import validate
from backend.channel.nodes import list_node_types
from backend.entity.datasets import list_dataset_relations
from backend.tests.entity_pg import bootstrapped_entity_database
from backend.tests.test_channel_engine import _RESOLVER, _edge, _node
from backend.tests.test_channel_until import RecordingHooks

_MAINTENANCE = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_CATALOG = list_node_types()


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
    with bootstrapped_entity_database(_MAINTENANCE, "refraq_dcont") as urls:
        monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
        monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
        from backend.admin.system_parameters import reset_parameter_registry
        from backend.core.config import reset_settings_cache
        from backend.entity.entity_db import reset_entity_engine
        from backend.worker.parameters import assemble_system_parameters

        reset_settings_cache()
        reset_entity_engine()
        assemble_system_parameters()
        reset_dataset_store()
        try:
            yield
        finally:
            reset_dataset_store()
            reset_parameter_registry()
            reset_entity_engine()
            reset_settings_cache()


def _errors(graph: dict) -> list[str]:
    return [
        f"{item.code} {item.node_id} {item.detail}"
        for item in validate(graph, _RESOLVER, _CATALOG)
        if item.severity == "error"
    ]


def _run(graph: dict, start: str, run_id: str):
    hooks = RecordingHooks(run_id=run_id)
    outcome = execute(graph, start, _CATALOG, _RESOLVER, hooks)
    return outcome, hooks


def _succeeded(hooks: RecordingHooks, node_id: str) -> list[dict]:
    return [
        result.output
        for item_id, result in hooks.finished
        if item_id == node_id and result.status == "succeeded" and isinstance(result.output, dict)
    ]


def _ids(outputs: list[dict]) -> list[str]:
    return [str(item["dataset"]["dataset_id"]) for item in outputs]


def _assert_table(dataset_id: str, expected_n: int) -> str:
    record = get_dataset_store().get(dataset_id)
    assert record is not None
    assert record.status == "ready"
    assert record.expires_at is None
    assert record.relation in list_dataset_relations()
    page = DatasetRegistry(get_dataset_store()).read_page(dataset_id, after_ord=0, limit=10)
    assert [row["n"] for row in page] == [expected_n]
    return record.relation


def _assert_one_table_each(
    pairs: list[tuple[str, int]],
    *,
    also_present: tuple[str, ...] = (),
) -> None:
    """Each execution has its own physical table.

    Row values repeat across rounds, so matching ``n`` does not prove the
    relations differ. ``also_present`` names tables this run planted first.
    """
    relations = [_assert_table(dataset_id, expected) for dataset_id, expected in pairs]
    assert len(relations) == len(set(relations))
    assert set(relations).isdisjoint(also_present)
    assert set(list_dataset_relations()) == set(relations).union(also_present)


def _mark(node_id: str, y: float, *, parent: str, source_ref: str) -> dict:
    node = _node(node_id, y, type_id="transform.set_fields", parent=parent)
    node["config"] = {
        "fields": [{"name": "n", "value": f"{{{{ self.{source_ref}.output.index }}}}"}]
    }
    return node


def _query(node_id: str, y: float, *, parent: str, sql: str) -> dict:
    node = _node(node_id, y, type_id="volume.dataset_query", parent=parent)
    node["config"] = {"source": {"kind": "entity"}, "sql": sql}
    return node


def _load(node_id: str, y: float, *, parent: str, items: str) -> dict:
    node = _node(node_id, y, type_id="volume.materialize", parent=parent)
    node["config"] = {"items": items}
    return node


def _index_sql(ref: str) -> str:
    return f"SELECT {{{{ self.{ref}.output.index }}}} AS n"


def _index_items(ref: str) -> str:
    return f'[{{"n": {{{{ self.{ref}.output.index }}}}}}]'


@pytest.mark.integration
def test_until_rounds_each_create_a_dataset(entity_db) -> None:
    """Two Until rounds land two Dataset Query tables and two Materialize tables."""
    hold = _node("hold", 1, type_id="volume.until")
    hold["config"] = {"until": "{{ self.mark.output.n == 1 }}", "max_iterations": 2}
    graph = {
        "nodes": [
            _node("start", 0, type_id="trigger.manual"),
            hold,
            _mark("mark", 2, parent="hold", source_ref="hold"),
            _query("query", 3, parent="hold", sql=_index_sql("hold")),
            _load("load", 4, parent="hold", items=_index_items("hold")),
        ],
        "edges": [
            _edge("start", "hold"),
            _edge("hold", "mark", "each"),
            _edge("mark", "query"),
            _edge("query", "load"),
        ],
        "settings": {},
    }
    assert _errors(graph) == []
    outcome, hooks = _run(graph, "start", "run_until_datasets")
    assert outcome.status == "succeeded", (outcome.error_code, outcome.error_message)
    queries = _succeeded(hooks, "query")
    loads = _succeeded(hooks, "load")
    query_ids = _ids(queries)
    load_ids = _ids(loads)
    assert len(query_ids) == 2
    assert len(load_ids) == 2
    assert len(set(query_ids + load_ids)) == 4
    _assert_one_table_each(
        [*zip(query_ids, (0, 1), strict=True), *zip(load_ids, (0, 1), strict=True)]
    )
    assert hooks.stored("hold")["count"] == 2


@pytest.mark.integration
def test_for_elements_each_create_a_dataset(entity_db) -> None:
    """Two For elements land two Dataset Query tables and two Materialize tables."""
    walk = _node("walk", 1, type_id="volume.for")
    walk["config"] = {"items": "[0, 1]"}
    graph = {
        "nodes": [
            _node("start", 0, type_id="trigger.manual"),
            walk,
            _query("query", 2, parent="walk", sql=_index_sql("walk")),
            _load("load", 3, parent="walk", items=_index_items("walk")),
        ],
        "edges": [
            _edge("start", "walk"),
            _edge("walk", "query", "each"),
            _edge("query", "load"),
        ],
        "settings": {},
    }
    assert _errors(graph) == []
    outcome, hooks = _run(graph, "start", "run_for_datasets")
    assert outcome.status == "succeeded", (outcome.error_code, outcome.error_message)
    query_ids = _ids(_succeeded(hooks, "query"))
    load_ids = _ids(_succeeded(hooks, "load"))
    assert len(query_ids) == 2
    assert len(load_ids) == 2
    assert len(set(query_ids + load_ids)) == 4
    _assert_one_table_each(
        [*zip(query_ids, (0, 1), strict=True), *zip(load_ids, (0, 1), strict=True)]
    )
    assert hooks.stored("walk")["count"] == 2


@pytest.mark.integration
def test_batch_read_rounds_each_create_a_dataset(entity_db) -> None:
    """Two Batch Read pages land two new datasets, distinct from the source."""
    source = DatasetRegistry(get_dataset_store()).create_from_chunks(
        job_id="run_batch_datasets",
        node_id="planted",
        seq=1,
        columns=[DatasetColumnSpec("n", "integer")],
        chunks=[[(10,), (20,)]],
    )
    reference = {
        "dataset_id": source.id,
        "columns": [{"name": "n", "type": "integer"}],
        "count": 2,
    }
    batch = _node("batch", 1, type_id="volume.batch_read")
    batch["config"] = {"dataset": json.dumps(reference), "batch_size": 1}
    graph = {
        "nodes": [
            _node("start", 0, type_id="trigger.manual"),
            batch,
            _query("query", 2, parent="batch", sql=_index_sql("batch")),
            _load("load", 3, parent="batch", items="{{ self.batch.output.rows }}"),
        ],
        "edges": [
            _edge("start", "batch"),
            _edge("batch", "query", "each"),
            _edge("query", "load"),
        ],
        "settings": {},
    }
    assert _errors(graph) == []
    outcome, hooks = _run(graph, "start", "run_batch_datasets")
    assert outcome.status == "succeeded", (outcome.error_code, outcome.error_message)
    query_ids = _ids(_succeeded(hooks, "query"))
    load_ids = _ids(_succeeded(hooks, "load"))
    assert len(query_ids) == 2
    assert len(load_ids) == 2
    assert source.id not in query_ids
    assert source.id not in load_ids
    assert len(set([source.id, *query_ids, *load_ids])) == 5
    _assert_one_table_each(
        [*zip(query_ids, (0, 1), strict=True), *zip(load_ids, (10, 20), strict=True)],
        also_present=(source.relation,),
    )


@pytest.mark.integration
def test_nested_container_does_not_reuse_the_outer_dataset(entity_db) -> None:
    """An inner Until's datasets are not the For round's dataset."""
    walk = _node("walk", 1, type_id="volume.for")
    walk["config"] = {"items": "[7, 8]"}
    inner = _node("inner", 3, type_id="volume.until", parent="walk")
    inner["config"] = {"until": "{{ self.mark.output.n == 1 }}", "max_iterations": 2}
    graph = {
        "nodes": [
            _node("start", 0, type_id="trigger.manual"),
            walk,
            _load("outer", 2, parent="walk", items='[{"n": {{ self.walk.output.current }}}]'),
            inner,
            _mark("mark", 4, parent="inner", source_ref="inner"),
            _query("query", 5, parent="inner", sql=_index_sql("inner")),
        ],
        "edges": [
            _edge("start", "walk"),
            _edge("walk", "outer", "each"),
            _edge("outer", "inner"),
            _edge("inner", "mark", "each"),
            _edge("mark", "query"),
        ],
        "settings": {},
    }
    assert _errors(graph) == []
    outcome, hooks = _run(graph, "start", "run_nested_datasets")
    assert outcome.status == "succeeded", (outcome.error_code, outcome.error_message)
    outer_ids = _ids(_succeeded(hooks, "outer"))
    inner_ids = _ids(_succeeded(hooks, "query"))
    assert len(outer_ids) == 2
    assert len(inner_ids) == 4
    assert set(outer_ids).isdisjoint(inner_ids)
    assert len(set(outer_ids + inner_ids)) == 6
    _assert_one_table_each(
        [*zip(outer_ids, (7, 8), strict=True), *zip(inner_ids, (0, 1, 0, 1), strict=True)]
    )
