"""User management API tests for docs/api-contracts-users.md."""

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


def _build_stores() -> tuple[MemoryUserStore, MemoryRoleStore, MemorySessionStore]:
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
        status="active",
    )
    user_store.create_user(
        account="op",
        display_name="Operator",
        password_hash=hash_password("op-pass"),
        role_id=operator.id,
        status="active",
    )
    session_store = MemorySessionStore()
    return user_store, role_store, session_store


@pytest.fixture
def store_bundle():
    user_store, role_store, session_store = _build_stores()
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


def _login_as(client: TestClient, account: str, password: str) -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": password}
    )
    assert response.status_code == 200, response.text


def test_super_admin_can_list_users(client: TestClient) -> None:
    _login_as(client, "root", "s3cret")

    response = client.get("/users")

    assert response.status_code == 200
    body = response.json()
    accounts = {item["account"] for item in body["items"]}
    assert accounts == {"root", "op"}
    assert body["total"] == 2
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_operator_cannot_list_users(client: TestClient) -> None:
    _login_as(client, "op", "op-pass")

    response = client.get("/users")

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_FORBIDDEN"


def test_super_admin_can_create_user(client: TestClient, store_bundle) -> None:
    _login_as(client, "root", "s3cret")
    _, role_store, _ = store_bundle
    operator = role_store.get_by_key("operator")
    assert operator is not None

    response = client.post(
        "/users",
        json={
            "account": "alice",
            "display_name": "Alice",
            "password": "alice-pass",
            "role_id": operator.id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["account"] == "alice"
    assert body["user"]["role_key"] == "operator"
    assert body["user"]["status"] == "active"


def test_create_user_without_role(client: TestClient) -> None:
    _login_as(client, "root", "s3cret")

    response = client.post(
        "/users",
        json={
            "account": "norole",
            "display_name": "No Role",
            "password": "norole-pass",
            "role_id": None,
        },
    )

    assert response.status_code == 201
    assert response.json()["user"]["role_id"] is None


def test_create_user_with_unknown_role_returns_invalid_role(client: TestClient) -> None:
    _login_as(client, "root", "s3cret")

    response = client.post(
        "/users",
        json={
            "account": "bob",
            "display_name": "Bob",
            "password": "bob-pass",
            "role_id": "role_does_not_exist",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "USER_INVALID_ROLE"


def test_create_user_with_duplicate_account_returns_conflict(client: TestClient) -> None:
    _login_as(client, "root", "s3cret")

    response = client.post(
        "/users",
        json={
            "account": "op",
            "display_name": "Duplicate Op",
            "password": "x",
            "role_id": None,
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "USER_ACCOUNT_DUPLICATE"


def test_super_admin_can_disable_other_user(client: TestClient) -> None:
    _login_as(client, "root", "s3cret")

    op_id = next(
        item["id"]
        for item in client.get("/users").json()["items"]
        if item["account"] == "op"
    )

    response = client.patch(
        f"/users/{op_id}/status", json={"status": "disabled"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["status"] == "disabled"


def test_super_admin_cannot_disable_themselves(client: TestClient) -> None:
    _login_as(client, "root", "s3cret")

    root_id = next(
        item["id"]
        for item in client.get("/users").json()["items"]
        if item["account"] == "root"
    )

    response = client.patch(
        f"/users/{root_id}/status", json={"status": "disabled"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "USER_SELF_DISABLE_FORBIDDEN"


def test_disabled_user_cannot_login(store_bundle, client: TestClient) -> None:
    user_store, _, _ = store_bundle
    users, _ = user_store.list_users()
    op_record = next(r for r in users if r.account == "op")
    user_store.update_status(op_record.id, "disabled")

    response = client.post(
        "/auth/login", json={"account": "op", "password": "op-pass"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_ACCOUNT_DISABLED"


def test_patch_status_for_missing_user_returns_not_found(client: TestClient) -> None:
    _login_as(client, "root", "s3cret")

    response = client.patch(
        "/users/user_does_not_exist/status", json={"status": "active"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "USER_NOT_FOUND"


def test_unauthenticated_request_returns_unauthenticated(client: TestClient) -> None:
    response = client.get("/users")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_patch_invalid_status_returns_invalid_status(client: TestClient) -> None:
    _login_as(client, "root", "s3cret")
    op_id = next(
        item["id"]
        for item in client.get("/users").json()["items"]
        if item["account"] == "op"
    )

    response = client.patch(
        f"/users/{op_id}/status", json={"status": "ghost"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "USER_INVALID_STATUS"


def test_disable_revokes_target_sessions_and_requires_relogin(
    store_bundle, client: TestClient
) -> None:
    user_store, _, session_store = store_bundle
    users, _ = user_store.list_users()
    op = next(record for record in users if record.account == "op")
    op_sid = session_store.create(op.id, ttl_seconds=3600)

    assert client.get("/auth/me", cookies={"refraq_sid": op_sid}).status_code == 200

    _login_as(client, "root", "s3cret")
    disable = client.patch(f"/users/{op.id}/status", json={"status": "disabled"})
    assert disable.status_code == 200
    assert disable.json()["user"]["status"] == "disabled"

    me_after_disable = client.get("/auth/me", cookies={"refraq_sid": op_sid})
    assert me_after_disable.status_code == 401
    assert me_after_disable.json()["code"] == "AUTH_UNAUTHENTICATED"

    reenable = client.patch(f"/users/{op.id}/status", json={"status": "active"})
    assert reenable.status_code == 200
    assert reenable.json()["user"]["status"] == "active"

    assert client.get("/auth/me", cookies={"refraq_sid": op_sid}).status_code == 401

    login = client.post("/auth/login", json={"account": "op", "password": "op-pass"})
    assert login.status_code == 200
    assert client.get("/auth/me").status_code == 200
