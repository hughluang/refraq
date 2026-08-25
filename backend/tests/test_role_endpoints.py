"""Role API tests for docs/api-contracts-roles.md."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.security import hash_password  # noqa: E402
from backend.main import app  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.role_store import (  # noqa: E402
    MemoryRoleStore,
    reset_role_store,
)
from backend.admin.session_store import (  # noqa: E402
    MemorySessionStore,
    reset_session_store,
)
from backend.admin.user_store import (  # noqa: E402
    MemoryUserStore,
    reset_user_store,
)


@pytest.fixture
def store_bundle():
    reset_user_store()
    reset_role_store()
    reset_session_store()
    role_store = MemoryRoleStore()
    seed_roles(role_store)
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


@pytest.fixture
def client(store_bundle):
    user_store, role_store, session_store = store_bundle
    from backend.admin.role_store import get_role_store
    from backend.admin.session_store import get_session_store
    from backend.admin.user_store import get_user_store

    app.dependency_overrides[get_user_store] = lambda: user_store
    app.dependency_overrides[get_role_store] = lambda: role_store
    app.dependency_overrides[get_session_store] = lambda: session_store
    with TestClient(app) as test_client:
        yield test_client


def _login_root(client: TestClient) -> None:
    response = client.post(
        "/auth/login", json={"account": "root", "password": "s3cret"}
    )
    assert response.status_code == 200


def test_list_permissions_catalog(client: TestClient) -> None:
    _login_root(client)
    response = client.get("/permissions")
    assert response.status_code == 200
    keys = {item["key"] for item in response.json()["items"]}
    assert "console:access" in keys
    assert "roles:write" in keys


def test_list_roles_includes_seeds(client: TestClient) -> None:
    _login_root(client)
    response = client.get("/roles")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    assert body["limit"] == 50
    assert body["offset"] == 0
    by_key = {item["key"]: item for item in body["items"]}
    assert by_key["super_admin"]["locked"] is True
    assert by_key["operator"]["locked"] is False
    assert by_key["operator"]["user_count"] == 1


def test_list_roles_expands_system_role_permissions(
    client: TestClient, store_bundle
) -> None:
    from backend.admin.permissions import ALL_PERMISSIONS

    _login_root(client)
    _users, role_store, _sessions = store_bundle
    stored = role_store.get_by_key("super_admin")
    assert stored is not None
    assert stored.permissions == []

    response = client.get("/roles")
    assert response.status_code == 200
    by_key = {item["key"]: item for item in response.json()["items"]}
    assert by_key["super_admin"]["permissions"] == list(ALL_PERMISSIONS)
    assert "catalog:sample" in by_key["super_admin"]["permissions"]
    assert "branding:read" in by_key["super_admin"]["permissions"]
    assert "branding:write" in by_key["super_admin"]["permissions"]


def test_create_and_update_role(client: TestClient) -> None:
    _login_root(client)
    created = client.post(
        "/roles",
        json={
            "key": "analyst",
            "name": "Analyst",
            "permissions": ["console:access", "dashboard:read"],
        },
    )
    assert created.status_code == 201
    role_id = created.json()["role"]["id"]

    updated = client.patch(
        f"/roles/{role_id}",
        json={"name": "Analysts", "permissions": ["console:access"]},
    )
    assert updated.status_code == 200
    assert updated.json()["role"]["name"] == "Analysts"
    assert updated.json()["role"]["permissions"] == ["console:access"]


def test_create_role_rejects_unknown_permission(client: TestClient) -> None:
    _login_root(client)
    response = client.post(
        "/roles",
        json={
            "key": "bad",
            "name": "Bad",
            "permissions": ["console:access", "not:a_real_perm"],
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "ROLE_INVALID_PERMISSION"


def test_cannot_patch_locked_super_admin(client: TestClient, store_bundle) -> None:
    _login_root(client)
    _, role_store, _ = store_bundle
    super_admin = role_store.get_by_key("super_admin")
    assert super_admin is not None
    response = client.patch(
        f"/roles/{super_admin.id}",
        json={"name": "Hacked"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "ROLE_LOCKED"


def test_cannot_delete_locked_or_in_use_role(client: TestClient, store_bundle) -> None:
    _login_root(client)
    _, role_store, _ = store_bundle
    super_admin = role_store.get_by_key("super_admin")
    operator = role_store.get_by_key("operator")
    assert super_admin is not None and operator is not None

    locked = client.delete(f"/roles/{super_admin.id}")
    assert locked.status_code == 403
    assert locked.json()["code"] == "ROLE_LOCKED"

    in_use = client.delete(f"/roles/{operator.id}")
    assert in_use.status_code == 409
    assert in_use.json()["code"] == "ROLE_IN_USE"


def test_delete_unused_role(client: TestClient) -> None:
    _login_root(client)
    created = client.post(
        "/roles",
        json={
            "key": "temp",
            "name": "Temp",
            "permissions": ["dashboard:read"],
        },
    )
    role_id = created.json()["role"]["id"]
    deleted = client.delete(f"/roles/{role_id}")
    assert deleted.status_code == 204
    assert client.get(f"/roles/{role_id}").status_code == 404


def test_operator_cannot_manage_roles(client: TestClient) -> None:
    response = client.post(
        "/auth/login", json={"account": "op", "password": "op-pass"}
    )
    assert response.status_code == 200
    assert client.get("/roles").status_code == 403
