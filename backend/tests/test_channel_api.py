"""Data Channel HTTP tests against the memory store."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.main import app  # noqa: E402

TRIGGER_GRAPH = {
    "nodes": [
        {
            "id": "nd_trigger",
            "ref": "run_manually",
            "type": "trigger.manual",
            "name": "Run manually",
            "position": {"x": 0, "y": 0},
            "config": {},
            "on_error": "stop",
            "retry": None,
        }
    ],
    "edges": [],
    "settings": {"run_timeout_sec": None, "error_channel_id": None},
}


def _login(client: TestClient, account: str, password: str) -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": password}
    )
    assert response.status_code == 200, response.text


@pytest.fixture()
def client() -> TestClient:
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )
    with TestClient(app) as test_client:
        _login(test_client, "admin", "secret")
        yield test_client


def test_unauthenticated_is_rejected() -> None:
    with TestClient(app) as client:
        response = client.get("/channels")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_read_permission_cannot_write() -> None:
    roles = get_role_store()
    seed_roles(roles)
    role = create_role(
        roles,
        key="channel_reader",
        name="Channel reader",
        permissions=["console:access", "channel:read"],
    )
    get_user_store().create_user(
        account="reader",
        display_name="Reader",
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    with TestClient(app) as client:
        _login(client, "reader", "secret")
        assert client.get("/channels").status_code == 200
        denied = client.post(
            "/channels", json={"name": "Material", "description": None}
        )
    assert denied.status_code == 403


def test_create_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/channels", json={"name": "Material", "description": None, "active": True}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_draft_conflict_and_invalid_publish(client: TestClient) -> None:
    created = client.post("/channels", json={"name": "Material", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    assert created.json()["channel"]["active"] is False
    assert created.json()["channel"]["draft_revision"] == 1
    assert created.json()["channel"]["latest_version"] is None

    conflict = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": 9, "graph": TRIGGER_GRAPH},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CHANNEL_DRAFT_CONFLICT"

    broken = {
        "nodes": [
            {
                "id": "nd_read",
                "ref": "read_suppliers",
                "type": "read.entity",
                "name": "Read",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            }
        ],
        "edges": [],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": 1, "graph": broken},
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()["draft_revision"]
    published = client.post(
        f"/channels/{channel_id}/publish",
        json={"draft_revision": revision},
    )
    assert published.status_code == 422
    body = published.json()
    assert body["code"] == "CHANNEL_GRAPH_INVALID"
    assert body["detail"]

    checked = client.post(f"/channels/{channel_id}/draft/validate")
    assert checked.status_code == 200
    assert checked.json()["valid"] is False
    assert checked.json()["problems"]
    assert checked.json()["ports"]
    assert "schema" in checked.json()["ports"][0]


def test_node_type_catalog_and_audit(client: TestClient) -> None:
    catalog = client.get("/channel-node-types")
    assert catalog.status_code == 200, catalog.text
    items = catalog.json()["items"]
    assert [item["type"] for item in items] == [
        "trigger.manual",
        "read.entity",
        "write.entity",
    ]
    assert items[0]["entry"] is True
    assert items[0]["label"] == "Manual trigger"
    assert items[0]["summary"]
    assert items[0]["description"]
    assert items[0]["inputs"] == []
    assert items[0]["outputs"][0]["port"] == "main"
    assert items[0]["outputs"][0]["coarse_type"] == "object"
    assert items[0]["outputs"][0]["description"]
    assert items[0]["type_version"] == 1
    assert all(item["permission"] is None for item in items)
    assert "x-refraq-ref" in items[1]["config_schema"]["properties"]["entity_id"]
    assert "x-refraq-template" in items[2]["config_schema"]["properties"]["source"]

    created = client.post(
        "/channels", json={"name": "Material", "description": "from U9"}
    )
    assert created.status_code == 201
    events, _cursor = get_audit_store().list_events(limit=20)
    assert any(event.action == "channel.create" for event in events)


def test_activate_and_deactivate(client: TestClient) -> None:
    created = client.post("/channels", json={"name": "Material", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    assert created.json()["channel"]["active"] is False

    activated = client.post(f"/channels/{channel_id}/activate")
    assert activated.status_code == 200, activated.text
    assert activated.json()["channel"]["active"] is True
    again = client.post(f"/channels/{channel_id}/activate")
    assert again.status_code == 200
    assert again.json()["channel"]["active"] is True

    deactivated = client.post(f"/channels/{channel_id}/deactivate")
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["channel"]["active"] is False
    current = client.get(f"/channels/{channel_id}")
    assert current.status_code == 200
    assert current.json()["channel"]["active"] is False
