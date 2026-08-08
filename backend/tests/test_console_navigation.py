"""Console navigation API tests for docs/api-contracts-console.md."""

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


def test_navigation_requires_auth(client: TestClient) -> None:
    response = client.get("/console/navigation")
    assert response.status_code == 401


def test_super_admin_sees_all_seed_modules(client: TestClient) -> None:
    assert (
        client.post("/auth/login", json={"account": "root", "password": "s3cret"}).status_code
        == 200
    )
    response = client.get("/console/navigation")
    assert response.status_code == 200
    groups = {group["id"]: group for group in response.json()["groups"]}
    assert set(groups) == {"workbench", "admin", "metadata", "settings"}
    assert [m["id"] for m in groups["workbench"]["modules"]] == ["dashboard"]
    assert [m["id"] for m in groups["admin"]["modules"]] == ["users", "roles"]
    assert [m["id"] for m in groups["metadata"]["modules"]] == [
        "sources",
        "catalog",
        "jobs",
    ]
    assert [m["id"] for m in groups["settings"]["modules"]] == ["settings"]
    assert groups["settings"]["modules"][0]["label_key"] == "settings.title"
    assert groups["settings"]["modules"][0]["route"] == "/console/settings"


def test_operator_omits_admin_and_settings(client: TestClient) -> None:
    assert (
        client.post("/auth/login", json={"account": "op", "password": "op-pass"}).status_code
        == 200
    )
    response = client.get("/console/navigation")
    assert response.status_code == 200
    groups = response.json()["groups"]
    assert len(groups) == 1
    assert groups[0]["id"] == "workbench"
    assert [m["id"] for m in groups[0]["modules"]] == ["dashboard"]
