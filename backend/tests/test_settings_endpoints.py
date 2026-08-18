"""Platform settings API tests for docs/api-contracts-settings.md."""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.security import hash_password  # noqa: E402
from backend.admin.system_parameters import (  # noqa: E402
    resolve_int,
    reset_system_parameters,
)
from backend.core.errors import CODE_HTTP_NOT_FOUND, CODE_REQUEST_INVALID  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402
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

REGISTERED_KEYS = {
    "admin_session_ttl_hours",
    "job_lost_detection_sec",
}

CATALOG_KEY_ORDER = [
    "admin_session_ttl_hours",
    "job_lost_detection_sec",
]


@pytest.fixture
def store_bundle():
    reset_user_store()
    reset_role_store()
    reset_session_store()
    reset_system_parameters()
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
    reset_system_parameters()


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


def _login_root(client: TestClient) -> None:
    assert (
        client.post("/auth/login", json={"account": "root", "password": "s3cret"}).status_code
        == 200
    )


def _by_key(body: dict, key: str) -> dict:
    return next(item for item in body["parameters"] if item["key"] == key)


def test_get_settings_requires_permission(client: TestClient) -> None:
    assert (
        client.post("/auth/login", json={"account": "op", "password": "op-pass"}).status_code
        == 200
    )
    response = client.get("/settings")
    assert response.status_code == 403


def test_get_settings_catalog_hides_secrets(client: TestClient) -> None:
    _login_root(client)
    response = client.get("/settings")
    assert response.status_code == 200
    body = response.json()
    keys = {item["key"] for item in body["parameters"]}
    assert keys == REGISTERED_KEYS
    ttl = _by_key(body, "admin_session_ttl_hours")
    assert ttl["source"] == "seed"
    assert ttl["value"] == 8
    assert ttl["operator_action_required"] is False
    assert ttl["constraint"] == {"type": "integer", "minimum": 1, "maximum": 168}
    assert "value_type" not in ttl
    assert "min" not in ttl
    assert "max" not in ttl
    assert [item["key"] for item in body["parameters"]] == CATALOG_KEY_ORDER
    for item in body["parameters"]:
        assert item["label_key"] == f"settings.parameter.{item['key']}.label"
        assert item["help_key"] == f"settings.parameter.{item['key']}.help"
        assert item["apply_note_key"] == f"settings.parameter.{item['key']}.apply"
    assert "admin_session_secret" not in body
    assert "initial_admin_password" not in str(body)


def test_patch_and_reset(client: TestClient) -> None:
    _login_root(client)
    patched = client.patch(
        "/settings", json={"values": {"admin_session_ttl_hours": 12}}
    )
    assert patched.status_code == 200
    ttl = _by_key(patched.json(), "admin_session_ttl_hours")
    assert ttl["value"] == 12
    assert ttl["source"] == "user"
    assert ttl["updated_by_account"] == "root"
    assert resolve_int("admin_session_ttl_hours").value == 12
    from backend.admin.audit_store import get_audit_store

    events, _cursor = get_audit_store().list_events(resource_type="system_parameter")
    assert {event.action for event in events} >= {"parameter.set"}

    reset = client.post("/settings/reset", json={"keys": ["admin_session_ttl_hours"]})
    assert reset.status_code == 200
    restored = _by_key(reset.json(), "admin_session_ttl_hours")
    assert restored["source"] == "seed"
    assert restored["value"] == restored["seed"]


def test_patch_seed_value_is_still_user(client: TestClient) -> None:
    _login_root(client)
    patched = client.patch(
        "/settings", json={"values": {"admin_session_ttl_hours": 8}}
    )
    assert patched.status_code == 200
    ttl = _by_key(patched.json(), "admin_session_ttl_hours")
    assert ttl["value"] == 8
    assert ttl["source"] == "user"


def test_patch_rejects_out_of_range_and_unknown(client: TestClient) -> None:
    _login_root(client)
    out_of_range = client.patch(
        "/settings", json={"values": {"admin_session_ttl_hours": 0}}
    )
    assert_problem(out_of_range, status=422, code="SYSTEM_PARAMETER_INVALID")
    unknown = client.patch("/settings", json={"values": {"not_a_key": 1}})
    assert_problem(unknown, status=422, code="SYSTEM_PARAMETER_INVALID")
    empty = client.patch("/settings", json={"values": {}})
    assert_problem(empty, status=422, code=CODE_REQUEST_INVALID)


def test_get_serves_raw_stored_value_outside_constraint(client: TestClient) -> None:
    from backend.admin.system_parameters import ParameterRecord, get_parameter_store
    from backend.core.time import utc_now

    _login_root(client)
    get_parameter_store().upsert(
        ParameterRecord(
            key="admin_session_ttl_hours",
            value=9999,
            previous_value=8,
            source="user",
            updated_at=utc_now(),
            updated_by_user_id=None,
        )
    )
    ttl = _by_key(client.get("/settings").json(), "admin_session_ttl_hours")
    assert ttl["value"] == 9999
    assert ttl["constraint"]["maximum"] == 168


def test_catalog_fails_loudly_when_parameter_reads_fail(client: TestClient) -> None:
    from backend.admin.system_parameters import get_parameter_store

    store = get_parameter_store()
    original_get = store.get

    def boom(key: str) -> object:
        raise RuntimeError("store down")

    store.get = boom  # type: ignore[method-assign]
    try:
        assert client.get("/healthz").status_code == 200
        _login_root(client)
        response = client.get("/settings")
        assert_problem(response, status=503, code="SYSTEM_PARAMETER_READ_FAILED")
    finally:
        store.get = original_get  # type: ignore[method-assign]


def test_patch_requires_write(client: TestClient) -> None:
    assert (
        client.post("/auth/login", json={"account": "op", "password": "op-pass"}).status_code
        == 200
    )
    response = client.patch(
        "/settings", json={"values": {"admin_session_ttl_hours": 10}}
    )
    assert response.status_code == 403


def test_ttl_write_affects_new_sessions_only(
    client: TestClient, store_bundle
) -> None:
    _, _, session_store = store_bundle
    _login_root(client)
    first_sid = client.cookies.get("refraq_sid")
    assert first_sid
    first_expiry = session_store._sessions[first_sid].expires_at  # noqa: SLF001

    assert (
        client.patch(
            "/settings", json={"values": {"admin_session_ttl_hours": 2}}
        ).status_code
        == 200
    )
    assert session_store._sessions[first_sid].expires_at == first_expiry  # noqa: SLF001

    client.post("/auth/logout")
    before = time.time()
    assert (
        client.post("/auth/login", json={"account": "root", "password": "s3cret"}).status_code
        == 200
    )
    second_sid = client.cookies.get("refraq_sid")
    assert second_sid and second_sid != first_sid
    second_expiry = session_store._sessions[second_sid].expires_at  # noqa: SLF001
    assert 7100 <= (second_expiry - before) <= 7300


def test_patch_rejects_partial_map_without_writing(client: TestClient) -> None:
    _login_root(client)
    from backend.admin.audit_store import get_audit_store

    events_before, _ = get_audit_store().list_events(resource_type="system_parameter")
    response = client.patch(
        "/settings",
        json={
            "values": {
                "admin_session_ttl_hours": 12,
                "job_lost_detection_sec": 5,
            }
        },
    )
    assert_problem(response, status=422, code="SYSTEM_PARAMETER_INVALID")
    catalog = client.get("/settings").json()
    assert _by_key(catalog, "admin_session_ttl_hours")["value"] == 8
    assert _by_key(catalog, "admin_session_ttl_hours")["source"] == "seed"
    assert _by_key(catalog, "job_lost_detection_sec")["value"] == 60
    events_after, _ = get_audit_store().list_events(resource_type="system_parameter")
    assert len(events_after) == len(events_before)


def test_patch_rejects_coerced_json_types(client: TestClient) -> None:
    _login_root(client)
    for payload in (
        {"values": {"admin_session_ttl_hours": "12"}},
        {"values": {"admin_session_ttl_hours": True}},
        {"values": {"admin_session_ttl_hours": 12.5}},
    ):
        response = client.patch("/settings", json=payload)
        assert_problem(response, status=422, code="SYSTEM_PARAMETER_INVALID")
    ttl = _by_key(client.get("/settings").json(), "admin_session_ttl_hours")
    assert ttl["value"] == 8
    assert ttl["source"] == "seed"


def test_reset_all_restores_every_key(client: TestClient) -> None:
    _login_root(client)
    assert (
        client.patch(
            "/settings",
            json={
                "values": {
                    "admin_session_ttl_hours": 12,
                    "job_lost_detection_sec": 90,
                }
            },
        ).status_code
        == 200
    )
    omitted = client.post("/settings/reset", json={})
    assert omitted.status_code == 200
    for item in omitted.json()["parameters"]:
        assert item["source"] == "seed"
        assert item["value"] == item["seed"]

    assert (
        client.patch(
            "/settings", json={"values": {"admin_session_ttl_hours": 12}}
        ).status_code
        == 200
    )
    empty_list = client.post("/settings/reset", json={"keys": []})
    assert empty_list.status_code == 200
    assert _by_key(empty_list.json(), "admin_session_ttl_hours")["source"] == "seed"


def test_reset_seed_key_still_records_change(client: TestClient) -> None:
    _login_root(client)
    from backend.admin.audit_store import get_audit_store

    events_before, _ = get_audit_store().list_events(
        resource_type="system_parameter", action="parameter.reset"
    )
    response = client.post(
        "/settings/reset", json={"keys": ["admin_session_ttl_hours"]}
    )
    assert response.status_code == 200
    after = _by_key(response.json(), "admin_session_ttl_hours")
    assert after["source"] == "seed"
    assert after["value"] == 8
    events_after, _ = get_audit_store().list_events(
        resource_type="system_parameter", action="parameter.reset"
    )
    assert len(events_after) == len(events_before) + 1


def test_delete_settings_override_is_gone(client: TestClient) -> None:
    _login_root(client)
    response = client.delete("/settings/override")
    assert_problem(response, status=404, code=CODE_HTTP_NOT_FOUND)


def test_permissions_catalog_includes_settings(client: TestClient) -> None:
    _login_root(client)
    response = client.get("/permissions")
    assert response.status_code == 200
    keys = {item["key"] for item in response.json()["items"]}
    assert "settings:read" in keys
    assert "settings:write" in keys
