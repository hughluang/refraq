"""Stable attribute_id: publish carry-over, backfill, and version read exposure."""

from __future__ import annotations

import importlib.util
import itertools
import os
from datetime import datetime, timezone
from pathlib import Path

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
from backend.entity.data.head import HeadTarget  # noqa: E402
from backend.entity.data.values import reference_value_attr  # noqa: E402
from backend.entity.errors import EntityNotServing  # noqa: E402
from backend.entity.publish import assign_attribute_ids  # noqa: E402
from backend.entity.records import (  # noqa: E402
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
    attribute_from_dict,
    attribute_to_dict,
    attribute_to_stored,
)
from backend.entity.store import get_entity_store  # noqa: E402
from backend.entity.table_port import (  # noqa: E402
    RecordingEntityTablePort,
    bind_entity_table_port,
)
from backend.main import app  # noqa: E402
from backend.tests.test_entity import SKU, _create_body  # noqa: E402

NOTE = {
    "name": "note",
    "type": "text",
    "required": False,
    "config": {},
}


@pytest.fixture()
def client() -> TestClient:
    bind_entity_table_port(RecordingEntityTablePort())
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


def _ids(client: TestClient, entity_id: str, version_id: str) -> dict[str, str | None]:
    detail = client.get(f"/entities/{entity_id}/versions/{version_id}")
    assert detail.status_code == 200, detail.text
    return {
        attr["name"]: attr["attribute_id"]
        for attr in detail.json()["version"]["attributes"]
    }


def _publish_current(client: TestClient, entity_id: str) -> str:
    entity = client.get(f"/entities/{entity_id}").json()["entity"]
    version_id = entity["current_version"]["id"]
    published = client.post(f"/entities/{entity_id}/versions/{version_id}/publish")
    assert published.status_code == 201, published.text
    assert published.json()["job"]["status"] == "succeeded"
    return version_id


def _open(client: TestClient, entity_id: str, attributes: list[dict]) -> str:
    opened = client.post(
        f"/entities/{entity_id}/versions", json={"attributes": attributes}
    )
    assert opened.status_code == 201, opened.text
    return opened.json()["version"]["id"]


def test_publish_assigns_and_carries_ids_by_name(client: TestClient) -> None:
    created = client.post("/entities", json=_create_body())
    assert created.status_code == 201, created.text
    entity_id = created.json()["entity"]["id"]
    v1 = created.json()["entity"]["current_version"]["id"]
    assert _ids(client, entity_id, v1) == {"sku": None}

    _publish_current(client, entity_id)
    v1_ids = _ids(client, entity_id, v1)
    assert v1_ids["sku"] is not None and v1_ids["sku"].startswith("att_")

    v2 = _open(client, entity_id, [SKU, NOTE])
    draft = _ids(client, entity_id, v2)
    assert draft == {"sku": v1_ids["sku"], "note": None}

    _publish_current(client, entity_id)
    v2_ids = _ids(client, entity_id, v2)
    assert v2_ids["sku"] == v1_ids["sku"]
    assert v2_ids["note"] is not None and v2_ids["note"] != v2_ids["sku"]
    assert _ids(client, entity_id, v1) == v1_ids

    renamed = {**NOTE, "name": "remark"}
    v3 = _open(client, entity_id, [SKU, renamed])
    assert _ids(client, entity_id, v3) == {"sku": v1_ids["sku"], "remark": None}
    _publish_current(client, entity_id)
    v3_ids = _ids(client, entity_id, v3)
    assert v3_ids["sku"] == v1_ids["sku"]
    assert v3_ids["remark"] not in (None, v2_ids["note"])

    stored = get_entity_store().get_version(v3)
    assert stored is not None
    assert {item["name"]: item["attribute_id"] for item in stored.materialized_attributes} == v3_ids
    assert {attr.name: attr.attribute_id for attr in stored.attributes} == v3_ids


def test_attribute_id_is_rejected_on_write(client: TestClient) -> None:
    body = _create_body(attributes=[{**SKU, "attribute_id": "att_forged"}])
    response = client.post("/entities", json=body)
    assert response.status_code == 422, response.text


def test_readded_name_after_a_gap_gets_a_new_id() -> None:
    previous = _version(
        "published", [AttributeRecord(name="sku", type="text", attribute_id="att_a")]
    )
    assigned = assign_attribute_ids(
        [
            AttributeRecord(name="sku", type="text", attribute_id="att_stale"),
            AttributeRecord(name="gone", type="text", attribute_id="att_old"),
        ],
        previous,
    )
    assert assigned[0].attribute_id == "att_a"
    assert assigned[1].attribute_id not in (None, "att_old", "att_a")


def test_attribute_id_does_not_change_shape_equality() -> None:
    plain = AttributeRecord(name="sku", type="text")
    stamped = AttributeRecord(name="sku", type="text", attribute_id="att_a")
    assert plain == stamped
    assert "attribute_id" not in attribute_to_dict(stamped)
    stored = attribute_to_stored(stamped)
    assert stored["attribute_id"] == "att_a"
    assert attribute_from_dict(stored).attribute_id == "att_a"
    assert "attribute_id" not in attribute_to_stored(plain)


def _load_backfill():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0050_entity_attribute_ids.py"
    )
    spec = importlib.util.spec_from_file_location("_mig_0050", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(version: int, status: str, names: list[str]) -> dict:
    attrs = [{"name": name, "type": "text", "config": {}} for name in names]
    return {
        "id": f"{version:016x}",
        "entity_id": "ent_a",
        "version": version,
        "publish_status": status,
        "attributes": attrs,
        "materialized_attributes": list(attrs) if status == "published" else [],
    }


def test_backfill_shares_ids_across_published_versions() -> None:
    module = _load_backfill()
    counter = itertools.count(1)
    rows = [
        _row(3, "unpublished", ["sku", "remark"]),
        _row(2, "published", ["sku", "remark"]),
        _row(1, "published", ["sku", "note"]),
    ]
    out = {
        row["version"]: row
        for row in module.assign_ids(rows, new_id=lambda: f"att_{next(counter)}")
    }
    v1 = {a["name"]: a["attribute_id"] for a in out[1]["attributes"]}
    v2 = {a["name"]: a["attribute_id"] for a in out[2]["attributes"]}
    assert v1 == {"sku": "att_1", "note": "att_2"}
    assert v2 == {"sku": "att_1", "remark": "att_3"}
    assert {
        a["name"]: a["attribute_id"] for a in out[2]["materialized_attributes"]
    } == v2
    assert all("attribute_id" not in a for a in out[3]["attributes"])


def test_backfill_keeps_ids_already_present() -> None:
    module = _load_backfill()
    row = _row(1, "published", ["sku"])
    row["attributes"][0] = {**row["attributes"][0], "attribute_id": "att_keep"}
    out = module.assign_ids([row], new_id=lambda: "att_new")
    assert out[0]["attributes"][0]["attribute_id"] == "att_keep"
    assert out[0]["materialized_attributes"][0]["attribute_id"] == "att_keep"


def _version(status: str, attributes: list[AttributeRecord]) -> EntityVersionRecord:
    now = datetime.now(timezone.utc)
    return EntityVersionRecord(
        id="0123456789abcdef",
        entity_id="ent_a",
        version=1,
        attributes=attributes,
        materialized_attributes=[],
        publish_status=status,
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )


def test_reference_without_snapshot_is_not_serving() -> None:
    ref = AttributeRecord(name="supplier", type="reference", target_entity_id="ent_b")
    now = datetime.now(timezone.utc)
    target = HeadTarget(
        entity=BusinessEntityRecord(
            id="ent_a",
            table_name="material",
            name="Material",
            description="x",
            deprecated_at=None,
            created_at=now,
            updated_at=now,
        ),
        head=_version("published", [ref]),
        attributes=(ref,),
        physical_table="material__v1__0123456789abcdef",
        qualified_table='"entity_data"."material__v1__0123456789abcdef"',
        writable=True,
    )
    with pytest.raises(EntityNotServing):
        reference_value_attr(ref, target)
