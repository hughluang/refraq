"""Business Entity HTTP tests (definition, versions, permissions)."""

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

from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
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


def test_create_list_get_and_empty_snapshot(client: TestClient) -> None:
    created = client.post("/entities", json=_create_body())
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    assert entity["table_name"] == "material"
    assert entity["current_version"]["version"] == 1
    assert entity["current_version"]["table_name"] is None
    assert entity["current_version"]["publish_status"] == "unpublished"
    assert entity["ever_published"] is False
    assert entity["deprecated_at"] is None
    assert entity["current_version"]["alignment"] == {
        "table_present": False,
        "latest_job_id": None,
        "latest_job_status": None,
    }

    listed = client.get("/entities")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == entity["id"]

    got = client.get(f"/entities/{entity['id']}")
    assert got.status_code == 200
    assert got.json()["entity"]["id"] == entity["id"]

    version = client.get(
        f"/entities/{entity['id']}/versions/{entity['current_version']['id']}"
    )
    assert version.status_code == 200
    body = version.json()["version"]
    assert body["attributes"][0]["name"] == "sku"
    assert body["attributes"][0]["unique"] is True
    assert body["attributes"][0]["indexed"] is False
    assert body["alignment"]["table_present"] is False

    events, _ = get_audit_store().list_events(action="entity.create")
    assert len(events) == 1


def test_create_allows_empty_attributes(client: TestClient) -> None:
    created = client.post(
        "/entities",
        json=_create_body(table_name="empty_shape", attributes=[]),
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    version = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert version.status_code == 200
    body = version.json()["version"]
    assert body["attributes"] == []
    assert body["alignment"]["table_present"] is False

    listed = client.get(f"/entities/{entity['id']}/versions")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["attribute_count"] == 0

    saved = client.patch(
        f"/entities/{entity['id']}/versions/{version_id}",
        json={"attributes": []},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"]["attributes"] == []

    refused_open = client.post(
        f"/entities/{entity['id']}/versions",
        json={"attributes": []},
    )
    assert refused_open.status_code == 422
    assert refused_open.json()["code"] == "ENTITY_NOT_PUBLISHED"

    refused_publish = client.post(
        f"/entities/{entity['id']}/versions/{version_id}/publish"
    )
    assert refused_publish.status_code == 422
    assert refused_publish.json()["code"] == "ENTITY_PUBLISH_EMPTY"


def test_empty_attributes_from_populated_can_save(
    client: TestClient,
) -> None:
    entity = client.post("/entities", json=_create_body()).json()["entity"]
    version_id = entity["current_version"]["id"]
    saved = client.patch(
        f"/entities/{entity['id']}/versions/{version_id}",
        json={"attributes": []},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"]["attributes"] == []


def test_table_name_dup_and_invalid(client: TestClient) -> None:
    assert client.post("/entities", json=_create_body()).status_code == 201
    conflict = client.post("/entities", json=_create_body(name="Other"))
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "ENTITY_TABLE_NAME_DUP"

    invalid = client.post("/entities", json=_create_body(table_name="1bad"))
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "ENTITY_TABLE_NAME_INVALID"

    too_long = client.post("/entities", json=_create_body(table_name="a" * 49))
    assert too_long.status_code == 422
    assert too_long.json()["code"] == "ENTITY_TABLE_NAME_INVALID"

    unknown = client.post(
        "/entities", json=_create_body(table_name="with_extra", category="master_data")
    )
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "REQUEST_INVALID"

    archived_shape = client.post(
        "/entities", json=_create_body(table_name="material__rfq_v1")
    )
    assert archived_shape.status_code == 422
    assert archived_shape.json()["code"] == "ENTITY_TABLE_NAME_INVALID"


def test_reserved_row_id_is_rejected(client: TestClient) -> None:
    reserved = client.post(
        "/entities",
        json=_create_body(
            attributes=[
                {
                    "name": "row_id",
                    "type": "integer",
                    "required": True,
                    "config": {},
                }
            ]
        ),
    )
    assert reserved.status_code == 422
    body = reserved.json()
    assert body["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert body["detail"] == (
        "Attribute name 'row_id' is reserved for the platform primary key"
    )


def test_attribute_name_rules_report_concrete_detail(client: TestClient) -> None:
    charset = client.post(
        "/entities",
        json=_create_body(
            attributes=[
                {
                    "name": "1bad",
                    "type": "string",
                    "required": True,
                    "config": {"max_length": 32},
                }
            ]
        ),
    )
    assert charset.status_code == 422
    assert charset.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert "must start with a letter" in charset.json()["detail"]
    assert "1bad" in charset.json()["detail"]

    blank = client.post(
        "/entities",
        json=_create_body(
            attributes=[
                {
                    "name": "   ",
                    "type": "string",
                    "required": True,
                    "config": {"max_length": 32},
                }
            ]
        ),
    )
    assert blank.status_code == 422
    assert blank.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert blank.json()["detail"] == "Attribute name is required"

    duplicate = client.post(
        "/entities",
        json=_create_body(
            attributes=[
                {
                    "name": "sku",
                    "type": "string",
                    "required": True,
                    "config": {"max_length": 32},
                },
                {
                    "name": "sku",
                    "type": "integer",
                    "required": True,
                    "config": {},
                },
            ]
        ),
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"] == (
        "Attribute name 'sku' is already used in this version"
    )


def test_patch_entity_and_reject_code(client: TestClient) -> None:
    entity = client.post("/entities", json=_create_body()).json()["entity"]
    patched = client.patch(
        f"/entities/{entity['id']}",
        json={"name": "Stock material"},
    )
    assert patched.status_code == 200
    assert patched.json()["entity"]["name"] == "Stock material"
    assert patched.json()["entity"]["table_name"] == "material"

    rejected_code = client.patch(
        f"/entities/{entity['id']}",
        json={"table_name": "other"},
    )
    assert rejected_code.status_code == 422
    assert rejected_code.json()["code"] == "REQUEST_INVALID"

    rejected_category = client.patch(
        f"/entities/{entity['id']}",
        json={"category": "master_data"},
    )
    assert rejected_category.status_code == 422
    assert rejected_category.json()["code"] == "REQUEST_INVALID"

    events, _ = get_audit_store().list_events(action="entity.patch")
    assert events


def test_patch_entity_writes_attributes_and_omits_keep_shape(
    client: TestClient,
) -> None:
    entity = client.post("/entities", json=_create_body()).json()["entity"]
    version_id = entity["current_version"]["id"]
    next_sku = {**SKU, "name": "sku_code"}
    patched = client.patch(
        f"/entities/{entity['id']}",
        json={"name": "Stock material", "attributes": [next_sku]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["entity"]["name"] == "Stock material"
    version = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert version.status_code == 200
    assert version.json()["version"]["attributes"][0]["name"] == "sku_code"

    omitted = client.patch(
        f"/entities/{entity['id']}",
        json={"description": "Identity only."},
    )
    assert omitted.status_code == 200
    version = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert version.json()["version"]["attributes"][0]["name"] == "sku_code"

    published = client.post(
        f"/entities/{entity['id']}/versions/{version_id}/publish"
    )
    assert published.status_code == 201, published.text
    refused = client.patch(
        f"/entities/{entity['id']}",
        json={"attributes": [SKU]},
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "ENTITY_NOT_UNPUBLISHED"


def test_classify_and_breaking_can_save(client: TestClient) -> None:
    entity = client.post("/entities", json=_create_body()).json()["entity"]
    version_id = entity["current_version"]["id"]
    classified = client.post(
        f"/entities/{entity['id']}/classify",
        json={"attributes": [{**SKU, "name": "sku_code"}]},
    )
    assert classified.status_code == 200
    assert classified.json()["class"] == "breaking"

    unique_on = client.post(
        f"/entities/{entity['id']}/classify",
        json={"attributes": [{**SKU, "unique": False, "indexed": True}]},
    )
    assert unique_on.status_code == 200
    assert unique_on.json()["class"] == "non_breaking"

    saved = client.patch(
        f"/entities/{entity['id']}/versions/{version_id}",
        json={"attributes": [{**SKU, "name": "sku_code"}]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"]["attributes"][0]["name"] == "sku_code"


def test_non_breaking_in_place_and_open_version(client: TestClient) -> None:
    entity = client.post("/entities", json=_create_body()).json()["entity"]
    version_id = entity["current_version"]["id"]
    attrs = [
        SKU,
        {
            "name": "note",
            "type": "string",
            "required": False,
            "description": "Optional note",
            "config": {"max_length": 200},
        },
    ]
    patched = client.patch(
        f"/entities/{entity['id']}/versions/{version_id}",
        json={"attributes": attrs},
    )
    assert patched.status_code == 200, patched.text
    assert len(patched.json()["version"]["attributes"]) == 2

    refused_open = client.post(f"/entities/{entity['id']}/versions", json={})
    assert refused_open.status_code == 422
    assert refused_open.json()["code"] == "ENTITY_NOT_PUBLISHED"


def test_delete_entity_and_version_delete_is_absent(client: TestClient) -> None:
    entity = client.post("/entities", json=_create_body()).json()["entity"]
    deleted = client.delete(f"/entities/{entity['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/entities/{entity['id']}").status_code == 404

    again = client.post("/entities", json=_create_body()).json()["entity"]
    version_id = again["current_version"]["id"]
    removed = client.delete(f"/entities/{again['id']}/versions/{version_id}")
    assert removed.status_code == 405
    assert client.get(f"/entities/{again['id']}").status_code == 200


def test_permissions_and_operator_has_no_entity_keys(client: TestClient) -> None:
    roles = get_role_store()
    reader = create_role(
        roles,
        key="entity_reader",
        name="Entity reader",
        permissions=["console:access", "entity:read"],
    )
    writer = create_role(
        roles,
        key="entity_writer",
        name="Entity writer",
        permissions=["console:access", "entity:read", "entity:write"],
    )
    users = get_user_store()
    users.create_user(
        account="reader",
        display_name="Reader",
        password_hash=hash_password("secret"),
        role_id=reader.id,
        status="active",
    )
    users.create_user(
        account="writer",
        display_name="Writer",
        password_hash=hash_password("secret"),
        role_id=writer.id,
        status="active",
    )
    operator = roles.get_by_key("operator")
    assert operator is not None
    assert "entity:read" not in operator.permissions
    assert "entity:write" not in operator.permissions
    assert "entity:drop_table" not in operator.permissions

    client.post("/auth/logout")
    assert (
        client.post("/auth/login", json={"account": "reader", "password": "secret"}).status_code
        == 200
    )
    denied = client.post("/entities", json=_create_body())
    assert denied.status_code == 403

    client.post("/auth/logout")
    assert (
        client.post("/auth/login", json={"account": "writer", "password": "secret"}).status_code
        == 200
    )
    created = client.post("/entities", json=_create_body())
    assert created.status_code == 201
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    drop = client.post(f"/entities/{entity['id']}/versions/{version_id}/drop-table")
    assert drop.status_code == 403


def test_unknown_entity_is_404(client: TestClient) -> None:
    missing = client.get("/entities/ent_missing")
    assert missing.status_code == 404
    assert missing.json()["code"] == "ENTITY_NOT_FOUND"


def test_definition_ledger_route_is_absent(client: TestClient) -> None:
    entity = client.post("/entities", json=_create_body()).json()["entity"]
    missing = client.get(f"/entities/{entity['id']}/ledger")
    assert missing.status_code == 404


def test_publish_locks_and_open_version_unlocks(client: TestClient) -> None:
    entity = client.post("/entities", json=_create_body()).json()["entity"]
    version_id = entity["current_version"]["id"]
    published = client.post(f"/entities/{entity['id']}/versions/{version_id}/publish")
    assert published.status_code == 201, published.text
    job = published.json()["job"]
    assert job["status"] == "succeeded"

    detail = client.get(f"/entities/{entity['id']}")
    body = detail.json()["entity"]
    assert body["ever_published"] is True
    assert body["current_version"]["publish_status"] == "published"
    assert body["current_version"]["table_name"] == "material"

    identity = client.patch(f"/entities/{entity['id']}", json={"name": "Locked"})
    assert identity.status_code == 422
    assert identity.json()["code"] == "ENTITY_NOT_UNPUBLISHED"

    shape = client.patch(
        f"/entities/{entity['id']}/versions/{version_id}",
        json={"attributes": [SKU]},
    )
    assert shape.status_code == 422
    assert shape.json()["code"] == "ENTITY_NOT_UNPUBLISHED"

    deleted = client.delete(f"/entities/{entity['id']}")
    assert deleted.status_code == 409
    assert deleted.json()["code"] == "ENTITY_ALREADY_PUBLISHED"

    opened = client.post(f"/entities/{entity['id']}/versions", json={})
    assert opened.status_code == 201, opened.text
    assert opened.json()["version"]["publish_status"] == "unpublished"
    assert opened.json()["version"]["version"] == 2
    assert opened.json()["version"]["table_name"] is None
    v1 = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert v1.json()["version"]["table_name"] == "material"

    renamed = client.patch(f"/entities/{entity['id']}", json={"name": "Next draft"})
    assert renamed.status_code == 200
    assert renamed.json()["entity"]["name"] == "Next draft"


def test_deprecate_and_never_published(client: TestClient) -> None:
    unpublished = client.post(
        "/entities", json=_create_body(table_name="draft_only")
    ).json()["entity"]
    refused = client.post(f"/entities/{unpublished['id']}/deprecate")
    assert refused.status_code == 422
    assert refused.json()["code"] == "ENTITY_NEVER_PUBLISHED"

    entity = client.post("/entities", json=_create_body(table_name="to_retire")).json()["entity"]
    version_id = entity["current_version"]["id"]
    assert (
        client.post(f"/entities/{entity['id']}/versions/{version_id}/publish").status_code
        == 201
    )
    deprecated = client.post(f"/entities/{entity['id']}/deprecate")
    assert deprecated.status_code == 200, deprecated.text
    assert deprecated.json()["entity"]["deprecated_at"] is not None

    again = client.post(f"/entities/{entity['id']}/deprecate")
    assert again.status_code == 422
    assert again.json()["code"] == "ENTITY_ALREADY_DEPRECATED"

    opened = client.post(f"/entities/{entity['id']}/versions", json={})
    assert opened.status_code == 422
    assert opened.json()["code"] == "ENTITY_DEPRECATED"


def test_list_entities_filters_by_status(client: TestClient) -> None:
    draft = client.post(
        "/entities", json=_create_body(table_name="draft_row", name="Draft")
    ).json()["entity"]
    live = client.post(
        "/entities", json=_create_body(table_name="live_row", name="Live")
    ).json()["entity"]
    live_version = live["current_version"]["id"]
    assert (
        client.post(f"/entities/{live['id']}/versions/{live_version}/publish").status_code
        == 201
    )
    opened = client.post(f"/entities/{live['id']}/versions", json={})
    assert opened.status_code == 201, opened.text

    retired = client.post(
        "/entities", json=_create_body(table_name="retired_row", name="Retired")
    ).json()["entity"]
    retired_version = retired["current_version"]["id"]
    assert (
        client.post(
            f"/entities/{retired['id']}/versions/{retired_version}/publish"
        ).status_code
        == 201
    )
    assert client.post(f"/entities/{retired['id']}/deprecate").status_code == 200

    def listed(response):
        assert response.status_code == 200, response.text
        body = response.json()
        return {item["id"] for item in body["items"]}, body["total"]

    everything, total = listed(client.get("/entities"))
    assert total == 3
    assert everything == {draft["id"], live["id"], retired["id"]}

    active, active_total = listed(
        client.get(
            "/entities",
            params=[("status", "not_serving"), ("status", "serving")],
        )
    )
    assert active_total == 2
    assert active == {draft["id"], live["id"]}

    serving, serving_total = listed(
        client.get("/entities", params=[("status", "serving"), ("status", "serving")])
    )
    assert serving_total == 1
    assert serving == {live["id"]}

    deprecated, deprecated_total = listed(
        client.get("/entities", params={"status": "deprecated"})
    )
    assert deprecated_total == 1
    assert deprecated == {retired["id"]}

    all_three, all_three_total = listed(
        client.get(
            "/entities",
            params=[
                ("status", "not_serving"),
                ("status", "serving"),
                ("status", "deprecated"),
            ],
        )
    )
    assert all_three_total == total
    assert all_three == everything

    named, named_total = listed(
        client.get("/entities", params=[("q", "Draft"), ("status", "not_serving")])
    )
    assert named_total == 1
    assert named == {draft["id"]}
    missed, missed_total = listed(
        client.get("/entities", params=[("q", "Draft"), ("status", "deprecated")])
    )
    assert missed_total == 0
    assert missed == set()

    invalid = client.get("/entities", params={"status": "published"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "REQUEST_INVALID"


def test_unauthenticated_entities_are_401() -> None:
    with TestClient(app) as test_client:
        assert test_client.get("/entities").status_code == 401
