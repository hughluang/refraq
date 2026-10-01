"""Shared Dictionary: lifecycle, publish snapshot, and classifier."""

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
from backend.entity.store import get_entity_store  # noqa: E402
from backend.entity.table_port import RecordingEntityTablePort, get_entity_table_port  # noqa: E402
from backend.main import app  # noqa: E402


def _entry(code: str, label: str | None = None, active: bool = True) -> dict:
    body: dict = {"code": code, "active": active}
    if label is not None:
        body["label"] = label
    return body


def _create_list(client: TestClient, **overrides: object) -> dict:
    body: dict = {
        "name": "order_status",
        "display_name": "Order status",
        "entries": [_entry("open", "Open"), _entry("closed", "Closed")],
    }
    body.update(overrides)
    created = client.post("/dictionaries", json=body)
    assert created.status_code == 201, created.text
    return created.json()["dictionary"]


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


def test_create_rejects_bad_shape_and_duplicate_name(client: TestClient) -> None:
    created = _create_list(client)
    assert created["revision"] == 1
    assert created["entries"][0]["code"] == "open"
    assert created["entries"][0]["label"] == "Open"
    again = client.post(
        "/dictionaries",
        json={
            "name": "order_status",
            "display_name": "Again",
            "entries": [_entry("open")],
        },
    )
    assert again.status_code == 409
    assert again.json()["code"] == "DICTIONARY_NAME_DUP"
    empty = client.post(
        "/dictionaries",
        json={"name": "empty_list", "display_name": "Empty", "entries": []},
    )
    assert empty.status_code == 422
    assert empty.json()["code"] == "DICTIONARY_INVALID"
    renamed = client.patch(
        f"/dictionaries/{created['id']}", json={"name": "other_name"}
    )
    assert renamed.status_code == 422
    assert renamed.json()["code"] == "REQUEST_INVALID"
    long_code = client.post(
        "/dictionaries",
        json={
            "name": "long_code",
            "display_name": "Long",
            "entries": [_entry("o" * 65)],
        },
    )
    assert long_code.status_code == 422
    assert long_code.json()["code"] == "DICTIONARY_INVALID"
    unlabeled = client.post(
        "/dictionaries",
        json={
            "name": "bare_codes",
            "display_name": "Bare",
            "entries": [_entry("open")],
        },
    )
    assert unlabeled.status_code == 201, unlabeled.text
    entry = unlabeled.json()["dictionary"]["entries"][0]
    assert entry["code"] == "open"
    assert "label" not in entry


def test_label_change_keeps_revision_and_active_set_bumps_it(
    client: TestClient,
) -> None:
    created = _create_list(client)
    relabeled = client.patch(
        f"/dictionaries/{created['id']}",
        json={"entries": [_entry("open", "Opened"), _entry("closed", "Closed")]},
    )
    assert relabeled.status_code == 200, relabeled.text
    assert relabeled.json()["dictionary"]["revision"] == 1
    added = client.patch(
        f"/dictionaries/{created['id']}",
        json={
            "entries": [
                _entry("open", "Opened"),
                _entry("closed", "Closed"),
                _entry("held", "Held"),
            ]
        },
    )
    assert added.status_code == 200, added.text
    assert added.json()["dictionary"]["revision"] == 2


def test_attribute_references_code_list_and_publish_snapshots(
    client: TestClient,
) -> None:
    code_list = _create_list(client)
    created = client.post(
        "/entities",
        json={
            "table_name": "orders",
            "name": "Orders",
            "description": "Customer orders.",
            "attributes": [
                {
                    "name": "status",
                    "type": "dictionary",
                    "required": True,
                    "config": {"dictionary_id": code_list["id"]},
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    read = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert read.status_code == 200, read.text
    attribute = read.json()["version"]["attributes"][0]
    assert attribute["config"] == {"dictionary_id": code_list["id"]}
    assert attribute["dictionary"]["name"] == "order_status"
    assert attribute["behind"] is False
    assert "entries" not in attribute
    inline = client.patch(
        f"/entities/{entity['id']}/versions/{version_id}",
        json={
            "attributes": [
                {
                    "name": "status",
                    "type": "dictionary",
                    "config": {"entries": [{"code": "open"}]},
                }
            ]
        },
    )
    assert inline.status_code == 422
    assert inline.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    published = client.post(f"/entities/{entity['id']}/versions/{version_id}/publish")
    assert published.status_code == 201, published.text
    assert published.json()["job"]["status"] == "succeeded"
    port = get_entity_table_port()
    assert isinstance(port, RecordingEntityTablePort)
    check = next(sql for sql in port.statements if "CHECK" in sql)
    assert "'open'" in check and "'closed'" in check
    stored = get_entity_store().get_version(version_id)
    assert stored is not None
    snapshot = stored.dictionary_snapshots["status"]
    assert snapshot["revision"] == 1
    assert snapshot["codes"] == ["open", "closed"]


def test_snapshot_blocks_code_removal_and_list_delete(client: TestClient) -> None:
    code_list = _create_list(client)
    created = client.post(
        "/entities",
        json={
            "table_name": "orders",
            "name": "Orders",
            "description": "Customer orders.",
            "attributes": [
                {
                    "name": "status",
                    "type": "dictionary",
                    "config": {"dictionary_id": code_list["id"]},
                }
            ],
        },
    )
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    assert (
        client.post(f"/entities/{entity['id']}/versions/{version_id}/publish").status_code
        == 201
    )
    removed = client.patch(
        f"/dictionaries/{code_list['id']}",
        json={"entries": [_entry("open", "Open")]},
    )
    assert removed.status_code == 422
    assert removed.json()["code"] == "DICTIONARY_INVALID"
    deactivated = client.patch(
        f"/dictionaries/{code_list['id']}",
        json={"entries": [_entry("open", "Open"), _entry("closed", "Closed", False)]},
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["dictionary"]["revision"] == 2
    detail = client.get(f"/dictionaries/{code_list['id']}")
    usage = detail.json()["dictionary"]["usages"][0]
    assert usage["table_name"] == "orders"
    assert usage["attribute_name"] == "status"
    assert usage["behind"] is True
    version = client.get(f"/entities/{entity['id']}/versions/{version_id}")
    assert version.json()["version"]["attributes"][0]["behind"] is True
    blocked = client.delete(f"/dictionaries/{code_list['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "DICTIONARY_IN_USE"
    assert "orders.status" in blocked.json()["detail"]
    classified = client.post(
        f"/entities/{entity['id']}/classify",
        json={
            "attributes": [
                {
                    "name": "status",
                    "type": "dictionary",
                    "config": {"dictionary_id": code_list["id"]},
                }
            ]
        },
    )
    assert classified.status_code == 200, classified.text
    body = classified.json()
    assert body["class"] == "breaking"
    assert body["changes"][0]["new_value"]["removed"] == ["closed"]


def test_classify_rejects_an_unknown_code_list(client: TestClient) -> None:
    code_list = _create_list(client)
    created = client.post(
        "/entities",
        json={
            "table_name": "orders",
            "name": "Orders",
            "description": "Customer orders.",
            "attributes": [
                {
                    "name": "status",
                    "type": "dictionary",
                    "config": {"dictionary_id": code_list["id"]},
                }
            ],
        },
    )
    entity = created.json()["entity"]
    classified = client.post(
        f"/entities/{entity['id']}/classify",
        json={
            "attributes": [
                {
                    "name": "status",
                    "type": "dictionary",
                    "config": {"dictionary_id": "cl_missing"},
                }
            ]
        },
    )
    assert classified.status_code == 422
    assert classified.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"
    assert "removed" not in classified.text


def test_classify_reports_removed_when_no_codes_are_active(
    client: TestClient,
) -> None:
    code_list = _create_list(client)
    created = client.post(
        "/entities",
        json={
            "table_name": "orders",
            "name": "Orders",
            "description": "Customer orders.",
            "attributes": [
                {
                    "name": "status",
                    "type": "dictionary",
                    "config": {"dictionary_id": code_list["id"]},
                }
            ],
        },
    )
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    published = client.post(
        f"/entities/{entity['id']}/versions/{version_id}/publish"
    )
    assert published.status_code == 201, published.text
    deactivated = client.patch(
        f"/dictionaries/{code_list['id']}",
        json={
            "entries": [
                _entry("open", "Open", False),
                _entry("closed", "Closed", False),
            ]
        },
    )
    assert deactivated.status_code == 200, deactivated.text
    classified = client.post(
        f"/entities/{entity['id']}/classify",
        json={
            "attributes": [
                {
                    "name": "status",
                    "type": "dictionary",
                    "config": {"dictionary_id": code_list["id"]},
                }
            ]
        },
    )
    assert classified.status_code == 200, classified.text
    body = classified.json()
    assert body["class"] == "breaking"
    assert body["changes"][0]["new_value"]["removed"] == ["closed", "open"]


def test_new_attribute_cannot_select_a_deprecated_code_list(client: TestClient) -> None:
    code_list = _create_list(client)
    deprecated = client.patch(
        f"/dictionaries/{code_list['id']}", json={"deprecated": True}
    )
    assert deprecated.status_code == 200, deprecated.text
    assert deprecated.json()["dictionary"]["deprecated_at"] is not None
    rejected = client.post(
        "/entities",
        json={
            "table_name": "orders",
            "name": "Orders",
            "description": "Customer orders.",
            "attributes": [
                {
                    "name": "status",
                    "type": "dictionary",
                    "config": {"dictionary_id": code_list["id"]},
                }
            ],
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "DICTIONARY_DEPRECATED"


def test_publish_refuses_a_code_list_with_no_active_codes(client: TestClient) -> None:
    code_list = _create_list(client)
    created = client.post(
        "/entities",
        json={
            "table_name": "orders",
            "name": "Orders",
            "description": "Customer orders.",
            "attributes": [
                {
                    "name": "status",
                    "type": "dictionary",
                    "config": {"dictionary_id": code_list["id"]},
                }
            ],
        },
    )
    entity = created.json()["entity"]
    version_id = entity["current_version"]["id"]
    client.patch(
        f"/dictionaries/{code_list['id']}",
        json={
            "entries": [
                _entry("open", "Open", False),
                _entry("closed", "Closed", False),
            ]
        },
    )
    published = client.post(f"/entities/{entity['id']}/versions/{version_id}/publish")
    assert published.status_code == 422
    assert published.json()["code"] == "ENTITY_ATTRIBUTE_INVALID"


def test_unreferenced_code_can_be_removed_and_list_deleted(client: TestClient) -> None:
    code_list = _create_list(client)
    removed = client.patch(
        f"/dictionaries/{code_list['id']}",
        json={"entries": [_entry("open", "Open")]},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["dictionary"]["revision"] == 2
    deleted = client.delete(f"/dictionaries/{code_list['id']}")
    assert deleted.status_code == 204
    missing = client.get(f"/dictionaries/{code_list['id']}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "DICTIONARY_NOT_FOUND"
    again = client.delete(f"/dictionaries/{code_list['id']}")
    assert again.status_code == 404
    assert again.json()["code"] == "DICTIONARY_NOT_FOUND"


def test_execution_reports_empty_codes_when_every_code_is_inactive() -> None:
    from datetime import datetime, timezone

    from backend.entity.dictionaries.records import (
        DictionaryEntryRecord,
        DictionaryRecord,
    )
    from backend.entity.dictionaries.store import get_dictionary_store
    from backend.entity.dictionary_binding import bind_publish
    from backend.entity.errors import EntityAttributeInvalid
    from backend.entity.records import AttributeRecord

    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    get_dictionary_store().create(
        DictionaryRecord(
            id="cl_status",
            name="order_status",
            display_name="Order status",
            description=None,
            revision=2,
            deprecated_at=None,
            entries=(
                DictionaryEntryRecord(
                    code="open", label="Open", active=False, position=0
                ),
            ),
            created_at=now,
            updated_at=now,
        )
    )
    with pytest.raises(EntityAttributeInvalid) as exc:
        bind_publish(
            [
                AttributeRecord(
                    name="status", type="dictionary", dictionary_id="cl_status"
                )
            ],
            {
                "status": {
                    "dictionary_id": "cl_status",
                    "codes": ["open"],
                    "deprecated": False,
                }
            },
        )
    assert "now=[]" in exc.value.message


def test_execution_missing_dictionary_is_not_an_empty_code_set() -> None:
    from backend.entity.dictionary_binding import bind_publish
    from backend.entity.errors import EntityAttributeInvalid
    from backend.entity.records import AttributeRecord

    with pytest.raises(EntityAttributeInvalid) as exc:
        bind_publish(
            [
                AttributeRecord(
                    name="status", type="dictionary", dictionary_id="missing"
                )
            ],
            {
                "status": {
                    "dictionary_id": "missing",
                    "codes": ["open"],
                    "deprecated": False,
                }
            },
        )
    assert "does not name a dictionary" in exc.value.message
    assert "now=" not in exc.value.message


def test_delete_does_not_audit_when_the_row_is_already_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone

    from backend.admin.audit_store import get_audit_store
    from backend.entity.dictionaries.records import DictionaryRecord
    from backend.entity.dictionaries.service import delete_dictionary
    from backend.entity.errors import DictionaryNotFound

    now = datetime(2026, 9, 30, tzinfo=timezone.utc)
    record = DictionaryRecord(
        id="cl_gone",
        name="order_status",
        display_name="Order status",
        description=None,
        revision=1,
        deprecated_at=None,
        entries=(),
        created_at=now,
        updated_at=now,
    )

    class StandIn:
        def get(self, dictionary_id: str) -> DictionaryRecord | None:
            return record if dictionary_id == record.id else None

        def delete(self, dictionary_id: str) -> bool:
            return False

    monkeypatch.setattr(
        "backend.entity.dictionaries.service.get_dictionary_store",
        lambda: StandIn(),
    )
    with pytest.raises(DictionaryNotFound):
        delete_dictionary(record.id, actor_user_id="user", actor_token_id=None)
    events, _cursor = get_audit_store().list_events(action="dictionary.delete")
    assert events == []


def test_list_dictionaries_filters_by_status(client: TestClient) -> None:
    live = _create_list(client, name="live_codes", display_name="Live codes")
    retired = _create_list(client, name="retired_codes", display_name="Retired codes")
    assert (
        client.patch(
            f"/dictionaries/{retired['id']}", json={"deprecated": True}
        ).status_code
        == 200
    )

    def listed(response):
        assert response.status_code == 200, response.text
        body = response.json()
        return {item["id"] for item in body["items"]}, body["total"]

    everything, total = listed(client.get("/dictionaries"))
    assert total == 2
    assert everything == {live["id"], retired["id"]}

    available, available_total = listed(
        client.get("/dictionaries", params=[("status", "available")])
    )
    assert available_total == 1
    assert available == {live["id"]}

    repeated, repeated_total = listed(
        client.get(
            "/dictionaries",
            params=[("status", "available"), ("status", "available")],
        )
    )
    assert repeated_total == 1
    assert repeated == {live["id"]}

    deprecated, deprecated_total = listed(
        client.get("/dictionaries", params={"status": "deprecated"})
    )
    assert deprecated_total == 1
    assert deprecated == {retired["id"]}

    both, both_total = listed(
        client.get(
            "/dictionaries",
            params=[("status", "available"), ("status", "deprecated")],
        )
    )
    assert both_total == total
    assert both == everything

    named, named_total = listed(
        client.get("/dictionaries", params=[("q", "Live"), ("status", "available")])
    )
    assert named_total == 1
    assert named == {live["id"]}
    missed, missed_total = listed(
        client.get("/dictionaries", params=[("q", "Live"), ("status", "deprecated")])
    )
    assert missed_total == 0
    assert missed == set()

    invalid = client.get("/dictionaries", params={"status": "serving"})
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "REQUEST_INVALID"
