"""Data Channel definition HTTP against real PostgreSQL."""

from __future__ import annotations

import os

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


def test_enqueue_body_matches_finished_run(
    channel_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eager SQL runs return the stored outcome, not the pre-execution record."""
    from backend.channel.engine import NodeResult
    from backend.channel.executors import EXECUTORS
    from backend.worker.app import celery_app

    previous = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = True
    try:
        created = channel_client.post(
            "/channels", json={"name": "Enqueue probe", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        _save_draft(channel_client, channel_id, TRIGGER, base_revision=1)

        succeeded = _enqueue_matches_get(channel_client, channel_id)
        assert succeeded["status"] == "succeeded"
        assert succeeded["outcome"] == "completed"
        assert succeeded["failed_node_id"] is None

        def _fail(node: dict, hooks: object) -> NodeResult:
            del node, hooks
            return NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_FAILED",
                error_message="forced",
            )

        monkeypatch.setitem(EXECUTORS, "trigger.manual", _fail)
        failed = _enqueue_matches_get(channel_client, channel_id)
        assert failed["status"] == "failed"
        assert failed["outcome"] is None
        assert failed["failed_node_id"] == "nd_trigger"
    finally:
        celery_app.conf.task_always_eager = previous


def test_template_preview_reads_the_recorded_run(channel_client: TestClient) -> None:
    from backend.worker.app import celery_app

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
    previous = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = True
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
        celery_app.conf.task_always_eager = previous
    preview = channel_client.post(
        f"/channels/{channel_id}/runs/{run['job_id']}/template-preview",
        json={"graph": graph, "node_id": "nd_keep", "path": ["value"]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "state": "ok",
        "value": [run["job_id"], "root"],
        "truncated": False,
    }


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
