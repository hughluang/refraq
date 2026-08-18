"""Integration tests against isolated Compose Postgres DB + Redis logical DB."""

from __future__ import annotations

import os
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.integration

# Dedicated stores — never read live DATABASE_URL / REDIS_URL from .env.
INTEGRATION_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)
INTEGRATION_REDIS_URL = os.getenv(
    "REFRAQ_INTEGRATION_REDIS_URL",
    "redis://127.0.0.1:6379/1",
)
# Same Compose instance as interactive dev; used only to probe / CREATE DATABASE.
_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)

_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _services_available() -> bool:
    """Probe Compose Postgres + Redis; does not require refraq_test to exist yet."""
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        from redis import Redis

        client = Redis.from_url(INTEGRATION_REDIS_URL)
        ok = client.ping() is True
        client.close()
        return bool(ok)
    except Exception:
        return False


def _ensure_integration_database(database_url: str) -> None:
    url = make_url(database_url)
    db_name = url.database
    if not db_name:
        raise ValueError("integration DATABASE_URL must include a database name")
    if not _SAFE_IDENT.match(db_name):
        raise ValueError(f"unsafe integration database name: {db_name!r}")

    admin_url = url.set(database=make_url(_MAINTENANCE_DATABASE_URL).database)
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
def persistent_client(monkeypatch: pytest.MonkeyPatch):
    if not _services_available():
        pytest.skip("Postgres/Redis not available (start: docker compose up -d)")

    _ensure_integration_database(INTEGRATION_DATABASE_URL)

    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
    monkeypatch.setenv("DATABASE_URL", INTEGRATION_DATABASE_URL)
    monkeypatch.setenv("REDIS_URL", INTEGRATION_REDIS_URL)
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.setenv("REFRAQ_SKIP_SEED", "0")
    monkeypatch.setenv("INITIAL_ADMIN_ACCOUNT", "root")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "s3cret")

    from backend.core.config import reset_settings_cache
    from backend.core.db import reset_db_singletons
    from backend.core.entry import migrate_with_advisory_lock
    from backend.core.redis_client import reset_redis_singleton
    from backend.admin.role_store import reset_role_store
    from backend.admin.session_store import reset_session_store
    from backend.admin.user_store import reset_user_store

    reset_settings_cache()
    reset_db_singletons()
    reset_redis_singleton()
    reset_user_store()
    reset_role_store()
    reset_session_store()

    migrate_with_advisory_lock(INTEGRATION_DATABASE_URL)

    # Truncate only the isolated test database
    engine = create_engine(INTEGRATION_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE users, roles RESTART IDENTITY CASCADE"))
    engine.dispose()

    from redis import Redis

    redis = Redis.from_url(INTEGRATION_REDIS_URL)
    redis.flushdb()
    redis.close()

    # Re-import app with fresh settings — use dependency factories after cache clear
    import backend.main as main_mod

    reset_settings_cache()
    main_mod.settings = main_mod.get_settings()
    main_mod._bootstrap_site(main_mod.settings)

    with TestClient(main_mod.app) as client:
        yield client

    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_db_singletons()
    reset_redis_singleton()
    reset_settings_cache()


def test_login_and_me_persistent(persistent_client: TestClient) -> None:
    login = persistent_client.post(
        "/auth/login",
        json={"account": "root", "password": "s3cret"},
    )
    assert login.status_code == 200
    assert "refraq_sid" in login.cookies

    me = persistent_client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["account"] == "root"


def test_disable_user_revokes_sessions(persistent_client: TestClient) -> None:
    # Create operator user via API as root
    login = persistent_client.post(
        "/auth/login",
        json={"account": "root", "password": "s3cret"},
    )
    assert login.status_code == 200

    roles = persistent_client.get("/roles")
    assert roles.status_code == 200
    operator = next(r for r in roles.json()["items"] if r["key"] == "operator")

    created = persistent_client.post(
        "/users",
        json={
            "account": "op1",
            "display_name": "Op One",
            "password": "op-pass-1",
            "role_id": operator["id"],
        },
    )
    assert created.status_code == 201
    user_id = created.json()["user"]["id"]

    persistent_client.post("/auth/logout")

    op_login = persistent_client.post(
        "/auth/login",
        json={"account": "op1", "password": "op-pass-1"},
    )
    assert op_login.status_code == 200
    op_sid = op_login.cookies.get("refraq_sid")
    assert op_sid

    # Root disables operator
    persistent_client.cookies.clear()
    root_login = persistent_client.post(
        "/auth/login",
        json={"account": "root", "password": "s3cret"},
    )
    assert root_login.status_code == 200
    disabled = persistent_client.patch(
        f"/users/{user_id}/status",
        json={"status": "disabled"},
    )
    assert disabled.status_code == 200

    # Former operator cookie must be unauthenticated
    persistent_client.cookies.clear()
    persistent_client.cookies.set("refraq_sid", op_sid)
    me = persistent_client.get("/auth/me")
    assert me.status_code == 401


def test_sql_list_objects_is_constant_queries(persistent_client: TestClient) -> None:
    from backend.core.db import get_engine
    from backend.core.time import utc_now
    from backend.metadata.catalog.store import (
        CatalogColumnRecord,
        CatalogIndexRecord,
        CatalogObjectRecord,
        get_catalog_store,
        new_column_id,
        new_index_id,
        new_object_id,
        reset_catalog_store,
    )
    from backend.metadata.catalog.structure_refresh import apply_structure_snapshot
    from backend.metadata.sources.service import require_source
    from backend.metadata.sources.store import reset_source_store

    reset_source_store()
    reset_catalog_store()

    login = persistent_client.post(
        "/auth/login",
        json={"account": "root", "password": "s3cret"},
    )
    assert login.status_code == 200
    key = f"listsql{uuid.uuid4().hex[:8]}"
    created = persistent_client.post(
        "/sources",
        json={
            "key": key,
            "name": key,
            "kind": "database",
            "engine": "postgresql",
            "access": {
                "host": "127.0.0.1",
                "port": 5432,
                "username": "u",
                "password": "p",
                "ssl_mode": "require",
                "database": "MES",
                "schema": "public",
                "extra": {},
            },
        },
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["source"]["id"]

    reset_catalog_store()
    now = utc_now()
    collected: list[CatalogObjectRecord] = []
    for i in range(20):
        object_id = new_object_id()
        columns = [
            CatalogColumnRecord(
                id=new_column_id(),
                object_id=object_id,
                locator_key=f"col/postgresql/{key}/public/table/t{i}/column/c{j}",
                name=f"c{j}",
                ordinal=j,
                data_type="int",
                nullable=False,
                is_present=True,
                default_value=None,
                comment=None,
                business_name=None,
                business_description=None,
                column_semantics=None,
                enum_catalog=None,
                semantic_source=None,
                field_kind="column",
                created_at=now,
                updated_at=now,
            )
            for j in range(8)
        ]
        collected.append(
            CatalogObjectRecord(
                id=object_id,
                source_id=source_id,
                locator_key=f"obj/postgresql/{key}/public/table/t{i}",
                object_type="table",
                schema_name="public",
                name=f"t{i}",
                ddl=f"CREATE TABLE t{i} ();",
                comment=None,
                primary_key=["c0"],
                is_present=True,
                business_name=f"Biz t{i}" if i == 7 else None,
                business_description="needle should not match list q",
                object_category=None,
                grain_description=None,
                business_primary_key=None,
                business_domain_id=None,
                evidence_summary=None,
                open_questions=None,
                semantic_source=None,
                business_semantics_ready=(i % 2 == 0),
                semantics_updated_at=None,
                last_structure_job_id="job_list",
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=columns,
                foreign_keys=[],
                indexes=[
                    CatalogIndexRecord(
                        id=new_index_id(),
                        name=f"ix_t{i}",
                        columns=["c0"],
                        is_unique=True,
                        is_present=True,
                    )
                ],
            )
        )
    apply_structure_snapshot(
        source=require_source(source_id),
        job_id="job_list",
        collected=collected,
        schema_scope=None,
        fail_safe_threshold=1.0,
    )

    store = get_catalog_store()
    statements: list[str] = []

    def _on_execute(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        items, total = store.list_objects(source_id, limit=5, offset=0)
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)

    assert total == 20
    assert len(items) == 5
    assert all(not o.columns and not o.indexes and o.ddl is None for o in items)
    child = [
        sql
        for sql in statements
        if "catalog_columns" in sql.lower()
        or "catalog_indexes" in sql.lower()
        or "catalog_foreign_keys" in sql.lower()
    ]
    assert child == []
    object_sql = [sql for sql in statements if "catalog_objects" in sql.lower()]
    assert len(object_sql) == 2

    named, named_total = store.list_objects(source_id, name_search="Biz t7")
    assert named_total == 1
    assert named[0].name == "t7"

    desc, desc_total = store.list_objects(source_id, name_search="needle")
    assert desc_total == 0
    assert desc == []

    _ready, ready_total = store.list_objects(
        source_id, business_semantics_ready=True, limit=100
    )
    assert ready_total == 10

    present = store.list_present_for_source(source_id)
    assert len(present) == 20
    assert all(o.columns for o in present)
    assert all(o.indexes for o in present)

    apply_structure_snapshot(
        source=require_source(source_id),
        job_id="job_tomb",
        collected=collected[:-1],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    _with_absent, with_absent_total = store.list_objects(
        source_id, include_absent=True, limit=5
    )
    _present_only, present_only_total = store.list_objects(
        source_id, include_absent=False, limit=5
    )
    assert with_absent_total == 20
    assert present_only_total == 19
    assert with_absent_total != present_only_total
    assert len(store.list_present_for_source(source_id)) == 19
