"""Draft change-log switch and retention on the entity HTTP API."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.main import app  # noqa: E402


SKU = {
    "name": "sku",
    "type": "string",
    "required": True,
    "unique": True,
    "indexed": False,
    "description": "SKU code",
    "config": {"max_length": 32},
}


def _create_body(**overrides: object) -> dict:
    body: dict = {
        "table_name": "material",
        "name": "Material",
        "description": "A stock-keeping material.",
        "attributes": [SKU],
    }
    body.update(overrides)
    return body


def _version(client: TestClient, entity: dict) -> dict:
    version_id = entity["current_version"]["id"]
    response = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert response.status_code == 200, response.text
    return response.json()["version"]


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
        login = test_client.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        yield test_client


def test_new_entity_change_log_is_off_and_never_expires(client: TestClient) -> None:
    created = client.post("/entities", json=_create_body())
    assert created.status_code == 201, created.text
    version = _version(client, created.json()["entity"])
    assert version["change_log_enabled"] is False
    assert version["change_log_retention_days"] is None


def test_create_stores_change_log_switch_and_retention(client: TestClient) -> None:
    created = client.post(
        "/entities",
        json=_create_body(
            table_name="logged_material",
            change_log_enabled=True,
            change_log_retention_days=14,
        ),
    )
    assert created.status_code == 201, created.text
    version = _version(client, created.json()["entity"])
    assert version["change_log_enabled"] is True
    assert version["change_log_retention_days"] == 14


def test_draft_save_persists_change_log_and_does_not_enqueue_publish(
    client: TestClient,
) -> None:
    created = client.post("/entities", json=_create_body(table_name="draft_log"))
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    patched = client.patch(
        f"/entities/{entity['id']}",
        json={"change_log_enabled": True, "change_log_retention_days": 30},
    )
    assert patched.status_code == 200, patched.text
    version = _version(client, patched.json()["entity"])
    assert version["change_log_enabled"] is True
    assert version["change_log_retention_days"] == 30
    assert version["publish_status"] == "unpublished"
    assert version["alignment"]["latest_job_id"] is None
    jobs = client.get("/jobs", params={"kind": "entity_reconcile"})
    assert jobs.status_code == 200, jobs.text
    assert jobs.json()["total"] == 0


def test_published_version_refuses_change_log_edits(client: TestClient) -> None:
    created = client.post(
        "/entities",
        json=_create_body(
            table_name="published_log",
            change_log_enabled=True,
            change_log_retention_days=7,
        ),
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    published = client.post(f"/entities/{entity['id']}/versions/{version_id}/publish")
    assert published.status_code == 201, published.text
    refused = client.patch(
        f"/entities/{entity['id']}",
        json={"change_log_enabled": False, "change_log_retention_days": 1},
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "ENTITY_NOT_UNPUBLISHED"
    version = _version(client, entity)
    assert version["change_log_enabled"] is True
    assert version["change_log_retention_days"] == 7


def test_turning_draft_switch_off_keeps_retention(client: TestClient) -> None:
    created = client.post(
        "/entities",
        json=_create_body(
            table_name="kept_window",
            change_log_enabled=True,
            change_log_retention_days=30,
        ),
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    patched = client.patch(
        f"/entities/{entity['id']}",
        json={"change_log_enabled": False},
    )
    assert patched.status_code == 200, patched.text
    version = _version(client, entity)
    assert version["change_log_enabled"] is False
    assert version["change_log_retention_days"] == 30


@pytest.mark.parametrize("retention", [0, -1, 1.5])
def test_change_log_retention_rejects_non_positive_or_fractional(
    client: TestClient, retention: object
) -> None:
    created = client.post("/entities", json=_create_body(table_name="bad_window"))
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    refused = client.patch(
        f"/entities/{entity['id']}",
        json={"change_log_retention_days": retention},
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "REQUEST_INVALID"
    version = _version(client, entity)
    assert version["change_log_retention_days"] is None
    created_bad = client.post(
        "/entities",
        json=_create_body(
            table_name="bad_window_create",
            change_log_retention_days=retention,
        ),
    )
    assert created_bad.status_code == 422
    assert created_bad.json()["code"] == "REQUEST_INVALID"


def test_open_version_starts_change_log_off_and_never_expires(
    client: TestClient,
) -> None:
    created = client.post(
        "/entities",
        json=_create_body(
            table_name="next_draft",
            change_log_enabled=True,
            change_log_retention_days=9,
        ),
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    published = client.post(f"/entities/{entity['id']}/versions/{version_id}/publish")
    assert published.status_code == 201, published.text
    opened = client.post(f"/entities/{entity['id']}/versions", json={})
    assert opened.status_code == 201, opened.text
    draft = opened.json()["version"]
    assert draft["publish_status"] == "unpublished"
    assert draft["change_log_enabled"] is False
    assert draft["change_log_retention_days"] is None
    previous = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert previous.status_code == 200, previous.text
    assert previous.json()["version"]["change_log_enabled"] is True
    assert previous.json()["version"]["change_log_retention_days"] == 9


def test_draft_retention_can_return_to_never_expire(client: TestClient) -> None:
    created = client.post(
        "/entities",
        json=_create_body(
            table_name="clear_window",
            change_log_enabled=True,
            change_log_retention_days=12,
        ),
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    patched = client.patch(
        f"/entities/{entity['id']}",
        json={"change_log_retention_days": None},
    )
    assert patched.status_code == 200, patched.text
    version = _version(client, entity)
    assert version["change_log_enabled"] is True
    assert version["change_log_retention_days"] is None


def test_change_log_list_is_empty_without_an_entity_database(
    client: TestClient,
) -> None:
    created = client.post("/entities", json=_create_body(table_name="no_log_db"))
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    detail = client.get(f"/entities/{entity['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["entity"]["change_log_recording"] is False
    listed = client.get(f"/entities/{entity['id']}/change-log")
    assert listed.status_code == 200, listed.text
    assert listed.json() == {
        "items": [],
        "limit": 50,
        "next_before_sequence": None,
    }
    missing = client.get(f"/entities/{entity['id']}/change-log/1")
    assert missing.status_code == 404
    assert missing.json()["code"] == "ENTITY_NOT_FOUND"
