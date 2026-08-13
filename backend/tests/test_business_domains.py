"""Business Domain HTTP tests (ADR 0017)."""

from __future__ import annotations

from backend.core.time import utc_now
import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.main import app  # noqa: E402
from backend.metadata.business_domains.store import (  # noqa: E402
    reset_business_domain_store,
)
from backend.metadata.catalog.store import (  # noqa: E402
    CatalogColumnRecord,
    CatalogObjectRecord,
    get_catalog_store,
    reset_catalog_store,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot  # noqa: E402
from backend.metadata.sources.store import reset_source_store  # noqa: E402
from backend.jobs.store import reset_job_store  # noqa: E402
from backend.admin.audit_store import reset_audit_store  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_source_store()
    reset_catalog_store()
    reset_business_domain_store()
    reset_job_store()
    reset_audit_store()
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


def _access() -> dict:
    return {
        "host": "127.0.0.1",
        "port": 5432,
        "username": "u",
        "password": "p",
        "ssl_mode": "require",
        "database": "MES",
        "schema": "public",
        "extra": {},
    }


def _make_source(client: TestClient) -> dict:
    resp = client.post(
        "/sources",
        json={
            "key": "mes-prod",
            "name": "MES",
            "kind": "database",
            "engine": "postgresql",
            "access": _access(),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["source"]


def _seed_object(source_id: str) -> CatalogObjectRecord:
    now = utc_now()
    record = CatalogObjectRecord(
        id="obj_wo",
        source_id=source_id,
        locator_key="obj/postgresql/mes-prod/dbo/table/WORK_ORDER",
        object_type="table",
        schema_name="dbo",
        name="WORK_ORDER",
        ddl=None,
        comment=None,
        primary_key=["WO_ID"],
        is_present=True,
        business_name="Work Order",
        business_description="Header",
        object_category=None,
        grain_description=None,
        business_primary_key=None,
        business_domain_id=None,
        evidence_summary=None,
        open_questions=None,
        semantic_source=None,
        business_semantics_ready=False,
        semantics_updated_at=None,
        last_structure_job_id="job_1",
        collected_at=now,
        created_at=now,
        updated_at=now,
        columns=[
            CatalogColumnRecord(
                id="col_a",
                object_id="obj_wo",
                locator_key="col/postgresql/mes-prod/dbo/table/WORK_ORDER/column/WO_ID",
                name="WO_ID",
                ordinal=0,
                data_type="NUMBER",
                nullable=False,
                is_present=True,
                default_value=None,
                comment=None,
                business_name=None,
                business_description=None,
                column_semantics=None,
                enum_catalog=None,
                semantic_source=None,
                field_kind="column",
                created_at=now,
                updated_at=now,
            )
        ],
    )
    store = get_catalog_store()
    apply_structure_snapshot(
        source_id=source_id,
        job_id="seed",
        collected=[record],
        schema_scope=None,
        fail_safe_threshold=1.0,
        engine="postgresql",
        kind="database",
        source_key="mes-prod",
    )
    stored = store.get_object(record.id)
    assert stored is not None
    return stored


def test_business_domain_crud_and_code_immutable(client: TestClient) -> None:
    created = client.post(
        "/business-domains",
        json={"code": "orders", "name": "Orders", "description": "Order domain"},
    )
    assert created.status_code == 201, created.text
    domain = created.json()["domain"]
    assert domain["code"] == "orders"
    assert domain["name"] == "Orders"

    listed = client.get("/business-domains")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    patched = client.patch(
        f"/business-domains/{domain['id']}",
        json={"name": "Sales Orders"},
    )
    assert patched.status_code == 200
    assert patched.json()["domain"]["name"] == "Sales Orders"
    assert patched.json()["domain"]["code"] == "orders"

    conflict = client.post(
        "/business-domains",
        json={"code": "orders", "name": "Dup"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "BUSINESS_DOMAIN_CODE_CONFLICT"

    deleted = client.delete(f"/business-domains/{domain['id']}")
    assert deleted.status_code == 204


def test_business_domain_restrict_and_object_attach(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    created = client.post(
        "/business-domains",
        json={"code": "mes", "name": "MES"},
    )
    assert created.status_code == 201
    domain = created.json()["domain"]

    attached = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"business_domain_code": "mes"},
    )
    assert attached.status_code == 200, attached.text
    body = attached.json()["object"]
    assert body["business_domain"] == {
        "id": domain["id"],
        "code": "mes",
        "name": "MES",
    }

    blocked = client.delete(f"/business-domains/{domain['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "BUSINESS_DOMAIN_IN_USE"

    # Detach by replacing with another domain, then delete original.
    other = client.post(
        "/business-domains",
        json={"code": "wip", "name": "WIP"},
    )
    assert other.status_code == 201
    other_id = other.json()["domain"]["id"]
    client.patch(
        f"/objects/{obj.id}/semantics",
        json={"business_domain_code": "wip"},
    )
    freed = client.delete(f"/business-domains/{domain['id']}")
    assert freed.status_code == 204

    still_in_use = client.delete(f"/business-domains/{other_id}")
    assert still_in_use.status_code == 409


def test_semantic_column_unknown(client: TestClient) -> None:
    source = _make_source(client)
    obj = _seed_object(source["id"])
    resp = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"business_primary_key": ["WO_ID", "MISSING"]},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SEMANTIC_COLUMN_UNKNOWN"

    ok = client.patch(
        f"/objects/{obj.id}/semantics",
        json={"business_primary_key": ["WO_ID"]},
    )
    assert ok.status_code == 200
    assert ok.json()["object"]["business_primary_key"] == ["WO_ID"]
