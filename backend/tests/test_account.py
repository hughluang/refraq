"""Account Center API tests for docs/api-contracts-account.md."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.security import hash_password, verify_password  # noqa: E402
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
from backend.admin.token_store import (  # noqa: E402
    MemoryTokenStore,
    reset_token_store,
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
    reset_token_store()
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
    token_store = MemoryTokenStore()
    yield user_store, role_store, session_store, token_store
    app.dependency_overrides.clear()
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_token_store()


@pytest.fixture
def client(store_bundle):
    user_store, role_store, session_store, token_store = store_bundle
    from backend.admin.role_store import get_role_store
    from backend.admin.session_store import get_session_store
    from backend.admin.token_store import get_token_store
    from backend.admin.user_store import get_user_store

    app.dependency_overrides[get_user_store] = lambda: user_store
    app.dependency_overrides[get_role_store] = lambda: role_store
    app.dependency_overrides[get_session_store] = lambda: session_store
    app.dependency_overrides[get_token_store] = lambda: token_store
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient) -> None:
    assert (
        client.post("/auth/login", json={"account": "root", "password": "s3cret"}).status_code
        == 200
    )


def test_me_includes_email_and_locale(client: TestClient) -> None:
    _login(client)
    body = client.get("/auth/me").json()["user"]
    assert body["email"] is None
    assert body["locale"] == "en-US"


def test_update_profile(client: TestClient, store_bundle) -> None:
    user_store, _, _, _ = store_bundle
    _login(client)
    response = client.patch(
        "/account/profile",
        json={
            "display_name": "Root Renamed",
            "email": "root@example.com",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["display_name"] == "Root Renamed"
    assert user["email"] == "root@example.com"
    assert user["locale"] == "zh-CN"
    stored = user_store.get_by_account("root")
    assert stored is not None
    assert stored.locale == "zh-CN"


def test_update_profile_clear_email(client: TestClient) -> None:
    _login(client)
    assert (
        client.patch("/account/profile", json={"email": "a@b.com"}).status_code == 200
    )
    cleared = client.patch("/account/profile", json={"email": ""})
    assert cleared.status_code == 200
    assert cleared.json()["user"]["email"] is None


def test_update_profile_invalid_locale(client: TestClient) -> None:
    _login(client)
    response = client.patch("/account/profile", json={"locale": "fr-FR"})
    assert response.status_code == 400
    assert response.json()["code"] == "ACCOUNT_INVALID_LOCALE"


def test_update_profile_empty(client: TestClient) -> None:
    _login(client)
    response = client.patch("/account/profile", json={})
    assert response.status_code == 400
    assert response.json()["code"] == "ACCOUNT_PROFILE_EMPTY"


def test_change_password_keeps_current_session(client: TestClient, store_bundle) -> None:
    user_store, _, session_store, _ = store_bundle
    user = user_store.get_by_account("root")
    assert user is not None
    other_sid = session_store.create(user.id, 3600)
    _login(client)
    current_sid = client.cookies.get("refraq_sid")
    assert current_sid
    assert other_sid != current_sid

    response = client.post(
        "/account/password",
        json={"current_password": "s3cret", "new_password": "n3w-pass"},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert session_store.get(current_sid) == user.id
    assert session_store.get(other_sid) is None
    assert verify_password("n3w-pass", user_store.get_by_id(user.id).password_hash)  # type: ignore[union-attr]

    me = client.get("/auth/me")
    assert me.status_code == 200


def test_change_password_wrong_current(client: TestClient) -> None:
    _login(client)
    response = client.post(
        "/account/password",
        json={"current_password": "wrong", "new_password": "n3w-pass"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "ACCOUNT_PASSWORD_INVALID"


def test_change_password_requires_session_not_pat_only(
    client: TestClient, store_bundle
) -> None:
    from datetime import datetime, timedelta

    from backend.admin.token_store import generate_token_secret

    user_store, _, _, token_store = store_bundle
    user = user_store.get_by_account("root")
    assert user is not None
    secret, prefix, token_hash = generate_token_secret()
    token_store.create(
        user_id=user.id,
        name="cli",
        token_hash=token_hash,
        prefix=prefix,
        expires_at=datetime.utcnow() + timedelta(days=1),
    )
    response = client.post(
        "/account/password",
        headers={"Authorization": f"Bearer {secret}"},
        json={"current_password": "s3cret", "new_password": "n3w-pass"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "ACCOUNT_PASSWORD_SESSION_REQUIRED"
