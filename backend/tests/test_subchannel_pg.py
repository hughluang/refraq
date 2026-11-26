"""PostgreSQL + Redis integration tests for Sub Data Channels."""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.tests.entity_pg import bootstrapped_entity_database

pytestmark = pytest.mark.integration

INTEGRATION_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)
INTEGRATION_REDIS_URL = os.getenv(
    "REFRAQ_INTEGRATION_REDIS_URL",
    "redis://127.0.0.1:6379/1",
)
_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)


def _services_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        from redis import Redis

        client = Redis.from_url(INTEGRATION_REDIS_URL)
        client.ping()
        client.close()
    except Exception:
        return False
    return True


def _ensure_database() -> None:
    from sqlalchemy.engine import make_url

    db_name = make_url(INTEGRATION_DATABASE_URL).database
    admin_url = make_url(_MAINTENANCE_DATABASE_URL).set(database="postgres")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()


@pytest.fixture
def pg_subchannel_client(monkeypatch: pytest.MonkeyPatch):
    if not _services_available():
        pytest.skip("Postgres/Redis not available (start: docker compose up -d)")

    _ensure_database()
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_subch") as urls:
        monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
        monkeypatch.setenv("DATABASE_URL", INTEGRATION_DATABASE_URL)
        monkeypatch.setenv("REDIS_URL", INTEGRATION_REDIS_URL)
        monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
        monkeypatch.setenv("REFRAQ_SKIP_SEED", "0")
        monkeypatch.setenv("INITIAL_ADMIN_ACCOUNT", "root")
        monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "s3cret")
        monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
        monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
        monkeypatch.setattr("backend.channel.runs.dispatch", lambda job_id: None)

        from backend.admin.role_store import reset_role_store
        from backend.admin.session_store import reset_session_store
        from backend.admin.user_store import reset_user_store
        from backend.channel.dataset_registry import reset_dataset_store
        from backend.channel.store import reset_channel_store
        from backend.core.config import reset_settings_cache
        from backend.core.db import reset_db_singletons
        from backend.core.entry import migrate_with_advisory_lock
        from backend.core.redis_client import reset_redis_singleton
        from backend.entity.entity_db import reset_entity_engine
        from backend.jobs.store import reset_job_store
        from backend.worker.parameters import assemble_system_parameters
        import backend.channel.run_store as run_store_mod

        reset_settings_cache()
        reset_db_singletons()
        reset_entity_engine()
        reset_redis_singleton()
        reset_user_store()
        reset_role_store()
        reset_session_store()
        reset_channel_store()
        reset_job_store()
        reset_dataset_store()
        with run_store_mod._lock:
            run_store_mod._memory = None

        migrate_with_advisory_lock(INTEGRATION_DATABASE_URL)
        assemble_system_parameters()

        engine = create_engine(INTEGRATION_DATABASE_URL)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE users, roles, channels, channel_versions,"
                    " channel_variables, channel_runs, channel_datasets, jobs"
                    " RESTART IDENTITY CASCADE"
                )
            )
        engine.dispose()

        from redis import Redis

        redis = Redis.from_url(INTEGRATION_REDIS_URL)
        redis.flushdb()
        redis.close()

        import backend.main as main_mod

        reset_settings_cache()
        reset_channel_store()
        main_mod.settings = main_mod.get_settings()
        main_mod._bootstrap_site(main_mod.settings)

        with TestClient(main_mod.app) as client:
            login = client.post(
                "/auth/login", json={"account": "root", "password": "s3cret"}
            )
            assert login.status_code == 200, login.text
            yield client

        reset_dataset_store()
        reset_job_store()
        reset_entity_engine()
        reset_user_store()
        reset_role_store()
        reset_session_store()
        reset_channel_store()
        reset_db_singletons()
        reset_redis_singleton()
        reset_settings_cache()
        with run_store_mod._lock:
            run_store_mod._memory = None


def _create_publish_activate(
    client: TestClient,
    name: str,
    graph: dict[str, Any],
    *,
    active: bool = True,
) -> str:
    created = client.post("/channels", json={"name": name, "description": None})
    assert created.status_code == 201, created.text
    cid = created.json()["channel"]["id"]
    saved = client.put(
        f"/channels/{cid}/draft",
        json={"base_revision": 1, "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    pub = client.post(f"/channels/{cid}/publish", json={"draft_revision": 2})
    assert pub.status_code == 201, pub.text
    if active:
        act = client.post(f"/channels/{cid}/activate")
        assert act.status_code == 200, act.text
    return cid


def test_subchannel_pg_bidirectional_dataset_sharing_and_child_keeping(
    pg_subchannel_client: TestClient,
) -> None:
    """Parent passes physical PG Dataset into Sub-channel; Sub-channel transforms & returns new PG Dataset even with keep_succeeded_runs=False."""
    from backend.channel.runner import run_channel_job

    sub_graph = {
        "nodes": [
            {
                "id": "nd_sub_trig",
                "ref": "sub_trig",
                "type": "trigger.subchannel",
                "type_version": 1,
                "name": "Sub Trigger",
                "position": {"x": 0, "y": 0},
                "config": {
                    "input": [
                        {"name": "src_ds", "type": "dataset", "required": True},
                    ],
                    "sample_input": {},
                },
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_dq",
                "ref": "double_ds",
                "type": "volume.dataset_query",
                "type_version": 1,
                "name": "Double Qty",
                "position": {"x": 240, "y": 0},
                "config": {
                    "source": {"kind": "entity"},
                    "sql": "SELECT sku, qty * 2 AS doubled FROM incoming_rows ORDER BY sku",
                    "datasets": {
                        "incoming_rows": "{{ self.sub_trig.output.src_ds }}",
                    },
                },
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_ret",
                "ref": "ret_ds",
                "type": "action.return",
                "type_version": 1,
                "name": "Return Dataset",
                "position": {"x": 480, "y": 0},
                "config": {
                    "value": "{{ self.double_ds.output.dataset }}",
                },
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": {"node_id": "nd_sub_trig", "port": "main"},
                "target": {"node_id": "nd_dq", "port": "main"},
            },
            {
                "id": "e2",
                "source": {"node_id": "nd_dq", "port": "main"},
                "target": {"node_id": "nd_ret", "port": "main"},
            },
        ],
        "settings": {
            "run_timeout_sec": 60,
            "error_channel_id": None,
            "keep_succeeded_runs": False,
        },
    }
    sub_id = _create_publish_activate(pg_subchannel_client, "Dataset Doubler Sub", sub_graph)

    parent_graph = {
        "nodes": [
            {
                "id": "nd_trig",
                "ref": "start",
                "type": "trigger.manual",
                "type_version": 1,
                "name": "Start",
                "position": {"x": 0, "y": 0},
                "config": {"payload": {}},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_mat",
                "ref": "mat",
                "type": "volume.materialize",
                "type_version": 1,
                "name": "Materialize",
                "position": {"x": 220, "y": 0},
                "config": {
                    "items": '[{"sku": "A1", "qty": 5}, {"sku": "B2", "qty": 7}]',
                },
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_call",
                "ref": "call_sub",
                "type": "action.call_channel",
                "type_version": 1,
                "name": "Call Doubler",
                "position": {"x": 440, "y": 0},
                "config": {
                    "channel_id": sub_id,
                    "inputs": {
                        "src_ds": "{{ self.mat.output.dataset }}",
                    },
                },
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_sql_verify",
                "ref": "verify_rows",
                "type": "read.sql",
                "type_version": 1,
                "name": "Verify Returned Dataset",
                "position": {"x": 660, "y": 0},
                "config": {
                    "source": {"kind": "entity"},
                    "sql": "SELECT sku, doubled FROM child_out ORDER BY sku",
                    "datasets": {
                        "child_out": "{{ self.call_sub.output.result }}",
                    },
                },
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "pe1",
                "source": {"node_id": "nd_trig", "port": "main"},
                "target": {"node_id": "nd_mat", "port": "main"},
            },
            {
                "id": "pe2",
                "source": {"node_id": "nd_mat", "port": "main"},
                "target": {"node_id": "nd_call", "port": "main"},
            },
            {
                "id": "pe3",
                "source": {"node_id": "nd_call", "port": "main"},
                "target": {"node_id": "nd_sql_verify", "port": "main"},
            },
        ],
        "settings": {"run_timeout_sec": 60, "error_channel_id": None},
    }
    parent_id = _create_publish_activate(pg_subchannel_client, "Parent Dataset Pipeline", parent_graph)

    started = pg_subchannel_client.post(
        f"/channels/{parent_id}/runs",
        json={"target": "published", "ignore_checkpoints": False},
    )
    assert started.status_code == 202, started.text
    parent_job_id = started.json()["run"]["job_id"]

    run_channel_job(parent_job_id)

    detail = pg_subchannel_client.get(f"/channels/{parent_id}/runs/{parent_job_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded", detail.json()

    execs = pg_subchannel_client.get(
        f"/channels/{parent_id}/runs/{parent_job_id}/executions"
    ).json()["items"]
    by_node = {item["node_id"]: item for item in execs}
    verify_out = by_node["nd_sql_verify"]["output_preview"]
    assert verify_out["rows"] == [
        {"sku": "A1", "doubled": 10},
        {"sku": "B2", "doubled": 14},
    ]

    returned_ds = by_node["nd_call"]["output_preview"]["result"]
    ds_rows = pg_subchannel_client.get(
        f"/channels/{parent_id}/runs/{parent_job_id}/datasets/{returned_ds['dataset_id']}/rows"
    )
    assert ds_rows.status_code == 200, ds_rows.text
    assert ds_rows.json()["items"] == [
        {"_ord": 1, "sku": "A1", "doubled": 10},
        {"_ord": 2, "sku": "B2", "doubled": 14},
    ]

    # Child run had keep_succeeded_runs=False, so child run history is empty while dataset survived for parent!
    sub_runs = pg_subchannel_client.get(f"/channels/{sub_id}/runs").json()
    assert sub_runs["total"] == 0


def test_subchannel_pg_call_tree_sql_queries_and_redis_concurrency(
    pg_subchannel_client: TestClient,
) -> None:
    """SQL filter published_trigger_type, 409 CHANNEL_IN_USE guards, caller projection, and Postgres advisory concurrency lock."""
    from backend.channel.locks import try_acquire_channel_run_lock
    from backend.channel.runner import run_channel_job

    sub_graph = {
        "nodes": [
            {
                "id": "nd_sub_trig",
                "ref": "sub_trig",
                "type": "trigger.subchannel",
                "type_version": 1,
                "name": "Sub Trigger",
                "position": {"x": 0, "y": 0},
                "config": {
                    "input": [
                        {"name": "msg", "type": "string", "required": True},
                    ],
                    "sample_input": {"msg": "hello"},
                },
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_ret",
                "ref": "ret",
                "type": "action.return",
                "type_version": 1,
                "name": "Return",
                "position": {"x": 240, "y": 0},
                "config": {"value": "{{ {'echo': self.sub_trig.output.msg} }}"},
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": {"node_id": "nd_sub_trig", "port": "main"},
                "target": {"node_id": "nd_ret", "port": "main"},
            },
        ],
        "settings": {
            "run_timeout_sec": 60,
            "error_channel_id": None,
            "concurrency": "forbid",
        },
    }
    sub_id = _create_publish_activate(pg_subchannel_client, "Echo Sub", sub_graph)

    caller_graph = {
        "nodes": [
            {
                "id": "nd_trig",
                "ref": "start",
                "type": "trigger.manual",
                "type_version": 1,
                "name": "Start",
                "position": {"x": 0, "y": 0},
                "config": {"payload": {}},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_call",
                "ref": "call_echo",
                "type": "action.call_channel",
                "type_version": 1,
                "name": "Call Echo",
                "position": {"x": 240, "y": 0},
                "config": {
                    "channel_id": sub_id,
                    "inputs": {"msg": "ping"},
                },
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "pe1",
                "source": {"node_id": "nd_trig", "port": "main"},
                "target": {"node_id": "nd_call", "port": "main"},
            },
        ],
        "settings": {"run_timeout_sec": 60, "error_channel_id": None},
    }
    caller_id = _create_publish_activate(pg_subchannel_client, "Caller Channel", caller_graph)

    # 1. SQL filter published_trigger_type=trigger.subchannel
    filtered = pg_subchannel_client.get(
        "/channels", params={"published_trigger_type": "trigger.subchannel"}
    )
    assert filtered.status_code == 200
    items = filtered.json()["items"]
    assert [c["id"] for c in items] == [sub_id]
    assert items[0]["latest_version"]["trigger_type"] == "trigger.subchannel"

    # 2. SQL 409 CHANNEL_IN_USE on delete and trigger-type replacement
    del_resp = pg_subchannel_client.delete(f"/channels/{sub_id}")
    assert del_resp.status_code == 409
    assert del_resp.json()["code"] == "CHANNEL_IN_USE"

    # 3. Normal call persists parent_job_id, root_job_id, return_value, and caller projection in PG
    run1 = pg_subchannel_client.post(
        f"/channels/{caller_id}/runs",
        json={"target": "published", "ignore_checkpoints": False},
    ).json()["run"]["job_id"]
    run_channel_job(run1)

    sub_runs = pg_subchannel_client.get(f"/channels/{sub_id}/runs").json()["items"]
    assert len(sub_runs) == 1
    child_run = sub_runs[0]
    assert child_run["parent_job_id"] == run1
    assert child_run["root_job_id"] == run1
    assert child_run["caller"] is None
    child_detail = pg_subchannel_client.get(
        f"/channels/{sub_id}/runs/{child_run['job_id']}"
    ).json()["run"]
    assert child_detail["return_value"] == {"echo": "ping"}
    assert child_detail["caller"] == {
        "job_id": run1,
        "channel_id": caller_id,
        "channel_name": "Caller Channel",
        "node_id": "nd_call",
    }

    # 4. Real Postgres advisory lock concurrency="forbid" returns outcome="skipped"
    held = try_acquire_channel_run_lock(sub_id)
    assert held is not None
    try:
        run2 = pg_subchannel_client.post(
            f"/channels/{caller_id}/runs",
            json={"target": "published", "ignore_checkpoints": False},
        ).json()["run"]["job_id"]
        run_channel_job(run2)
    finally:
        held.release()

    execs2 = pg_subchannel_client.get(
        f"/channels/{caller_id}/runs/{run2}/executions"
    ).json()["items"]
    call_out2 = next(e for e in execs2 if e["node_id"] == "nd_call")["output_preview"]
    assert call_out2["outcome"] == "skipped"
    assert call_out2["result"] is None
