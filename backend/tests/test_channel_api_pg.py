"""Data Channel definition HTTP against real PostgreSQL."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

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

TRIGGER = {
    "nodes": [
        {
            "id": "nd_trigger",
            "ref": "run_manually",
            "type": "trigger.manual",
            "name": "Run manually",
            "position": {"x": 10, "y": 20},
            "config": {},
            "on_error": "stop",
            "retry": None,
        }
    ],
    "edges": [],
    "settings": {"run_timeout_sec": None, "error_channel_id": None},
}

RENAMED = {
    "nodes": [
        {
            **TRIGGER["nodes"][0],
            "name": "Run later",
        }
    ],
    "edges": [],
    "settings": TRIGGER["settings"],
}


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
def channel_client(monkeypatch: pytest.MonkeyPatch):
    if not _services_available():
        pytest.skip("Postgres/Redis not available (start: docker compose up -d)")

    _ensure_database()
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
    monkeypatch.setenv("DATABASE_URL", INTEGRATION_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", INTEGRATION_REDIS_URL)
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.setenv("REFRAQ_SKIP_SEED", "0")
    monkeypatch.setenv("INITIAL_ADMIN_ACCOUNT", "root")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "s3cret")
    from backend.core.config import get_settings, reset_settings_cache

    reset_settings_cache()
    loaded = get_settings()
    owner_url = loaded.entity_database_url
    reader_url = loaded.entity_reader_database_url or owner_url
    if not owner_url or not reader_url:
        pytest.skip("ENTITY_DATABASE_URL is not configured")
    monkeypatch.setenv("ENTITY_DATABASE_URL", owner_url)

    from backend.channel.store import reset_channel_store
    from backend.admin.role_store import reset_role_store
    from backend.admin.session_store import reset_session_store
    from backend.admin.user_store import reset_user_store
    from backend.core.config import reset_settings_cache
    from backend.core.db import reset_db_singletons
    from backend.core.entry import migrate_with_advisory_lock
    from backend.core.redis_client import reset_redis_singleton

    reset_settings_cache()
    reset_db_singletons()
    reset_redis_singleton()
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_channel_store()
    migrate_with_advisory_lock(INTEGRATION_DATABASE_URL)

    engine = create_engine(INTEGRATION_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE users, roles, channels, channel_versions, channel_variables"
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

    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_channel_store()
    reset_db_singletons()
    reset_redis_singleton()
    reset_settings_cache()


def test_publish_keeps_version_immutable(channel_client: TestClient) -> None:
    created = channel_client.post(
        "/channels", json={"name": "Material master", "description": None}
    )
    assert created.status_code == 201, created.text
    channel = created.json()["channel"]
    assert channel["active"] is False
    channel_id = channel["id"]

    saved = channel_client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": 1, "graph": TRIGGER},
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()["draft_revision"]

    preview = channel_client.post(f"/channels/{channel_id}/publish/preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["mirrors_to_open"] == []
    assert preview.json()["runs_to_cancel"] == []
    assert preview.json()["missing_run_timeout"] is True

    published = channel_client.post(
        f"/channels/{channel_id}/publish",
        json={"draft_revision": revision},
    )
    assert published.status_code == 201, published.text
    body = published.json()
    assert body["version"]["number"] == 1
    assert body["version"]["published_by_name"] == "root"
    assert body["version"]["graph"]["nodes"][0]["name"] == "Run manually"
    assert body["confirmation"]["missing_run_timeout"] is True
    published_graph = body["version"]["graph"]

    later = channel_client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": revision, "graph": RENAMED},
    )
    assert later.status_code == 200, later.text

    stored = channel_client.get(f"/channels/{channel_id}/versions/1")
    assert stored.status_code == 200, stored.text
    assert stored.json()["version"]["graph"] == published_graph

    listing = channel_client.get(f"/channels/{channel_id}/versions")
    assert listing.status_code == 200, listing.text
    item = listing.json()["items"][0]
    assert item["number"] == 1
    assert item["published_by_name"] == "root"
    assert item["published_at"]
    assert "graph" not in item

    current = channel_client.get(f"/channels/{channel_id}")
    assert current.json()["channel"]["active"] is False
    assert current.json()["channel"]["latest_version"]["number"] == 1
    assert current.json()["channel"]["draft_revision"] == later.json()["draft_revision"]


def _save_draft(
    client: TestClient, channel_id: str, graph: dict, *, base_revision: int
) -> int:
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": base_revision, "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    return int(saved.json()["draft_revision"])


def _enqueue_matches_get(client: TestClient, channel_id: str) -> dict:
    queued = client.post(f"/channels/{channel_id}/runs", json={"target": "draft"})
    assert queued.status_code == 202, queued.text
    posted = queued.json()["run"]
    loaded = client.get(f"/channels/{channel_id}/runs/{posted['job_id']}")
    assert loaded.status_code == 200, loaded.text
    stored = loaded.json()["run"]
    assert posted["status"] == stored["status"]
    assert posted["outcome"] == stored["outcome"]
    assert posted["failed_node_id"] == stored["failed_node_id"]
    return posted


def test_enqueue_body_matches_finished_run(channel_client: TestClient) -> None:
    """An on-demand run returns the stored outcome, not the pre-execution record.

    A SQL store runs the Job in a child process, so a parent-process executor
    patch never reaches it. The failing run is a real node error.
    """
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job

    previous = set_dispatcher(run_job)
    try:
        created = channel_client.post(
            "/channels", json={"name": "Enqueue probe", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        revision = _save_draft(channel_client, channel_id, TRIGGER, base_revision=1)

        succeeded = _enqueue_matches_get(channel_client, channel_id)
        assert succeeded["status"] == "succeeded"
        assert succeeded["outcome"] == "completed"
        assert succeeded["failed_node_id"] is None

        failing = {
            "nodes": [
                TRIGGER["nodes"][0],
                {
                    "id": "nd_bad",
                    "ref": "bad",
                    "type": "transform.set_fields",
                    "name": "Bad",
                    "position": {"x": 10, "y": 80},
                    "config": {"fields": [{"name": "n", "value": "{{ 1/0 }}"}]},
                    "on_error": "stop",
                    "retry": None,
                },
            ],
            "edges": [
                {
                    "id": "ed_bad",
                    "source": {"node_id": "nd_trigger", "port": "main"},
                    "target": {"node_id": "nd_bad", "port": "main"},
                }
            ],
            "settings": TRIGGER["settings"],
        }
        _save_draft(channel_client, channel_id, failing, base_revision=revision)
        failed = _enqueue_matches_get(channel_client, channel_id)
        assert failed["status"] == "failed"
        assert failed["outcome"] is None
        assert failed["failed_node_id"] == "nd_bad"
    finally:
        set_dispatcher(previous)


def test_template_preview_reads_the_recorded_run(channel_client: TestClient) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job

    graph = {
        "nodes": [
            TRIGGER["nodes"][0],
            {
                "id": "nd_keep",
                "ref": "keep",
                "type": "state.variable",
                "name": "Keep",
                "position": {"x": 10, "y": 120},
                "config": {
                    "operation": "set",
                    "name": "lease",
                    "value": "{{ [self.run.id, self.run_manually.output.triggered_by.name] }}",
                },
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "ed_keep",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_keep", "port": "main"},
            }
        ],
        "settings": TRIGGER["settings"],
    }
    previous = set_dispatcher(run_job)
    try:
        created = channel_client.post(
            "/channels", json={"name": "Preview probe", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        _save_draft(channel_client, channel_id, graph, base_revision=1)
        queued = channel_client.post(
            f"/channels/{channel_id}/runs",
            json={"target": "draft", "stop_at_node_id": "nd_trigger"},
        )
        assert queued.status_code == 202, queued.text
        run = queued.json()["run"]
        assert run["status"] == "succeeded"
    finally:
        set_dispatcher(previous)
    preview = channel_client.post(
        f"/channels/{channel_id}/runs/{run['job_id']}/template-preview",
        json={"graph": graph, "node_id": "nd_keep", "path": ["value"]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["state"] == "ok"
    assert body["value"] == [run["job_id"], "root"]
    assert body["truncated"] is False
    assert body["scope"] == []
    listed = channel_client.get(
        f"/channels/{channel_id}/runs/{run['job_id']}/executions",
        params={"node_id": "nd_trigger"},
    )
    assert listed.status_code == 200, listed.text
    assert body["bindings"] == [
        {
            "node_id": "nd_trigger",
            "seq": listed.json()["items"][-1]["seq"],
            "source": "execution",
        }
    ]


def test_global_variable_writes_are_atomic(channel_client: TestClient) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from backend.channel.variables import get_variable_store

    del channel_client
    store = get_variable_store()

    def claim(owner: int) -> bool:
        return store.apply(
            operation="set_if_absent", name="once", value={"owner": owner}
        ).applied

    with ThreadPoolExecutor(max_workers=8) as pool:
        winners = list(pool.map(claim, range(8)))
    assert winners.count(True) == 1

    def bump(_: int) -> None:
        for _step in range(20):
            while True:
                current = store.apply(operation="get", name="counter")
                assert current.found
                result = store.apply(
                    operation="compare_and_set",
                    name="counter",
                    value={"n": current.value["n"] + 1},
                    expected=current.value,
                )
                if result.applied:
                    break

    store.apply(operation="set", name="counter", value={"n": 0})
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(bump, range(4)))
    assert store.apply(operation="get", name="counter").value == {"n": 80}


def _string_attr(name: str, *, business_key: bool = False) -> dict:
    return {
        "name": name,
        "type": "string",
        "required": business_key,
        "unique": business_key,
        "indexed": False,
        "business_key": business_key,
        "description": name,
        "config": {"max_length": 64},
    }


def _integer_attr(name: str) -> dict:
    return {
        "name": name,
        "type": "integer",
        "required": False,
        "unique": False,
        "indexed": False,
        "business_key": False,
        "description": name,
        "config": {},
    }


def _publish_entity(client: TestClient, *, table_name: str, name: str, attributes: list) -> str:
    from backend.worker.app import celery_app

    created = client.post(
        "/entities",
        json={
            "table_name": table_name,
            "name": name,
            "description": name,
            "attributes": attributes,
        },
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    previous = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = True
    try:
        published = client.post(
            f"/entities/{entity['id']}/versions/{entity['current_version']['id']}/publish"
        )
    finally:
        celery_app.conf.task_always_eager = previous
    assert published.status_code == 201, published.text
    job = client.get(f"/jobs/{published.json()['job']['id']}")
    assert job.status_code == 200, job.text
    assert job.json()["job"]["status"] == "succeeded", job.text
    return entity["id"]


def _node(
    node_id: str,
    ref: str,
    type_id: str,
    name: str,
    y: int,
    config: dict,
) -> dict:
    return {
        "id": node_id,
        "ref": ref,
        "type": type_id,
        "name": name,
        "position": {"x": 10, "y": y},
        "config": config,
        "on_error": "stop",
        "retry": None,
    }


def _edge(edge_id: str, source: str, target: str, *, source_port: str = "main", target_port: str = "main") -> dict:
    return {
        "id": edge_id,
        "source": {"node_id": source, "port": source_port},
        "target": {"node_id": target, "port": target_port},
    }


def test_merge_entity_reads_write_a_third_entity(channel_client: TestClient) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job

    suffix = uuid.uuid4().hex[:8]
    names = f"nm_{suffix}"
    prices = f"pr_{suffix}"
    target = f"tg_{suffix}"
    previous = set_dispatcher(run_job)
    try:
        names_id = _publish_entity(
            channel_client,
            table_name=names,
            name="Names",
            attributes=[_string_attr("code", business_key=True), _string_attr("name")],
        )
        prices_id = _publish_entity(
            channel_client,
            table_name=prices,
            name="Prices",
            attributes=[_string_attr("code", business_key=True), _integer_attr("price")],
        )
        target_id = _publish_entity(
            channel_client,
            table_name=target,
            name="Priced",
            attributes=[
                _string_attr("code", business_key=True),
                _string_attr("name"),
                _integer_attr("price"),
            ],
        )
        for table, rows in (
            (names, [{"code": "A", "name": " Bolt "}, {"code": "B", "name": "Nut"}]),
            (
                prices,
                [
                    {"code": "A", "price": 10},
                    {"code": "B", "price": 1},
                    {"code": "C", "price": 99},
                ],
            ),
        ):
            for row in rows:
                created = channel_client.post(
                    f"/entities/{table}/create", json={"values": row}
                )
                assert created.status_code == 201, created.text

        created = channel_client.post(
            "/channels", json={"name": "Combine prices", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        graph = {
            "nodes": [
                _node("nd_trigger", "run_manually", "trigger.manual", "Run", 0, {}),
                _node(
                    "nd_names",
                    "names",
                    "read.sql",
                    "Names",
                    40,
                    {
                        "source": {"kind": "entity"},
                        "sql": f"SELECT code, name FROM {names}",
                    },
                ),
                _node(
                    "nd_prices",
                    "prices",
                    "read.sql",
                    "Prices",
                    80,
                    {
                        "source": {"kind": "entity"},
                        "sql": f"SELECT code, price FROM {prices}",
                    },
                ),
                _node(
                    "nd_join",
                    "joined",
                    "transform.merge",
                    "Join",
                    120,
                    {
                        "mode": "by_key",
                        "inputs": [
                            "{{ self.names.output.rows }}",
                            "{{ self.prices.output.rows }}",
                        ],
                        "key": "code",
                        "join": "inner",
                    },
                ),
                _node(
                    "nd_keep",
                    "kept",
                    "transform.filter",
                    "Keep",
                    160,
                    {
                        "items": "{{ self.joined.output.rows }}",
                        "combinator": "all",
                        "conditions": [
                            {"key": "price", "operator": "gt", "value": "5"}
                        ],
                    },
                ),
                _node(
                    "nd_shape",
                    "shape",
                    "transform.set_fields",
                    "Shape",
                    200,
                    {
                        "fields": [
                            {
                                "name": "rows",
                                "value": (
                                    '{{ [dict(r, name=r["name"].strip()) '
                                    "for r in self.kept.output.rows] }}"
                                ),
                            }
                        ]
                    },
                ),
                _node(
                    "nd_write",
                    "written",
                    "write.entity",
                    "Write",
                    240,
                    {
                        "entity_id": target_id,
                        "mode": "upsert",
                        "match_key": None,
                        "source": "{{ self.shape.output.rows }}",
                        "mapping": [],
                        "on_incompatible_head": "fail",
                    },
                ),
            ],
            "edges": [
                _edge("ed_names", "nd_trigger", "nd_names"),
                _edge("ed_prices", "nd_trigger", "nd_prices"),
                _edge("ed_join_names", "nd_names", "nd_join"),
                _edge("ed_join_prices", "nd_prices", "nd_join"),
                _edge("ed_keep", "nd_join", "nd_keep"),
                _edge("ed_shape", "nd_keep", "nd_shape"),
                _edge("ed_write", "nd_shape", "nd_write"),
            ],
            "settings": {"run_timeout_sec": None, "error_channel_id": None},
        }
        _save_draft(channel_client, channel_id, graph, base_revision=1)
        finished = _enqueue_matches_get(channel_client, channel_id)
        assert finished["status"] == "succeeded", finished
        assert finished["outcome"] == "completed"
        del names_id, prices_id

        queried = channel_client.post(f"/entities/{target}/query", json={})
        assert queried.status_code == 200, queried.text
        rows = queried.json()["items"]
        assert len(rows) == 1
        assert rows[0]["code"] == "A"
        assert rows[0]["name"] == "Bolt"
        assert rows[0]["price"] == 10
        assert target_id
    finally:
        set_dispatcher(previous)


def test_if_and_for_run_the_live_branch(channel_client: TestClient) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job

    previous = set_dispatcher(run_job)
    try:
        created = channel_client.post(
            "/channels", json={"name": "Branch and loop", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        graph = {
            "nodes": [
                _node("nd_trigger", "run_manually", "trigger.manual", "Run", 0, {}),
                _node(
                    "nd_gate",
                    "gate",
                    "transform.if",
                    "Gate",
                    40,
                    {"condition": "true"},
                ),
                _node(
                    "nd_walk",
                    "walk",
                    "volume.for",
                    "Walk",
                    80,
                    {"items": "[1, 2]"},
                ),
                {
                    **_node(
                        "nd_step",
                        "step",
                        "transform.set_fields",
                        "Step",
                        120,
                        {
                            "fields": [
                                {
                                    "name": "n",
                                    "value": "{{ self.walk.output.current }}",
                                }
                            ]
                        },
                    ),
                    "parent": "nd_walk",
                },
                _node(
                    "nd_missed",
                    "missed",
                    "transform.set_fields",
                    "Missed",
                    160,
                    {"fields": [{"name": "n", "value": "0"}]},
                ),
            ],
            "edges": [
                _edge("ed_gate", "nd_trigger", "nd_gate"),
                _edge("ed_true", "nd_gate", "nd_walk", source_port="true"),
                _edge("ed_false", "nd_gate", "nd_missed", source_port="false"),
                _edge("ed_each", "nd_walk", "nd_step", source_port="each"),
            ],
            "settings": {"run_timeout_sec": None, "error_channel_id": None},
        }
        _save_draft(channel_client, channel_id, graph, base_revision=1)
        finished = _enqueue_matches_get(channel_client, channel_id)
        assert finished["status"] == "succeeded", finished
        detail = channel_client.get(
            f"/channels/{channel_id}/runs/{finished['job_id']}"
        )
        assert detail.status_code == 200, detail.text
        detail_body = detail.json()
        assert "node_executions" not in detail_body
        summaries = {item["node_id"]: item for item in detail_body["node_summaries"]}
        assert "nd_missed" not in summaries
        assert summaries["nd_step"]["execution_count"] == 2
        assert summaries["nd_walk"]["execution_count"] == 1
        steps = _execution_items(channel_client, channel_id, finished["job_id"], node_id="nd_step")
        assert [item["round"] for item in steps] == [0, 1]
        walk = _execution_items(channel_client, channel_id, finished["job_id"], node_id="nd_walk")
        assert len(walk) == 1
        assert walk[0]["container_seq"] is None
        assert walk[0]["round"] is None
        assert {item["container_seq"] for item in steps} == {walk[0]["seq"]}
        scoped = _execution_items(
            channel_client,
            channel_id,
            finished["job_id"],
            container_seq=walk[0]["seq"],
            round=1,
        )
        assert [item["node_id"] for item in scoped] == ["nd_step"]
        assert scoped[0]["round"] == 1
        assert walk[0]["output_preview"]["iterations"] == [
            {"step": {"n": 1}},
            {"step": {"n": 2}},
        ]
    finally:
        set_dispatcher(previous)


def _physical_rows(entity_id: str) -> list[dict]:
    from sqlalchemy import text

    from backend.entity.entity_db import get_entity_engine
    from backend.entity.rows import head_target

    target = head_target(entity_id)
    assert target is not None
    with get_entity_engine().connect() as conn:
        rows = conn.execute(
            text(f"SELECT * FROM {target.qualified_table} ORDER BY row_id")
        ).mappings().all()
    return [dict(row) for row in rows]


def test_run_record_preview_and_retention(channel_client: TestClient) -> None:
    from datetime import timedelta

    from backend.channel.parameters import channel_run_record_retention_days
    from backend.channel.run_store import (
        ChannelRunRecord,
        get_run_store,
        output_page,
        output_preview,
    )
    from backend.channel.tasks import purge_expired_run_records
    from backend.core.time import utc_now
    from backend.jobs.store import (
        claim_for_execution,
        create_queued_job,
        get_job_store,
        mark_cancelled,
        mark_succeeded,
    )

    created = channel_client.post(
        "/channels", json={"name": "Retention", "description": None}
    )
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    days = channel_run_record_retention_days()
    old = utc_now() - timedelta(days=days + 1)
    recent = utc_now() - timedelta(days=max(days - 1, 0))

    def job(status: str) -> str:
        record = create_queued_job(
            kind="channel_run",
            input={"channel_id": channel_id},
            summary="retention",
        )
        if status == "succeeded":
            assert claim_for_execution(record.id, claimed_by="test") is not None
            assert mark_succeeded(record.id, result={"schema": "channel_run.v1"}) is not None
        elif status == "cancelled":
            assert mark_cancelled(record.id) is not None
        return record.id

    old_done = job("succeeded")
    old_cancelled = job("cancelled")
    unfinished = job("queued")
    recent_done = job("succeeded")
    store = get_run_store()

    def insert(job_id: str, created_at) -> None:
        store.insert_run(
            ChannelRunRecord(
                job_id=job_id,
                channel_id=channel_id,
                target="draft",
                version=None,
                draft_revision=1,
                graph=TRIGGER,
                trigger_node_id="nd_trigger",
                ignore_checkpoints=False,
                outcome="completed",
                failed_node_id=None,
                skipped_node_ids=[],
                created_at=created_at,
            )
        )

    insert(old_done, old)
    insert(old_cancelled, old)
    insert(unfinished, old)
    insert(recent_done, recent)
    old_exec = store.start_execution(old_done, "nd_read")
    old_exec.status = "succeeded"
    old_exec.finished_at = utc_now()
    old_exec.output = {"rows": [{"n": 1}]}
    old_exec.output_bytes = 1
    store.finish_execution(old_exec)
    rows = [{"n": index} for index in range(150)]
    execution = store.start_execution(recent_done, "nd_read")
    execution.status = "succeeded"
    execution.finished_at = utc_now()
    execution.output = {"rows": rows, "count": 150}
    execution.output_bytes = 1
    store.finish_execution(execution)
    stored = store.get_execution(recent_done, 1)
    assert stored is not None
    assert len(output_preview(stored.output)["rows"]) == 100
    page = output_page(stored.output, "rows", limit=50, offset=0)
    assert page["total"] == 150
    assert len(page["items"]) == 50

    deleted = purge_expired_run_records()
    assert deleted == 2
    assert store.get_run(old_done) is None
    assert store.get_run(old_cancelled) is None
    assert store.get_execution(old_done, 1) is None
    assert store.list_executions(old_done) == []
    assert store.get_run(unfinished) is not None
    assert store.get_run(recent_done) is not None
    kept = store.get_execution(recent_done, 1)
    assert kept is not None
    assert len(output_preview(kept.output)["rows"]) == 100
    jobs = get_job_store()
    for job_id in (old_done, old_cancelled, unfinished, recent_done):
        assert jobs.get(job_id) is not None


def _execution_items(
    client: TestClient, channel_id: str, job_id: str, **params: object
) -> list[dict]:
    response = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params=params,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["limit"] == params.get("limit", 50)
    assert body["offset"] == params.get("offset", 0)
    return body["items"]


def _test_run(client: TestClient, channel_id: str, graph: dict, **body) -> object:
    stop_at_node_id = body.pop("stop_at_node_id")
    draft = client.get(f"/channels/{channel_id}/draft").json()
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": draft["draft_revision"], "graph": graph},
    )
    if saved.status_code != 200:
        return saved
    started = client.post(
        f"/channels/{channel_id}/runs",
        json={
            "target": "draft",
            "stop_at_node_id": stop_at_node_id,
            **body,
        },
    )
    if started.status_code != 202:
        return started
    job_id = started.json()["run"]["job_id"]
    return client.get(f"/channels/{channel_id}/runs/{job_id}")


def test_test_run_is_a_recorded_run_and_writes(channel_client: TestClient) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job
    from backend.core.time import utc_now
    from backend.metadata.sources.store import SourceRecord, get_source_store, new_source_id

    previous = set_dispatcher(run_job)
    try:
        suffix = uuid.uuid4().hex[:8]
        table = f"ed_{suffix}"
        entity_id = _publish_entity(
            channel_client,
            table_name=table,
            name="Editor",
            attributes=[_string_attr("code", business_key=True), _string_attr("name")],
        )
        created_row = channel_client.post(
            f"/entities/{table}/create", json={"values": {"code": "A", "name": "Bolt"}}
        )
        assert created_row.status_code == 201, created_row.text
        created = channel_client.post(
            "/channels", json={"name": "Editor", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        settings = {"run_timeout_sec": None, "error_channel_id": None}
        graph = {
            "nodes": [
                _node("nd_trigger", "run_manually", "trigger.manual", "Run", 0, {}),
                _node(
                    "nd_sql",
                    "sql_read",
                    "read.sql",
                    "SQL",
                    40,
                    {
                        "source": {"kind": "entity"},
                        "sql": f"UPDATE {table} SET name = 'hacked' WHERE code = 'A'",
                    },
                ),
                _node(
                    "nd_write",
                    "written",
                    "write.entity",
                    "Write",
                    80,
                    {
                        "entity_id": entity_id,
                        "mode": "upsert",
                        "match_key": None,
                        "source": '[{"code": "A", "name": "Changed"}, {"code": "Z", "name": "Zinc"}]',
                        "mapping": [],
                        "on_incompatible_head": "fail",
                    },
                ),
                _node(
                    "nd_after",
                    "after",
                    "transform.set_fields",
                    "After",
                    120,
                    {"fields": [{"name": "n", "value": "1"}]},
                ),
            ],
            "edges": [
                _edge("ed_sql", "nd_trigger", "nd_sql"),
                _edge("ed_write", "nd_sql", "nd_write"),
                _edge("ed_after", "nd_write", "nd_after"),
            ],
            "settings": settings,
        }
        response = _test_run(channel_client, channel_id, graph, stop_at_node_id="nd_write")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["run"]["status"] == "succeeded", body
        assert body["run"]["stopped_node_id"] is None
        assert "node_executions" not in body
        summaries = {item["node_id"]: item for item in body["node_summaries"]}
        assert set(summaries) == {"nd_trigger", "nd_sql", "nd_write"}
        by_node = {
            item["node_id"]: item
            for item in _execution_items(channel_client, channel_id, body["run"]["job_id"])
        }
        assert "dry_run" not in by_node["nd_write"]["output_preview"]
        assert by_node["nd_write"]["output_preview"]["updated"] == 1
        assert by_node["nd_write"]["output_preview"]["inserted"] == 1
        assert by_node["nd_sql"]["started_at"].endswith("Z")
        queried = channel_client.post(f"/entities/{table}/query", json={})
        assert queried.status_code == 200, queried.text
        items = queried.json()["items"]
        assert len(items) == 2
        assert items[0]["code"] == "A"
        assert items[0]["name"] == "Changed"

        limited = {
            "nodes": [
                _node("nd_trigger", "run_manually", "trigger.manual", "Run", 0, {}),
                _node(
                    "nd_sql",
                    "sql_read",
                    "read.sql",
                    "SQL",
                    40,
                    {
                        "source": {"kind": "entity"},
                        "sql": "SELECT g FROM generate_series(1, 20) AS t(g)",
                    },
                ),
                _node(
                    "nd_cut",
                    "cut",
                    "transform.set_fields",
                    "Cut",
                    80,
                    {"fields": [{"name": "n", "value": "[1, 2, 3, 4, 5]"}]},
                ),
            ],
            "edges": [
                _edge("ed_sql", "nd_trigger", "nd_sql"),
                _edge("ed_cut", "nd_sql", "nd_cut"),
            ],
            "settings": settings,
        }
        capped = _test_run(
            channel_client,
            channel_id,
            limited,
            stop_at_node_id="nd_cut",
        )
        assert capped.status_code == 200, capped.text
        capped_body = capped.json()
        assert capped_body["run"]["status"] == "succeeded", capped_body
        assert "node_executions" not in capped_body
        capped_nodes = {
            item["node_id"]: item
            for item in _execution_items(
                channel_client, channel_id, capped_body["run"]["job_id"]
            )
        }
        assert len(capped_nodes["nd_sql"]["output_preview"]["rows"]) == 20
        assert capped_nodes["nd_sql"]["output_truncated"] is False
        assert capped_nodes["nd_cut"]["output_preview"]["n"] == [1, 2, 3, 4, 5]
        assert capped_nodes["nd_cut"]["output_truncated"] is False

        refused = channel_client.post(
            f"/channels/{channel_id}/runs",
            json={
                "target": "draft",
                "stop_at_node_id": "nd_trigger",
                "pinned": [{"node_id": "nd_shape", "output": {"rows": [{"code": "Z"}]}}],
            },
        )
        assert refused.status_code == 422
        assert refused.json()["code"] == "REQUEST_INVALID"

        unknown = channel_client.post(
            f"/channels/{channel_id}/runs",
            json={"target": "draft", "stop_at_node_id": "nd_trigger", "extra": True},
        )
        assert unknown.status_code == 422
        assert unknown.json()["code"] == "REQUEST_INVALID"

        missing = _test_run(
            channel_client, channel_id, TRIGGER, stop_at_node_id="nd_missing"
        )
        assert missing.status_code == 422
        assert missing.json()["code"] == "CHANNEL_GRAPH_INVALID"
        assert missing.json()["problems"] == []

        now = utc_now()
        source = get_source_store().create_source(
            SourceRecord(
                id=new_source_id(),
                key=f"ed{suffix}",
                locator_key="pending",
                name="Editor source",
                kind="database",
                status="active",
                description=None,
                engine="postgresql",
                access_ciphertext="unused",
                access_updated_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        source_graph = {
            "nodes": [
                _node("nd_trigger", "run_manually", "trigger.manual", "Run", 0, {}),
                _node(
                    "nd_sql",
                    "sql_read",
                    "read.sql",
                    "SQL",
                    40,
                    {
                        "source": {"kind": "source", "source_id": source.id},
                        "sql": "UPDATE widgets SET name = 'x'",
                    },
                ),
            ],
            "edges": [_edge("ed_sql", "nd_trigger", "nd_sql")],
            "settings": settings,
        }
        blocked = _test_run(
            channel_client, channel_id, source_graph, stop_at_node_id="nd_sql"
        )
        assert blocked.status_code == 200, blocked.text
        blocked_body = blocked.json()
        assert blocked_body["run"]["status"] == "failed"
        assert "node_executions" not in blocked_body
        sql_summary = next(
            item for item in blocked_body["node_summaries"] if item["node_id"] == "nd_sql"
        )
        assert sql_summary["status_counts"]["failed"] == 1
        sql_node = _execution_items(
            channel_client,
            channel_id,
            blocked_body["run"]["job_id"],
            node_id="nd_sql",
        )[0]
        assert sql_node["status"] == "failed"

        listed = channel_client.get(f"/channels/{channel_id}/runs")
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] > 0
    finally:
        set_dispatcher(previous)


def test_dataset_rows_are_a_keyset_page(
    channel_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.dataset_registry import get_dataset_store
    from backend.channel.models import ChannelDatasetRow
    from backend.core.config import reset_settings_cache
    from backend.core.db import session_scope
    from backend.entity.datasets import drop_relation
    from backend.entity.entity_db import reset_entity_engine
    from backend.tests.entity_pg import bootstrapped_entity_database

    created = channel_client.post(
        "/channels", json={"name": "Dataset rows", "description": None}
    )
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    _save_draft(channel_client, channel_id, TRIGGER, base_revision=1)
    previous = set_dispatcher(lambda _job_id: None)
    created_sets = []
    try:
        with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_rows") as urls:
            monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
            monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
            reset_settings_cache()
            reset_entity_engine()
            try:
                _assert_dataset_row_page(channel_client, channel_id, created_sets)
            finally:
                store = get_dataset_store()
                for record in created_sets:
                    record.status = "dropped"
                    record.size_bytes = 0
                    store.save(record)
                try:
                    for record in created_sets:
                        drop_relation(record.relation)
                finally:
                    reset_entity_engine()
    finally:
        set_dispatcher(previous)
        with session_scope() as session:
            for record in created_sets:
                row = session.get(ChannelDatasetRow, record.id)
                if row is not None:
                    session.delete(row)
        reset_settings_cache()


def _assert_dataset_row_page(
    channel_client: TestClient, channel_id: str, created_sets: list
) -> None:
    from datetime import timedelta

    from sqlalchemy import text

    from backend.channel.dataset_registry import (
        DatasetColumnSpec,
        DatasetRegistry,
        get_dataset_store,
    )
    from backend.channel.parameters import channel_dataset_max_total_gb
    from backend.core.time import utc_now
    from backend.entity.entity_db import get_entity_engine
    from backend.tests.problem import assert_problem

    started = channel_client.post(
        f"/channels/{channel_id}/runs", json={"target": "draft"}
    )
    assert started.status_code == 202, started.text
    job_id = started.json()["run"]["job_id"]
    missing_run = channel_client.get(
        f"/channels/{channel_id}/runs/job_missing/datasets/dmissing/rows"
    )
    assert_problem(missing_run, status=404, code="CHANNEL_RUN_NOT_FOUND")
    missing = channel_client.get(
        f"/channels/{channel_id}/runs/{job_id}/datasets/dmissing/rows"
    )
    body = assert_problem(missing, status=404, code="CHANNEL_DATASET_UNAVAILABLE")
    assert body["reason"] == "not_found"
    assert "CHANNEL_DATASET_QUOTA_EXCEEDED" not in missing.text

    registry = DatasetRegistry(get_dataset_store())
    page_set = registry.create_from_chunks(
        job_id=job_id,
        node_id="nd_read",
        seq=1,
        columns=[DatasetColumnSpec(name="code", normalized_type="string")],
        chunks=[[("S-01",), ("S-02",), ("S-03",)]],
    )
    created_sets.append(page_set)
    assert page_set.row_count == 3

    def rows(dataset_id: str, **params: object):
        return channel_client.get(
            f"/channels/{channel_id}/runs/{job_id}/datasets/{dataset_id}/rows",
            params=params,
        )

    first = rows(page_set.id, limit=2)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["limit"] == 2
    assert "total" not in first_body
    assert "offset" not in first_body
    assert [item["_ord"] for item in first_body["items"]] == [1, 2]
    assert [item["code"] for item in first_body["items"]] == ["S-01", "S-02"]
    assert first_body["next_after_ord"] == 2
    second = rows(page_set.id, after_ord=first_body["next_after_ord"], limit=2)
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert [item["_ord"] for item in second_body["items"]] == [3]
    assert second_body["items"][0]["code"] == "S-03"
    assert second_body["next_after_ord"] is None
    exact = rows(page_set.id, limit=3)
    assert exact.json()["next_after_ord"] is None
    assert [item["_ord"] for item in exact.json()["items"]] == [1, 2, 3]
    tail = rows(page_set.id, after_ord=3)
    assert tail.json()["items"] == []
    assert tail.json()["limit"] == 50
    assert tail.json()["next_after_ord"] is None
    refused = rows(page_set.id, limit=201)
    assert_problem(refused, status=422, code="REQUEST_INVALID")

    foreign = registry.create_from_query(
        job_id="job_other",
        node_id="nd_read",
        seq=1,
        query="SELECT 'Z' AS code",
    )
    created_sets.append(foreign)
    foreign.expires_at = utc_now() - timedelta(seconds=1)
    get_dataset_store().save(foreign)
    foreign_response = rows(foreign.id)
    foreign_body = assert_problem(
        foreign_response, status=404, code="CHANNEL_DATASET_UNAVAILABLE"
    )
    assert foreign_body["reason"] == "foreign_run"

    expired = registry.create_from_query(
        job_id=job_id,
        node_id="nd_read",
        seq=2,
        query="SELECT 'E' AS code",
    )
    created_sets.append(expired)
    expired.expires_at = utc_now() - timedelta(seconds=1)
    get_dataset_store().save(expired)
    expired_body = assert_problem(
        rows(expired.id), status=404, code="CHANNEL_DATASET_UNAVAILABLE"
    )
    assert expired_body["reason"] == "expired"

    loading = registry.create_from_query(
        job_id=job_id,
        node_id="nd_read",
        seq=3,
        query="SELECT 'L' AS code",
    )
    created_sets.append(loading)
    loading.status = "loading"
    get_dataset_store().save(loading)
    loading_body = assert_problem(
        rows(loading.id), status=404, code="CHANNEL_DATASET_UNAVAILABLE"
    )
    assert loading_body["reason"] == "not_found"

    lost = registry.create_from_query(
        job_id=job_id,
        node_id="nd_read",
        seq=4,
        query="SELECT 'gone' AS code",
    )
    created_sets.append(lost)
    assert lost.row_count > 0
    with get_entity_engine().begin() as conn:
        conn.execute(text(f"DELETE FROM {lost.relation}"))
    lost_body = assert_problem(
        rows(lost.id), status=404, code="CHANNEL_DATASET_UNAVAILABLE"
    )
    assert lost_body["reason"] == "lost"

    empty = registry.create_from_query(
        job_id=job_id,
        node_id="nd_read",
        seq=5,
        query="SELECT 'x' AS code WHERE false",
    )
    created_sets.append(empty)
    assert empty.row_count == 0
    empty_body = rows(empty.id).json()
    assert empty_body["items"] == []
    assert empty_body["next_after_ord"] is None

    page_set.size_bytes = 10**18
    get_dataset_store().save(page_set)
    assert get_dataset_store().used_bytes() >= channel_dataset_max_total_gb() * 1024**3
    still = rows(page_set.id, limit=1)
    assert still.status_code == 200, still.text
    assert still.json()["items"][0]["_ord"] == 1
    assert "CHANNEL_DATASET_QUOTA_EXCEEDED" not in still.text