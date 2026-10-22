"""Batch Read against a real dataset. The entity database is throwaway."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from backend.channel.dataset_registry import (
    DatasetColumnSpec,
    DatasetRegistry,
    get_dataset_store,
    reset_dataset_store,
)
from backend.channel.engine import execute
from backend.channel.nodes.spec import NodeResult
from backend.tests.channel_hooks_fake import FakeHooks
from backend.tests.entity_pg import bootstrapped_entity_database
from backend.tests.test_channel_engine import _RESOLVER, _edge, _node, _type

_MAINTENANCE = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)


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
    with bootstrapped_entity_database(_MAINTENANCE, "refraq_bread") as urls:
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


@pytest.mark.integration
def test_batch_read_reads_a_real_dataset_in_two_batches(entity_db) -> None:
    import backend.channel.nodes.volume.batch_read as batch_read

    seen = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    record = DatasetRegistry(get_dataset_store()).create_from_chunks(
        job_id="run",
        node_id="nd_load",
        seq=1,
        columns=[
            DatasetColumnSpec("n", "integer"),
            DatasetColumnSpec("amount", "decimal", precision=10, scale=2),
            DatasetColumnSpec("seen", "timestamp", with_time_zone=True),
        ],
        chunks=[
            [
                (1, Decimal("1.50"), seen),
                (2, Decimal("2.00"), seen),
            ],
            [(3, Decimal("3.25"), seen)],
        ],
    )
    assert record.row_count == 3
    reference = {
        "dataset_id": record.id,
        "columns": [
            {"name": "n", "type": "integer"},
            {"name": "amount", "type": "decimal"},
            {"name": "seen", "type": "timestamp"},
        ],
        "count": 3,
    }
    node = _node("batch", 0, type_id="volume.batch_read")
    node["config"] = {"dataset": json.dumps(reference), "batch_size": 2}
    caught: list[dict] = []

    def step(body: dict, hooks) -> NodeResult:
        if body["id"] == "step":
            caught.append(dict(hooks.outputs["batch"]))
        return NodeResult(status="succeeded", output={"id": body["id"]})

    graph = {
        "nodes": [node, _node("step", 1, parent="batch"), _node("after", 2)],
        "edges": [
            _edge("batch", "step", "each"),
            _edge("batch", "after", "done"),
        ],
        "settings": {},
    }
    hooks = FakeHooks(run_id="run")
    outcome = execute(
        graph,
        "batch",
        [batch_read.NODE_TYPE, _type("fake", step)],
        _RESOLVER,
        hooks,
    )
    assert outcome.status == "succeeded", outcome.error_message
    assert caught == [
        {
            "rows": [
                {"n": 1, "amount": "1.50", "seen": "2026-10-22T12:00:00Z"},
                {"n": 2, "amount": "2.00", "seen": "2026-10-22T12:00:00Z"},
            ],
            "index": 0,
            "count": 2,
            "total": 3,
        },
        {
            "rows": [
                {"n": 3, "amount": "3.25", "seen": "2026-10-22T12:00:00Z"},
            ],
            "index": 1,
            "count": 2,
            "total": 3,
        },
    ]
    assert hooks.order == ["batch", "step", "step", "after"]
    assert hooks.outputs["batch"] == {"count": 2, "total": 3, "batch_size": 2}
    assert "iterations" not in hooks.outputs["batch"]
