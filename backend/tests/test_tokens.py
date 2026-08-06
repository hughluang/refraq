"""User PAT API and Session-or-PAT auth tests."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.main import app  # noqa: E402
from backend.repositories.audit_store import (  # noqa: E402
    MemoryAuditStore,
    reset_audit_store,
)
from backend.repositories.role_store import MemoryRoleStore, reset_role_store  # noqa: E402
from backend.repositories.session_store import (  # noqa: E402
    MemorySessionStore,
    reset_session_store,
)
from backend.repositories.token_store import (  # noqa: E402
    MemoryTokenStore,
    reset_token_store,
)
from backend.repositories.user_store import MemoryUserStore, reset_user_store  # noqa: E402


@pytest.fixture
def store_bundle():
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_token_store()
    reset_audit_store()
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
    audit_store = MemoryAuditStore()
    yield user_store, role_store, session_store, token_store, audit_store
    app.dependency_overrides.clear()
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_token_store()
    reset_audit_store()


@pytest.fixture
def client(store_bundle):
    user_store, role_store, session_store, token_store, audit_store = store_bundle
    from backend.repositories.audit_store import get_audit_store as _get_audit
    from backend.repositories.role_store import get_role_store
    from backend.repositories.session_store import get_session_store
    from backend.repositories.token_store import get_token_store
    from backend.repositories.user_store import get_user_store

    app.dependency_overrides[get_user_store] = lambda: user_store
    app.dependency_overrides[get_role_store] = lambda: role_store
    app.dependency_overrides[get_session_store] = lambda: session_store
    app.dependency_overrides[get_token_store] = lambda: token_store
    app.dependency_overrides[_get_audit] = lambda: audit_store
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient) -> None:
    response = client.post("/auth/login", json={"account": "root", "password": "s3cret"})
    assert response.status_code == 200


def test_create_list_revoke_token(client: TestClient) -> None:
    _login(client)
    expires = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
    created = client.post("/tokens", json={"name": "mcp-local", "expires_at": expires})
    assert created.status_code == 201
    body = created.json()
    assert body["secret"].startswith("rfq_pat_")
    assert "secret" not in body["token"]
    token_id = body["token"]["id"]

    listed = client.get("/tokens")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert "secret" not in listed.json()["items"][0]

    secret = body["secret"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {secret}"})
    # Session cookie still present and preferred — still 200
    assert me.status_code == 200

    revoked = client.post(f"/tokens/{token_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["token"]["revoked_at"] is not None

    # Clear cookies so Bearer is used
    client.cookies.clear()
    me_pat = client.get("/auth/me", headers={"Authorization": f"Bearer {secret}"})
    assert me_pat.status_code == 401
    assert me_pat.json()["code"] == "AUTH_PAT_INVALID"

    events = client.get("/audit/events")
    # no session — need re-login for audit
    _login(client)
    events = client.get("/audit/events")
    assert events.status_code == 200
    actions = {item["action"] for item in events.json()["items"]}
    assert "token.create" in actions
    assert "token.revoke" in actions
    for item in events.json()["items"]:
        assert "secret" not in item["detail"]


def test_bearer_auth_me_without_session(client: TestClient, store_bundle) -> None:
    _login(client)
    expires = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
    created = client.post("/tokens", json={"name": "agent", "expires_at": expires})
    secret = created.json()["secret"]
    client.cookies.clear()
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {secret}"})
    assert me.status_code == 200
    assert me.json()["user"]["account"] == "root"
    assert "tokens:write" in me.json()["user"]["permissions"]


def test_invalid_bearer_returns_pat_invalid(client: TestClient) -> None:
    response = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer rfq_pat_not-a-real-token"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_PAT_INVALID"


def test_tokens_forbidden_without_permission(client: TestClient, store_bundle) -> None:
    user_store, role_store, *_ = store_bundle
    limited = create_role(
        role_store,
        key="tokenless",
        name="Tokenless",
        permissions=["console:access", "dashboard:read"],
    )
    user_store.create_user(
        account="ops",
        display_name="Ops",
        password_hash=hash_password("s3cret"),
        role_id=limited.id,
        status="active",
    )
    login = client.post("/auth/login", json={"account": "ops", "password": "s3cret"})
    assert login.status_code == 200
    response = client.get("/tokens")
    assert response.status_code == 403
