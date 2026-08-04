"""Platform settings API tests for docs/api-contracts-settings.md."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.security import hash_password  # noqa: E402
from backend.admin.settings_override import (  # noqa: E402
    get_effective_admin_session_ttl_hours,
    reset_settings_override,
)
from backend.main import app  # noqa: E402
from backend.repositories.role_store import (  # noqa: E402
    MemoryRoleStore,
    reset_role_store,
)
from backend.repositories.session_store import (  # noqa: E402
    MemorySessionStore,
    reset_session_store,
)
from backend.repositories.user_store import (  # noqa: E402
    MemoryUserStore,
    reset_user_store,
)


@pytest.fixture
def store_bundle():
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_settings_override()
    role_store = MemoryRoleStore()
    role_store.seed_defaults()
    user_store = MemoryUserStore()
    super_admin = role_store.get_by_key("super_admin")
    operator = role_store.get_by_key("operator")
    assert super_admin is not None and operator is not None
    user_store.create_user(
        account="root",
        display_name="Root",
        password_hash=hash_password("s3cret"),
        role_id=super_admin.id,
    )
    user_store.create_user(
        account="op",
        display_name="Operator",
        password_hash=hash_password("op-pass"),
        role_id=operator.id,
    )
    session_store = MemorySessionStore()
    yield user_store, role_store, session_store
    app.dependency_overrides.clear()
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_settings_override()


@pytest.fixture
def client(store_bundle):
    user_store, role_store, session_store = store_bundle
    from backend.repositories.role_store import get_role_store
    from backend.repositories.session_store import get_session_store
    from backend.repositories.user_store import get_user_store

    app.dependency_overrides[get_user_store] = lambda: user_store
    app.dependency_overrides[get_role_store] = lambda: role_store
    app.dependency_overrides[get_session_store] = lambda: session_store
    with TestClient(app) as test_client:
        yield test_client


def _login_root(client: TestClient) -> None:
    assert (
        client.post("/auth/login", json={"account": "root", "password": "s3cret"}).status_code
        == 200
    )


def test_get_settings_requires_permission(client: TestClient) -> None:
    assert (
        client.post("/auth/login", json={"account": "op", "password": "op-pass"}).status_code
        == 200
    )
    response = client.get("/settings")
    assert response.status_code == 403


def test_get_settings_hides_secrets(client: TestClient) -> None:
    _login_root(client)
    response = client.get("/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["refraq_env"]
    assert body["admin_session_ttl_hours_source"] == "env"
    assert "admin_session_secret" not in body
    assert "initial_admin_password" not in body
    assert "initial_admin_account" not in body


def test_patch_and_clear_override(client: TestClient) -> None:
    _login_root(client)
    patched = client.patch("/settings", json={"admin_session_ttl_hours": 12})
    assert patched.status_code == 200
    body = patched.json()
    assert body["admin_session_ttl_hours"] == 12
    assert body["admin_session_ttl_hours_source"] == "override"
    assert get_effective_admin_session_ttl_hours() == 12

    cleared = client.delete("/settings/override")
    assert cleared.status_code == 200
    cleared_body = cleared.json()
    assert cleared_body["admin_session_ttl_hours_source"] == "env"
    assert cleared_body["admin_session_ttl_hours"] == cleared_body["admin_session_ttl_hours_default"]


def test_patch_rejects_out_of_range(client: TestClient) -> None:
    _login_root(client)
    response = client.patch("/settings", json={"admin_session_ttl_hours": 0})
    assert response.status_code == 422


def test_patch_requires_write(client: TestClient) -> None:
    assert (
        client.post("/auth/login", json={"account": "op", "password": "op-pass"}).status_code
        == 200
    )
    response = client.patch("/settings", json={"admin_session_ttl_hours": 10})
    assert response.status_code == 403


def test_ttl_override_affects_new_sessions_only(
    client: TestClient, store_bundle
) -> None:
    _, _, session_store = store_bundle
    _login_root(client)
    first_sid = client.cookies.get("refraq_sid")
    assert first_sid
    first_expiry = session_store._sessions[first_sid].expires_at  # noqa: SLF001

    assert client.patch("/settings", json={"admin_session_ttl_hours": 2}).status_code == 200
    # Existing session expiry unchanged
    assert session_store._sessions[first_sid].expires_at == first_expiry  # noqa: SLF001

    client.post("/auth/logout")
    before = time.time()
    assert (
        client.post("/auth/login", json={"account": "root", "password": "s3cret"}).status_code
        == 200
    )
    second_sid = client.cookies.get("refraq_sid")
    assert second_sid and second_sid != first_sid
    second_expiry = session_store._sessions[second_sid].expires_at  # noqa: SLF001
    # 2 hours ≈ 7200s; allow small scheduling skew
    assert 7100 <= (second_expiry - before) <= 7300


def test_permissions_catalog_includes_settings(client: TestClient) -> None:
    _login_root(client)
    response = client.get("/permissions")
    assert response.status_code == 200
    keys = {item["key"] for item in response.json()["items"]}
    assert "settings:read" in keys
    assert "settings:write" in keys
