"""Console module-identity API tests for docs/api-contracts-console.md."""

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

EXPECTED_IDENTITIES = {
    "dashboard": {
        "label_key": "layout.nav.home",
        "routes": {"list": "/console", "create": None, "edit": None},
        "actions": {
            "list": "dashboard:read",
            "create": None,
            "edit": None,
            "delete": None,
        },
    },
    "users": {
        "label_key": "users.title",
        "routes": {
            "list": "/console/users",
            "create": "/console/users/new",
            "edit": None,
        },
        "actions": {
            "list": "users:read",
            "create": "users:write",
            "edit": "users:write",
            "delete": "users:write",
        },
    },
    "roles": {
        "label_key": "roles.title",
        "routes": {
            "list": "/console/roles",
            "create": "/console/roles/new",
            "edit": "/console/roles/:id",
        },
        "actions": {
            "list": "roles:read",
            "create": "roles:write",
            "edit": "roles:write",
            "delete": "roles:write",
        },
    },
    "tokens": {
        "label_key": "tokens.title",
        "routes": {"list": None, "create": None, "edit": None},
        "actions": {
            "list": "tokens:read",
            "create": "tokens:write",
            "edit": "tokens:write",
            "delete": "tokens:write",
        },
    },
    "sources": {
        "label_key": "sources.title",
        "routes": {"list": "/console/sources", "create": None, "edit": None},
        "actions": {
            "list": "sources:read",
            "create": "sources:write",
            "edit": "sources:write",
            "delete": "sources:write",
        },
    },
    "catalog": {
        "label_key": "catalog.title",
        "routes": {"list": "/console/catalog", "create": None, "edit": None},
        "actions": {
            "list": "metadata:read",
            "create": None,
            "edit": None,
            "delete": None,
        },
    },
    "jobs": {
        "label_key": "jobs.title",
        "routes": {"list": "/console/jobs", "create": None, "edit": None},
        "actions": {
            "list": "jobs:run",
            "create": None,
            "edit": None,
            "delete": None,
        },
    },
    "settings": {
        "label_key": "settings.title",
        "routes": {"list": "/console/settings", "create": None, "edit": None},
        "actions": {
            "list": "settings:read",
            "create": None,
            "edit": "settings:write",
            "delete": None,
        },
    },
}


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


def test_module_identities_requires_auth(client: TestClient) -> None:
    response = client.get("/console/module-identities")
    assert response.status_code == 401


def test_module_identities_contract_for_super_admin(client: TestClient) -> None:
    assert (
        client.post("/auth/login", json={"account": "root", "password": "s3cret"}).status_code
        == 200
    )
    response = client.get("/console/module-identities")
    assert response.status_code == 200
    modules = {module["id"]: module for module in response.json()["modules"]}
    assert set(modules) == set(EXPECTED_IDENTITIES)
    for module_id, expected in EXPECTED_IDENTITIES.items():
        actual = modules[module_id]
        assert actual["label_key"] == expected["label_key"]
        assert actual["routes"] == expected["routes"]
        assert actual["actions"] == expected["actions"]


def test_operator_receives_full_unfiltered_identities(client: TestClient) -> None:
    """Identities are UX wiring, not nav: operator still gets every Foundation module."""
    assert (
        client.post("/auth/login", json={"account": "op", "password": "op-pass"}).status_code
        == 200
    )
    identities = client.get("/console/module-identities")
    assert identities.status_code == 200
    assert {m["id"] for m in identities.json()["modules"]} == set(EXPECTED_IDENTITIES)

    navigation = client.get("/console/navigation")
    assert navigation.status_code == 200
    nav_ids = {
        module["id"]
        for group in navigation.json()["groups"]
        for module in group["modules"]
    }
    assert nav_ids == {"dashboard"}
