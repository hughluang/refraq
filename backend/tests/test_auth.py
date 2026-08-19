"""Auth API tests covering docs/api-contracts-auth.md §9."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.security import hash_password  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
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
    assert super_admin is not None
    user_store.create_user(
        account="root",
        display_name="Root Admin",
        password_hash=hash_password("s3cret"),
        role_id=super_admin.id,
        status="active",
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


def test_login_success_returns_user_and_cookie(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"account": "root", "password": "s3cret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["account"] == "root"
    assert body["user"]["role_key"] == "super_admin"
    assert "users:write" in body["user"]["permissions"]
    assert "console:access" in body["user"]["permissions"]
    assert "refraq_sid" in response.cookies


def test_login_wrong_password_returns_invalid_credentials(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"account": "root", "password": "wrong"},
    )

    assert response.status_code == 401
    assert_problem(
        response,
        status=401,
        code="AUTH_INVALID_CREDENTIALS",
        detail="Invalid account or password",
    )


def test_login_unknown_account_returns_invalid_credentials(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"account": "ghost", "password": "whatever"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_INVALID_CREDENTIALS"


def test_login_disabled_account_returns_account_disabled(
    store_bundle, client: TestClient
) -> None:
    user_store, _, _ = store_bundle
    users, _ = user_store.list_users()
    user_store.update_status(users[0].id, "disabled")

    response = client.post(
        "/auth/login",
        json={"account": "root", "password": "s3cret"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_ACCOUNT_DISABLED"


def test_login_without_console_access_is_rejected(
    store_bundle, client: TestClient
) -> None:
    user_store, role_store, _ = store_bundle
    no_console = create_role(
        role_store,
        key="no_console",
        name="No Console",
        permissions=["dashboard:read"],
    )
    user_store.create_user(
        account="guest",
        display_name="Guest",
        password_hash=hash_password("guest-pass"),
        role_id=no_console.id,
    )

    response = client.post(
        "/auth/login",
        json={"account": "guest", "password": "guest-pass"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_CONSOLE_ACCESS_REQUIRED"


def test_login_without_role_is_rejected(store_bundle, client: TestClient) -> None:
    user_store, _, _ = store_bundle
    user_store.create_user(
        account="norole",
        display_name="No Role",
        password_hash=hash_password("norole-pass"),
        role_id=None,
    )

    response = client.post(
        "/auth/login",
        json={"account": "norole", "password": "norole-pass"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_CONSOLE_ACCESS_REQUIRED"


def test_me_with_valid_cookie_returns_current_user(client: TestClient) -> None:
    client.post("/auth/login", json={"account": "root", "password": "s3cret"})

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["user"]["account"] == "root"


def test_me_without_cookie_returns_unauthenticated(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_me_with_expired_session_returns_unauthenticated(
    store_bundle, client: TestClient
) -> None:
    user_store, _, session_store = store_bundle
    users, _ = user_store.list_users()
    sid = session_store.create(users[0].id, ttl_seconds=-1)

    response = client.get("/auth/me", cookies={"refraq_sid": sid})

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_logout_delete_cookie_matches_secure_attrs(
    store_bundle, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.core.config import Settings, get_settings

    # Env wins over init for BaseSettings; force prod for Secure cookie attrs.
    monkeypatch.setenv("REFRAQ_ENV", "prod")
    secure_settings = Settings(
        store_backend="memory",
        admin_session_secret="test-secret",
        initial_admin_account="root",
        initial_admin_password="s3cret",
    )
    monkeypatch.setattr(
        "backend.admin.routers.auth.get_settings", lambda: secure_settings
    )
    app.dependency_overrides[get_settings] = lambda: secure_settings

    login_response = client.post(
        "/auth/login", json={"account": "root", "password": "s3cret"}
    )
    assert login_response.status_code == 200

    response = client.post("/auth/logout")
    assert response.status_code == 200

    set_cookie_headers = response.headers.get_list("set-cookie")
    logout_cookie = next(
        (h for h in set_cookie_headers if h.startswith("refraq_sid=")),
        None,
    )
    assert logout_cookie is not None
    assert "Secure" in logout_cookie
    assert "HttpOnly" in logout_cookie
    assert "Path=/" in logout_cookie


def test_logout_clears_cookie_and_invalidates_session(client: TestClient) -> None:
    login_response = client.post(
        "/auth/login", json={"account": "root", "password": "s3cret"}
    )
    assert login_response.status_code == 200
    sid_cookie = login_response.cookies.get("refraq_sid")
    assert sid_cookie

    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"success": True}

    follow = client.get("/auth/me")
    assert follow.status_code == 401


def test_logout_without_session_still_returns_success(client: TestClient) -> None:
    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"success": True}


def test_healthz_remains_accessible(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_session_purge_is_lazy() -> None:
    store = MemorySessionStore()
    sid = store.create("user_x", ttl_seconds=1)
    time.sleep(1.1)
    assert store.get(sid) is None
