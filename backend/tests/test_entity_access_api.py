"""Access management HTTP: permission, shape preview, and the preview access log."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.admin.role_store import RoleRecord, get_role_store
from backend.admin.roles import seed_roles
from backend.admin.security import hash_password
from backend.admin.user_store import get_user_store
from backend.entity.access.store import get_access_store
from backend.entity.ids import new_entity_id, new_version_id
from backend.entity.lifecycle import PUBLISHED
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_to_dict,
)
from backend.entity.store import get_entity_store
from backend.main import app


@pytest.fixture()
def client() -> TestClient:
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    operator = roles.get_by_key("operator")
    assert admin is not None and operator is not None
    roles.insert(
        RoleRecord(
            id="role_access",
            key="access_manager",
            name="Access manager",
            permissions=["console:access", "entity:access_manage"],
        )
    )
    users = get_user_store()
    users.create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )
    users.create_user(
        account="manager",
        display_name="Manager",
        password_hash=hash_password("secret"),
        role_id="role_access",
        status="active",
    )
    users.create_user(
        account="op",
        display_name="Op",
        password_hash=hash_password("secret"),
        role_id=operator.id,
        status="active",
    )
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, account: str) -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": "secret"}
    )
    assert response.status_code == 200, response.text


def _entity() -> str:
    now = datetime.now(timezone.utc)
    attr = AttributeRecord(
        name="name",
        type="string",
        max_length=32,
        attribute_id="att_name",
    )
    entity = BusinessEntityRecord(
        id=new_entity_id(),
        table_name="customer",
        name="Customer",
        description="Customers",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id=new_version_id(),
        entity_id=entity.id,
        version=1,
        attributes=[attr],
        materialized_attributes=[{**attribute_to_dict(attr), "attribute_id": attr.attribute_id}],
        publish_status=PUBLISHED,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    get_entity_store().create_entity(entity, version)
    return entity.id


@pytest.mark.parametrize("include_rows", [False, True])
def test_preview_dynamic_limit_precedes_empty_results(
    client: TestClient, include_rows: bool,
) -> None:
    from backend.admin.system_parameters import set_parameter

    _login(client, "admin")
    entity_id = _entity()
    subject = get_user_store().get_by_account("op")
    assert subject is not None
    body = {"subject": {"type": "user", "id": subject.id},
            "include_rows": include_rows, "limit": 201}
    url = f"/entities/{entity_id}/access/preview"
    refused = client.post(url, json=body)
    assert refused.status_code == 422
    assert refused.json()["code"] == "REQUEST_INVALID"
    assert refused.json()["detail"] == "limit must be <= 200"
    set_parameter("entity_page_limit_max", 1000, actor_user_id=None)
    for value in (201, 1000):
        body["limit"] = value
        accepted = client.post(url, json=body)
        assert accepted.status_code == 200, accepted.text
        if include_rows:
            assert accepted.json()["rows"] == {"items": [], "total": 0, "limit": value, "offset": 0}
    body["limit"] = 1001
    assert client.post(url, json=body).json()["detail"] == "limit must be <= 1000"
    assert client.get(f"/entities/{entity_id}/access/grants?limit=201").status_code == 422
    assert client.get(f"/entities/{entity_id}/access/grants").json()["limit"] == 50
    set_parameter("entity_page_limit_max", 50, actor_user_id=None)
    body["limit"] = 201
    assert client.post(url, json=body).json()["detail"] == "limit must be <= 50"


@pytest.mark.parametrize("include_rows", [False, True])
def test_preview_resolves_page_limit_once_for_validation_and_schema(
    client: TestClient, monkeypatch, include_rows: bool,
) -> None:
    from unittest.mock import Mock

    from backend.admin.system_parameters import resolve_int, set_parameter
    from backend.entity.access import service
    from backend.tests.entity_access_oracle import prepare_legacy_entity

    _login(client, "admin")
    entity_id = _entity()
    prepare_legacy_entity(entity_id)
    subject = get_user_store().get_by_account("admin")
    assert subject is not None
    set_parameter("entity_page_limit_max", 1000, actor_user_id=None)
    resolver = Mock(wraps=resolve_int)
    schema_builder = Mock(wraps=service.build_schema)
    read_rows = Mock(return_value=([{"row_id": 1}], 1))
    monkeypatch.setattr(service, "resolve_int", resolver)
    monkeypatch.setattr(service, "build_schema", schema_builder)
    monkeypatch.setattr(service, "_ensure_generated", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_read_rows", read_rows)

    response = client.post(
        f"/entities/{entity_id}/access/preview",
        json={"subject": {"type": "user", "id": subject.id},
              "include_rows": include_rows, "limit": 1000},
    )

    assert response.status_code == 200, response.text
    resolver.assert_called_once_with("entity_page_limit_max")
    schema_builder.assert_called_once()
    assert schema_builder.call_args.kwargs["page_limit_max"] == 1000
    if include_rows:
        assert response.json()["rows"]["limit"] == 1000
        assert read_rows.call_args.args[-2] == 1000
    else:
        assert response.json()["rows"] is None
        read_rows.assert_not_called()


def test_access_manage_is_required_before_entity_lookup(client: TestClient) -> None:
    _login(client, "op")
    denied = client.get("/entities/ent_missing/access")
    assert denied.status_code == 403
    assert denied.json()["code"] == "AUTH_FORBIDDEN"


def test_profile_grant_preview_shape_and_row_log(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.entity.access.jobs.dispatch_entity_job", lambda job: job.id
    )
    entity_id = _entity()
    subject = get_user_store().get_by_account("manager")
    assert subject is not None
    _login(client, "manager")
    ladder = client.put(
        f"/entities/{entity_id}/access/ladders/att_name",
        json={"levels": [{"key": "clear", "mode": "clear"}]},
    )
    assert ladder.status_code == 200, ladder.text
    assert ladder.json()["policy_revision"] == 1
    created = client.post(
        f"/entities/{entity_id}/access/profiles",
        json={
            "key": "sales",
            "name": "Sales",
            "columns": [{"attribute_id": "att_name", "level": "clear"}],
        },
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["profile"]["id"]
    grant = client.post(
        f"/entities/{entity_id}/access/grants",
        json={
            "subject": {"type": "user", "id": subject.id},
            "profile_id": profile_id,
            "actions": ["read"],
        },
    )
    assert grant.status_code == 201, grant.text
    assert grant.json()["grant"]["warnings"] == []
    preview = client.post(
        f"/entities/{entity_id}/access/preview",
        json={"subject": {"type": "user", "id": subject.id}, "include_rows": False},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["rows"] is None
    assert body["schema"]["attributes"][0]["name"] == "name"
    assert body["schema"]["withheld_field"] is None
    refused = client.post(
        f"/entities/{entity_id}/access/preview",
        json={"subject": {"type": "user", "id": subject.id}, "include_rows": True},
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "AUTH_FORBIDDEN"
    assert get_access_store().logs_for_entity(entity_id) == []

    _login(client, "admin")
    pending = client.post(
        f"/entities/{entity_id}/access/preview",
        json={"subject": {"type": "user", "id": subject.id}, "include_rows": True},
    )
    assert pending.status_code == 503, pending.text
    assert pending.json()["code"] == "ENTITY_ACCESS_PENDING"
    assert pending.headers["retry-after"] == "1"
    from backend.entity.tasks import run_job
    from backend.jobs.store import get_job_store

    queued, _total = get_job_store().list(kind="entity_access_views")
    assert queued
    assert run_job(queued[0].id)["status"] == "succeeded"
    monkeypatch.setattr(
        "backend.entity.access.service._read_rows",
        lambda *args, **kwargs: ([{"row_id": 1, "name": "Ada", "__sources": {}}], 1),
    )
    viewed = client.post(
        f"/entities/{entity_id}/access/preview",
        json={"subject": {"type": "user", "id": subject.id}, "include_rows": True},
    )
    assert viewed.status_code == 200, viewed.text
    assert viewed.json()["rows"]["total"] == 1
    logs = get_access_store().logs_for_entity(entity_id)
    assert [item.outcome_code for item in logs] == ["ENTITY_ACCESS_PENDING", "ok"]
    assert logs[-1].user_id != subject.id
    assert logs[-1].preview_subject_user_id == subject.id
    assert logs[-1].verb == "preview"
