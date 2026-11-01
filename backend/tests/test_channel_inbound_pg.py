"""Inbound callback on PostgreSQL: entity SQL, two Sources, and compensation."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.entity.ddl import ENTITY_OWNER_ROLE
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
_SECRET = "hook-secret-9f3a"
_BUYER = "O'Brien; DROP TABLE ledger"
_MARKER = "BOLT-7"
_ANSWER = '{"buyer":"O\'Brien; DROP TABLE ledger","marker":"BOLT-7"}'
_PRIOR_STATUS = "open"


@dataclass(frozen=True)
class _World:
    client: TestClient
    entity_url: str
    erp_url: str
    crm_url: str
    erp_id: str
    crm_id: str
    credential_id: str
    suffix: str


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


def _admin_engine():
    admin_url = make_url(_MAINTENANCE_DATABASE_URL).set(database="postgres")
    return create_engine(admin_url, isolation_level="AUTOCOMMIT")


def _create_database(name: str) -> None:
    engine = _admin_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()


def _drop_database(name: str) -> None:
    engine = _admin_engine()
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        engine.dispose()


def _database_url(name: str) -> str:
    return make_url(_MAINTENANCE_DATABASE_URL).set(database=name).render_as_string(
        hide_password=False
    )


def _source_access(database: str) -> dict:
    parsed = make_url(_MAINTENANCE_DATABASE_URL)
    return {
        "host": parsed.host or "127.0.0.1",
        "port": parsed.port or 5432,
        "username": parsed.username or "refraq",
        "password": parsed.password or "refraq",
        "ssl_mode": "disable",
        "database": database,
        "schema": "public",
    }


def _plant_entity(admin_url: str) -> None:
    engine = create_engine(admin_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("CREATE TABLE entity_data.order_line (buyer text, marker text)")
            )
            conn.execute(
                text(
                    "INSERT INTO entity_data.order_line (buyer, marker) "
                    "VALUES (:buyer, :marker)"
                ),
                {"buyer": _BUYER, "marker": _MARKER},
            )
            conn.execute(
                text(
                    "ALTER TABLE entity_data.order_line "
                    f'OWNER TO "{ENTITY_OWNER_ROLE}"'
                )
            )
    finally:
        engine.dispose()


def _plant_ledger(url: str) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE public.ledger ("
                    "id integer PRIMARY KEY, buyer text, marker text, status text)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO public.ledger (id, buyer, marker, status) "
                    "VALUES (1, 'before', 'before', :status)"
                ),
                {"status": _PRIOR_STATUS},
            )
    finally:
        engine.dispose()


def _ledger(url: str) -> dict:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, buyer, marker, status FROM public.ledger WHERE id = 1"
                )
            ).mappings().one()
        return dict(row)
    finally:
        engine.dispose()


def _order_line(url: str) -> dict:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT buyer, marker FROM entity_data.order_line")
            ).mappings().one()
        return dict(row)
    finally:
        engine.dispose()


@pytest.fixture
def inbound_pg(monkeypatch: pytest.MonkeyPatch):
    if not _services_available():
        pytest.skip("Postgres/Redis not available (start: docker compose up -d)")

    _ensure_database()
    suffix = uuid.uuid4().hex[:8]
    erp_name = f"refraq_inb_erp_{suffix}"
    crm_name = f"refraq_inb_crm_{suffix}"
    created: list[str] = []
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_inb") as urls:
        try:
            for name in (erp_name, crm_name):
                _create_database(name)
                created.append(name)
            _plant_entity(urls.admin_url)
            erp_url = _database_url(erp_name)
            crm_url = _database_url(crm_name)
            _plant_ledger(erp_url)
            _plant_ledger(crm_url)

            monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
            monkeypatch.setenv("DATABASE_URL", INTEGRATION_DATABASE_URL)
            monkeypatch.setenv("REDIS_URL", INTEGRATION_REDIS_URL)
            monkeypatch.setenv("ENTITY_DATABASE_URL", urls.owner_url)
            monkeypatch.setenv("ENTITY_READER_DATABASE_URL", urls.reader_url)
            monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
            monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
            monkeypatch.setenv("REFRAQ_SKIP_SEED", "0")
            monkeypatch.setenv("INITIAL_ADMIN_ACCOUNT", "root")
            monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "s3cret")

            from backend.admin.role_store import reset_role_store
            from backend.admin.session_store import reset_session_store
            from backend.admin.user_store import reset_user_store
            from backend.channel.channel_run import set_dispatcher
            from backend.channel.store import reset_channel_store
            from backend.channel.tasks import run_job
            from backend.core.config import get_settings, reset_settings_cache
            from backend.core.db import reset_db_singletons
            from backend.core.entry import migrate_with_advisory_lock
            from backend.core.redis_client import reset_redis_singleton
            from backend.entity.entity_db import reset_entity_engine

            reset_settings_cache()
            reset_db_singletons()
            reset_redis_singleton()
            reset_entity_engine()
            reset_user_store()
            reset_role_store()
            reset_session_store()
            reset_channel_store()
            migrate_with_advisory_lock(INTEGRATION_DATABASE_URL)

            engine = create_engine(INTEGRATION_DATABASE_URL)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "TRUNCATE TABLE users, roles, channels, channel_versions, "
                        "channel_variables RESTART IDENTITY CASCADE"
                    )
                )
            engine.dispose()

            from redis import Redis

            redis = Redis.from_url(INTEGRATION_REDIS_URL)
            redis.flushdb()
            redis.close()

            import backend.main as main_mod

            reset_settings_cache()
            reset_entity_engine()
            reset_channel_store()
            main_mod.settings = main_mod.get_settings()
            main_mod._bootstrap_site(main_mod.settings)

            with TestClient(main_mod.app) as client:
                login = client.post(
                    "/auth/login", json={"account": "root", "password": "s3cret"}
                )
                assert login.status_code == 200, login.text
                credential_id = _credential(client, suffix)
                erp_id = _register_source(client, f"erp{suffix}", "ERP", erp_name)
                crm_id = _register_source(client, f"crm{suffix}", "CRM", crm_name)
                previous = set_dispatcher(run_job)
                try:
                    yield _World(
                        client=client,
                        entity_url=urls.owner_url,
                        erp_url=erp_url,
                        crm_url=crm_url,
                        erp_id=erp_id,
                        crm_id=crm_id,
                        credential_id=credential_id,
                        suffix=suffix,
                    )
                finally:
                    set_dispatcher(previous)

            reset_user_store()
            reset_role_store()
            reset_session_store()
            reset_channel_store()
            reset_entity_engine()
            reset_db_singletons()
            reset_redis_singleton()
            reset_settings_cache()
        finally:
            for name in created:
                _drop_database(name)


def _credential(client: TestClient, suffix: str) -> str:
    created = client.post(
        "/inbound-credentials",
        json={
            "name": f"Hook {suffix}",
            "type": "token",
            "secret": _SECRET,
            "config": {"location": "header", "name": "X-Hook-Token"},
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["inbound_credential"]["id"]


def _register_source(client: TestClient, key: str, name: str, database: str) -> str:
    created = client.post(
        "/sources",
        json={
            "key": key,
            "name": name,
            "kind": "database",
            "engine": "postgresql",
            "access": _source_access(database),
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["source"]["id"]


def _node(
    node_id: str,
    ref: str,
    type_id: str,
    name: str,
    x: int,
    config: dict,
    *,
    on_error: str = "stop",
) -> dict:
    return {
        "id": node_id,
        "ref": ref,
        "type": type_id,
        "name": name,
        "position": {"x": x, "y": 0},
        "config": config,
        "on_error": on_error,
        "retry": None,
    }


def _edge(edge_id: str, source: str, target: str, *, source_port: str = "main") -> dict:
    return {
        "id": edge_id,
        "source": {"node_id": source, "port": source_port},
        "target": {"node_id": target, "port": "main"},
    }


def _graph(*nodes: dict, edges: list[dict]) -> dict:
    return {
        "nodes": list(nodes),
        "edges": edges,
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }


def _hook_node(credential_id: str, path: str) -> dict:
    return _node(
        "nd_hook",
        "hook",
        "trigger.inbound",
        "Inbound",
        0,
        {
            "path": path,
            "credential_id": credential_id,
            "response": {"mode": "respond_node", "wait_sec": 5},
        },
    )


def _sql_node(
    node_id: str,
    ref: str,
    name: str,
    x: int,
    source: dict,
    statement: str,
    params: list[str] | None = None,
    *,
    on_error: str = "stop",
) -> dict:
    config: dict = {"source": source, "sql": statement}
    if params is not None:
        config["params"] = params
    return _node(
        node_id,
        ref,
        "read.sql",
        name,
        x,
        config,
        on_error=on_error,
    )


def _entity_read() -> dict:
    return _sql_node(
        "nd_order",
        "order_line",
        "Read order",
        80,
        {"kind": "entity"},
        "SELECT marker FROM order_line WHERE buyer = %s",
        ["{{ self.hook.output.body.buyer }}"],
    )


def _source_update(node_id: str, ref: str, name: str, x: int, source_id: str) -> dict:
    return _sql_node(
        node_id,
        ref,
        name,
        x,
        {"kind": "source", "source_id": source_id},
        "UPDATE public.ledger SET buyer = %s, marker = %s WHERE id = 1",
        [
            "{{ self.hook.output.body.buyer }}",
            "{{ self.order_line.output.rows[0].marker }}",
        ],
    )


def _publish(world: _World, name: str, path: str, graph: dict) -> str:
    client = world.client
    created = client.post("/channels", json={"name": name, "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    current = client.get(f"/channels/{channel_id}/draft")
    assert current.status_code == 200, current.text
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": current.json()["draft_revision"], "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    published = client.post(
        f"/channels/{channel_id}/publish",
        json={"draft_revision": saved.json()["draft_revision"]},
    )
    assert published.status_code == 201, published.text
    activated = client.post(f"/channels/{channel_id}/activate")
    assert activated.status_code == 200, activated.text
    return channel_id


def _call(world: _World, path: str):
    return world.client.post(
        f"/hooks/{path}",
        json={"buyer": _BUYER},
        headers={"X-Hook-Token": _SECRET},
    )


def _only_job(world: _World, channel_id: str) -> str:
    listed = world.client.get(f"/channels/{channel_id}/runs")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    return body["items"][0]["job_id"]


def _executions(world: _World, channel_id: str, job_id: str, node_id: str) -> list[dict]:
    listed = world.client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"node_id": node_id},
    )
    assert listed.status_code == 200, listed.text
    return listed.json()["items"]


def _output(world: _World, channel_id: str, job_id: str, seq: int):
    loaded = world.client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions/{seq}/output"
    )
    assert loaded.status_code == 200, loaded.text
    return loaded.json()["value"]


def test_inbound_callback_reads_an_entity_and_updates_two_sources(
    inbound_pg: _World,
) -> None:
    path = f"in{inbound_pg.suffix}"
    channel_id = _publish(
        inbound_pg,
        "Accepted order",
        path,
        _graph(
            _hook_node(inbound_pg.credential_id, path),
            _entity_read(),
            _source_update("nd_erp", "erp", "Update ERP", 160, inbound_pg.erp_id),
            _source_update("nd_crm", "crm", "Update CRM", 240, inbound_pg.crm_id),
            _node(
                "nd_reply",
                "reply",
                "action.respond",
                "Respond",
                320,
                {
                    "status": "200",
                    "content_type": "application/json",
                    "body": (
                        '{{ {"buyer": self.hook.output.body.buyer, '
                        '"marker": self.order_line.output.rows[0].marker} }}'
                    ),
                },
            ),
            edges=[
                _edge("ed_order", "nd_hook", "nd_order"),
                _edge("ed_erp", "nd_order", "nd_erp"),
                _edge("ed_crm", "nd_erp", "nd_crm"),
                _edge("ed_reply", "nd_crm", "nd_reply"),
            ],
        ),
    )

    response = _call(inbound_pg, path)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].split(";")[0] == "application/json"
    assert response.text == _ANSWER
    assert _order_line(inbound_pg.entity_url) == {
        "buyer": _BUYER,
        "marker": _MARKER,
    }
    written = {"id": 1, "buyer": _BUYER, "marker": _MARKER, "status": _PRIOR_STATUS}
    assert _ledger(inbound_pg.erp_url) == written
    assert _ledger(inbound_pg.crm_url) == written
    job_id = _only_job(inbound_pg, channel_id)
    detail = inbound_pg.client.get(f"/channels/{channel_id}/runs/{job_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    read = _executions(inbound_pg, channel_id, job_id, "nd_order")
    assert len(read) == 1
    assert read[0]["status"] == "succeeded"
    assert _output(inbound_pg, channel_id, job_id, read[0]["seq"])["rows"] == [
        {"marker": _MARKER}
    ]


def test_failed_second_source_update_restores_the_first(inbound_pg: _World) -> None:
    path = f"fix{inbound_pg.suffix}"
    channel_id = _publish(
        inbound_pg,
        "Restore ERP",
        path,
        _graph(
            _hook_node(inbound_pg.credential_id, path),
            _entity_read(),
            _sql_node(
                "nd_prior",
                "prior",
                "Read ERP",
                160,
                {"kind": "source", "source_id": inbound_pg.erp_id},
                "SELECT status FROM public.ledger WHERE id = 1",
            ),
            _sql_node(
                "nd_erp",
                "erp",
                "Update ERP",
                240,
                {"kind": "source", "source_id": inbound_pg.erp_id},
                "UPDATE public.ledger SET status = %s WHERE id = 1",
                ["{{ self.hook.output.body.buyer }}"],
            ),
            _sql_node(
                "nd_crm",
                "crm",
                "Update CRM",
                320,
                {"kind": "source", "source_id": inbound_pg.crm_id},
                "UPDATE public.crm_account SET status = %s WHERE id = 1",
                ["{{ self.hook.output.body.buyer }}"],
                on_error="error_output",
            ),
            _sql_node(
                "nd_restore",
                "restore",
                "Restore ERP",
                400,
                {"kind": "source", "source_id": inbound_pg.erp_id},
                "UPDATE public.ledger SET status = %s WHERE id = 1",
                ["{{ self.prior.output.rows[0].status }}"],
            ),
            _node(
                "nd_kept",
                "kept",
                "transform.set_fields",
                "Kept",
                400,
                {"fields": [{"name": "kept", "value": "true"}]},
            ),
            _node(
                "nd_reply",
                "reply",
                "action.respond",
                "Respond",
                480,
                {
                    "status": "200",
                    "content_type": "text/plain",
                    "body": '"restored"',
                },
            ),
            edges=[
                _edge("ed_order", "nd_hook", "nd_order"),
                _edge("ed_prior", "nd_order", "nd_prior"),
                _edge("ed_erp", "nd_prior", "nd_erp"),
                _edge("ed_crm", "nd_erp", "nd_crm"),
                _edge("ed_restore", "nd_crm", "nd_restore", source_port="error"),
                _edge("ed_kept", "nd_crm", "nd_kept"),
                _edge("ed_reply", "nd_restore", "nd_reply"),
            ],
        ),
    )

    response = _call(inbound_pg, path)

    assert response.status_code == 200, response.text
    assert response.text == "restored"
    assert _ledger(inbound_pg.erp_url)["status"] == _PRIOR_STATUS
    assert _ledger(inbound_pg.erp_url)["buyer"] == "before"
    assert _ledger(inbound_pg.crm_url) == {
        "id": 1,
        "buyer": "before",
        "marker": "before",
        "status": _PRIOR_STATUS,
    }
    job_id = _only_job(inbound_pg, channel_id)
    detail = inbound_pg.client.get(f"/channels/{channel_id}/runs/{job_id}")
    assert detail.status_code == 200, detail.text
    run = detail.json()["run"]
    assert run["status"] == "succeeded"
    assert run["failed_node_id"] is None
    read = _executions(inbound_pg, channel_id, job_id, "nd_order")
    assert _output(inbound_pg, channel_id, job_id, read[0]["seq"])["rows"] == [
        {"marker": _MARKER}
    ]
    updated = _executions(inbound_pg, channel_id, job_id, "nd_erp")
    assert updated[0]["status"] == "succeeded"
    assert _output(inbound_pg, channel_id, job_id, updated[0]["seq"])["rowcount"] == 1
    failed = _executions(inbound_pg, channel_id, job_id, "nd_crm")
    assert failed[0]["status"] == "failed"
    recorded = _output(inbound_pg, channel_id, job_id, failed[0]["seq"])
    assert set(recorded) == {"code", "message", "detail"}
    assert recorded["code"]
    restored = _executions(inbound_pg, channel_id, job_id, "nd_restore")
    assert restored[0]["status"] == "succeeded"
    assert _output(inbound_pg, channel_id, job_id, restored[0]["seq"])["rowcount"] == 1
    assert _executions(inbound_pg, channel_id, job_id, "nd_kept") == []
