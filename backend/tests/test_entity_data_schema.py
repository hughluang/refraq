"""Entity Data API schema discovery (memory metadata; no entity connection)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.pop("ENTITY_DATABASE_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.entity.attribute_type import resolve  # noqa: E402
from backend.entity.data.capabilities import (  # noqa: E402
    FILTER_DEPTH_MAX,
    FILTER_IN_VALUES_MAX,
    FILTER_LEAVES_MAX,
    OFFSET_MAX,
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    ROW_WRITE_LIMIT,
    upsert_key_for,
)
from backend.entity.ids import new_entity_id, new_version_id  # noqa: E402
from backend.entity.lifecycle import PUBLISHED, PUBLISHING  # noqa: E402
from backend.entity.records import (  # noqa: E402
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import get_entity_store  # noqa: E402
from backend.main import app  # noqa: E402


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


def _seed_serving(
    *,
    table_name: str = "material",
    attributes: list[AttributeRecord] | None = None,
    publishing: bool = False,
    deprecated: bool = False,
) -> BusinessEntityRecord:
    now = datetime.now(timezone.utc)
    attrs = attributes or [
        AttributeRecord(
            name="sku",
            type="string",
            required=True,
            unique=True,
            max_length=32,
        ),
        AttributeRecord(
            name="active",
            type="boolean",
            required=False,
            unique=True,
        ),
        AttributeRecord(name="note", type="text"),
    ]
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name=table_name,
        name="Material",
        description="Stock material",
        deprecated_at=now if deprecated else None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=list(attrs),
        materialized_attributes=[attribute_to_dict(item) for item in attrs],
        publish_status=PUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    store = get_entity_store()
    store.create_entity(entity, version)
    if publishing:
        store.create_version(
            EntityVersionRecord(
                id=new_version_id(),
                entity_id=entity.id,
                version=2,
                attributes=list(attrs),
                materialized_attributes=[],
                publish_status=PUBLISHING,
                latest_reconcile_job_id=None,
                created_at=now,
                updated_at=now,
            )
        )
    return entity


def test_schema_returns_head_metadata_and_shared_limits(client: TestClient) -> None:
    _seed_serving()
    response = client.post("/entities/material/schema", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entity"]["table_name"] == "material"
    assert body["entity"]["writable"] is True
    assert "table_name" not in body["head"]
    assert body["row_id"]["type"] == "integer"
    assert body["row_id"]["operators"] == list(resolve("integer").operators)
    names = [item["name"] for item in body["attributes"]]
    assert names == ["sku", "active", "note"]
    by_name = {item["name"]: item for item in body["attributes"]}
    assert by_name["sku"]["operators"] == list(resolve("string").operators)
    assert by_name["sku"]["upsert_key"] is True
    assert by_name["active"]["upsert_key"] is True
    assert by_name["note"]["upsert_key"] is False
    assert body["limits"] == {
        "page_limit_default": PAGE_LIMIT_DEFAULT,
        "page_limit_max": PAGE_LIMIT_MAX,
        "offset_max": OFFSET_MAX,
        "filter_leaves_max": FILTER_LEAVES_MAX,
        "filter_depth_max": FILTER_DEPTH_MAX,
        "filter_in_values_max": FILTER_IN_VALUES_MAX,
        "row_write_max": ROW_WRITE_LIMIT,
    }


def test_schema_unknown_table_name_is_404(client: TestClient) -> None:
    response = client.post("/entities/missing_table/schema", json={})
    assert response.status_code == 404
    assert response.json()["code"] == "ENTITY_NOT_FOUND"


def test_unknown_table_beats_bad_body_structure(client: TestClient) -> None:
    """Contract §10: table_name / lifecycle before request structure.

    Authenticated callers with data permissions must still get
    ENTITY_NOT_FOUND for an unregistered table_name even when the body
    would otherwise be REQUEST_INVALID.
    """
    cases = [
        ("/entities/missing_table/schema", {"extra": 1}),
        ("/entities/missing_table/create", {"cursor": True}),
        ("/entities/missing_table/create-many", {"items": []}),
        ("/entities/missing_table/get", {"row_id": "bad", "extra": 1}),
        ("/entities/missing_table/update", {"filters": []}),
        ("/entities/missing_table/delete", {"row_id": 0}),
        ("/entities/missing_table/query", {"cursor": "x"}),
        ("/entities/missing_table/update-where", {"set": {}}),
        ("/entities/missing_table/delete-where", {"extra": True}),
        ("/entities/missing_table/upsert", {"key": "", "values": {}}),
    ]
    for path, body in cases:
        response = client.post(path, json=body)
        assert response.status_code == 404, (path, response.text)
        assert response.json()["code"] == "ENTITY_NOT_FOUND", path


def test_schema_id_path_does_not_resolve(client: TestClient) -> None:
    entity = _seed_serving()
    response = client.post(f"/entities/{entity.id}/schema", json={})
    assert response.status_code == 404
    assert response.json()["code"] == "ENTITY_NOT_FOUND"


def test_schema_non_post_is_405(client: TestClient) -> None:
    _seed_serving()
    assert client.get("/entities/material/schema").status_code == 405


def test_schema_deprecated_and_not_serving(client: TestClient) -> None:
    _seed_serving(table_name="gone", deprecated=True)
    deprecated = client.post("/entities/gone/schema", json={})
    assert deprecated.status_code == 422
    assert deprecated.json()["code"] == "ENTITY_DEPRECATED"

    now = datetime.now(timezone.utc)
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name="draft_only",
        name="Draft",
        description="No head",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=[],
        materialized_attributes=[],
        publish_status="unpublished",
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    missing = client.post("/entities/draft_only/schema", json={})
    assert missing.status_code == 422
    assert missing.json()["code"] == "ENTITY_NOT_SERVING"


def test_schema_publishing_sets_writable_false(client: TestClient) -> None:
    _seed_serving(publishing=True)
    response = client.post("/entities/material/schema", json={})
    assert response.status_code == 200
    assert response.json()["entity"]["writable"] is False


def test_action_verbs_503_in_memory_without_entity_url(client: TestClient) -> None:
    _seed_serving()
    created = client.post(
        "/entities/material/create",
        json={"values": {"sku": "A1", "active": True}},
    )
    assert created.status_code == 503
    assert created.json()["code"] == "PLATFORM_CAPACITY_EXCEEDED"
    assert created.headers.get("retry-after") == "1"


def test_data_permissions_not_implied_by_entity_read_write(
    client: TestClient,
) -> None:
    roles = get_role_store()
    writer = create_role(
        roles,
        key="def_writer",
        name="Definition writer",
        permissions=["console:access", "entity:read", "entity:write"],
    )
    get_user_store().create_user(
        account="defwriter",
        display_name="Def",
        password_hash=hash_password("secret"),
        role_id=writer.id,
        status="active",
    )
    _seed_serving()
    client.post("/auth/logout")
    assert (
        client.post(
            "/auth/login", json={"account": "defwriter", "password": "secret"}
        ).status_code
        == 200
    )
    denied = client.post("/entities/material/schema", json={})
    assert denied.status_code == 403
    assert denied.json()["code"] == "AUTH_FORBIDDEN"

    operator = roles.get_by_key("operator")
    assert operator is not None
    assert "entity:data_read" not in operator.permissions
    assert "entity:data_write" not in operator.permissions


def test_super_admin_has_data_permissions_via_catalog(client: TestClient) -> None:
    catalog = client.get("/permissions")
    assert catalog.status_code == 200
    keys = {item["key"] for item in catalog.json()["items"]}
    assert "entity:data_read" in keys
    assert "entity:data_write" in keys


def test_upsert_key_includes_boolean_excludes_number_json() -> None:
    assert upsert_key_for(
        AttributeRecord(name="flag", type="boolean", unique=True)
    )
    assert not upsert_key_for(
        AttributeRecord(name="n", type="number", unique=True)
    )
    assert not upsert_key_for(
        AttributeRecord(name="j", type="json", unique=True)
    )


def test_schema_dictionary_codes_writable_intersection(client: TestClient) -> None:
    from backend.entity.dictionaries.records import (
        DictionaryEntryRecord,
        DictionaryRecord,
    )
    from backend.entity.dictionaries.store import get_dictionary_store

    now = datetime.now(timezone.utc)
    dictionary = DictionaryRecord(
        id="dict_status",
        name="status_codes",
        display_name="Status",
        description=None,
        revision=1,
        deprecated_at=None,
        created_at=now,
        updated_at=now,
        entries=(
            DictionaryEntryRecord(code="open", label="Open", active=True, position=0),
            DictionaryEntryRecord(code="closed", label="Closed", active=False, position=1),
            DictionaryEntryRecord(code="hold", label="Hold", active=True, position=2),
        ),
    )
    get_dictionary_store().create(dictionary)
    attrs = [
        AttributeRecord(
            name="status",
            type="dictionary",
            required=True,
            dictionary_id=dictionary.id,
        )
    ]
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name="ticket",
        name="Ticket",
        description="Ticket",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=list(attrs),
        materialized_attributes=[attribute_to_dict(item) for item in attrs],
        publish_status=PUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
        dictionary_snapshots={
            "status": {
                "dictionary_id": dictionary.id,
                "revision": 1,
                "codes": ["open", "closed"],
            }
        },
    )
    get_entity_store().create_entity(entity, version)
    response = client.post("/entities/ticket/schema", json={})
    assert response.status_code == 200, response.text
    codes = {
        item["code"]: item["writable"]
        for item in response.json()["attributes"][0]["codes"]
    }
    assert codes == {"open": True, "closed": False}
    assert "hold" not in codes


def test_unauthenticated_schema_is_401() -> None:
    with TestClient(app) as anon:
        response = anon.post("/entities/material/schema", json={})
        assert response.status_code == 401
