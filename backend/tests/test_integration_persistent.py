"""Integration tests against isolated Compose Postgres DB + Redis logical DB."""

from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
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
