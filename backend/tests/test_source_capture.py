"""Source capture configuration through the authorized HTTP seam."""

from __future__ import annotations

from datetime import datetime
import json

import pytest

from pydantic import ValidationError

from backend.metadata.capture.configuration import CaptureCredential
from backend.metadata.sources.service import update_source
from backend.tests.test_sources_jobs import client, _access
from backend.metadata.capture.configuration import (
    SnapshotWindow,
    snapshot_dispatch_allowed,
)
from backend.metadata.sources.store import get_source_store
from backend.core.secrets import decrypt_secret
from backend.worker.schedules import get_schedule_store


def test_capture_write_only_retain_replace_clear(client):
    credential = {"username": " capture-user ", "password": "capture-only-password"}
    response = client.post(
        "/sources",
        json={
            "key": "capture",
            "name": "Capture",
            "engine": "postgresql",
            "access": _access(),
            "capture_credential": credential,
        },
    )
    assert response.status_code == 201, response.text
    source = response.json()["source"]
    assert source["capture_credential_set"] is True
    assert source["capture_state"] == "configured"
    assert source["snapshot_window"] is None
    assert source["schedule_timezone"] == "UTC"
    source_id = source["id"]
    record = get_source_store().get_source(source_id)
    assert record.capture_revision == 1
    assert (
        json.loads(decrypt_secret(record.capture_credential_ciphertext)) == credential
    )
    timestamp = source["capture_credential_updated_at"]
    for response in (
        response,
        client.get("/sources"),
        client.get(f"/sources/{source_id}"),
        client.get(f"/sources/{source_id}/access"),
    ):
        assert credential["username"] not in response.text
        assert credential["password"] not in response.text
        assert record.capture_credential_ciphertext not in response.text
    assert record.capture_credential_ciphertext not in repr(record)
    assert record.access_ciphertext not in repr(record)
    retained = client.patch(f"/sources/{source_id}", json={"name": "Retained"})
    assert retained.json()["source"]["capture_credential_updated_at"] == timestamp
    assert get_source_store().get_source(source_id).capture_revision == 1
    replaced = client.patch(
        f"/sources/{source_id}", json={"capture_credential": credential}
    )
    assert replaced.status_code == 200
    assert get_source_store().get_source(source_id).capture_revision == 2
    cleared = client.patch(f"/sources/{source_id}", json={"capture_credential": None})
    assert cleared.status_code == 200
    assert cleared.json()["source"]["capture_state"] == "disabled"
    assert cleared.json()["source"]["capture_credential_set"] is False
    cleared_at = cleared.json()["source"]["capture_credential_updated_at"]
    assert cleared_at is not None
    assert get_source_store().get_source(source_id).capture_revision == 3


def test_typed_capture_inputs_are_revalidated_before_update(client):
    source = client.post(
        "/sources",
        json={
            "key": "typed",
            "name": "Typed",
            "engine": "postgresql",
            "access": _access(),
        },
    ).json()["source"]
    source_id = source["id"]
    credential = CaptureCredential(username="user", password="valid")
    update_source(source_id, capture_credential=credential)
    invalid_credential = credential.model_copy(update={"password": ""})
    invalid_window = SnapshotWindow(start="01:00", end="02:00").model_copy(
        update={"end": "01:00"}
    )
    for changes in (
        {"capture_credential": invalid_credential},
        {"snapshot_window": invalid_window},
    ):
        with pytest.raises(ValidationError):
            update_source(source_id, **changes)
    assert get_source_store().get_source(source_id).capture_revision == 1
    assert get_source_store().get_source(source_id).snapshot_window is None


def test_capture_invalid_shape_does_not_leak_keys(client):
    secret = "private-invalid-member-name"
    response = client.post(
        "/sources",
        json={
            "key": "invalid",
            "name": "Invalid",
            "engine": "postgresql",
            "access": _access(),
            "capture_credential": {
                "username": "user",
                "password": "secret",
                secret: "hidden",
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"
    assert secret not in response.text


def test_capture_scope_guard_and_ordinary_rotation(client):
    source = client.post(
        "/sources",
        json={
            "key": "scope",
            "name": "Scope",
            "engine": "postgresql",
            "access": _access(),
            "capture_credential": {
                "username": "capture",
                "password": "capture-password",
            },
        },
    ).json()["source"]
    path = f"/sources/{source['id']}"
    assert client.patch(path, json={"access": _access()}).status_code == 200
    assert (
        client.patch(
            path, json={"access": _access(username="rotated", password="rotated")}
        ).status_code
        == 200
    )
    for changes in (
        {"access": _access(host="new-host")},
        {"access": _access(database="other")},
        {"access": _access(extra={"setting": "new"})},
        {"engine": "mssql", "access": _access(ssl_mode="disable")},
        {"access": _access(host="new-host"), "capture_credential": None},
    ):
        response = client.patch(path, json=changes)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "SOURCE_CAPTURE_SCOPE_LOCKED"
    assert client.patch(path, json={"capture_credential": None}).status_code == 200
    assert (
        client.patch(path, json={"access": _access(host="new-host")}).status_code == 200
    )


@pytest.mark.parametrize(
    "credential",
    [
        "capture-secret",
        [],
        4,
        True,
        {},
        {"username": "u", "password": ""},
        {"username": 1, "password": "capture-secret"},
        {"username": "u", "password": ["capture-secret"]},
    ],
)
def test_capture_invalid_credentials_are_safe(client, credential):
    response = client.post(
        "/sources",
        json={
            "key": "invalid",
            "name": "Invalid",
            "engine": "postgresql",
            "access": _access(),
            "capture_credential": credential,
        },
    )
    assert response.status_code == 422
    assert "capture-secret" not in response.text


@pytest.mark.parametrize(
    "window",
    [
        {"start": "01:00", "end": "01:00"},
        {"start": "1:00", "end": "02:00"},
        {"start": "24:00", "end": "02:00"},
        {"start": "00:60", "end": "02:00"},
        {"start": "00:00\n", "end": "02:00"},
        {"start": "00:00", "end": "02:00", "extra": "value"},
        [],
        "00:00",
        {},
    ],
)
def test_window_invalid(client, window):
    response = client.post(
        "/sources",
        json={
            "key": "invalid",
            "name": "Invalid",
            "engine": "postgresql",
            "access": _access(),
            "snapshot_window": window,
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "REQUEST_INVALID"


@pytest.mark.parametrize(
    "wall,allowed",
    [
        ("2026-11-15T22:59:59+00:00", False),
        ("2026-11-15T23:00:00+00:00", True),
        ("2026-11-16T00:00:00+00:00", True),
        ("2026-11-16T00:59:59+00:00", True),
        ("2026-11-16T01:00:00+00:00", False),
    ],
)
def test_window_half_open_midnight(wall, allowed):
    assert (
        snapshot_dispatch_allowed(
            SnapshotWindow(start="23:00", end="01:00"), datetime.fromisoformat(wall)
        )
        is allowed
    )


def test_window_dst_actual_instants(monkeypatch):
    monkeypatch.setattr(
        "backend.metadata.capture.configuration.current_schedule_timezone",
        lambda: "America/New_York",
    )
    window = SnapshotWindow(start="01:15", end="01:45")
    for wall in ("2026-11-01T05:30:00+00:00", "2026-11-01T06:30:00+00:00"):
        assert snapshot_dispatch_allowed(window, datetime.fromisoformat(wall))
    gap = SnapshotWindow(start="02:00", end="03:00")
    assert not snapshot_dispatch_allowed(
        gap, datetime.fromisoformat("2026-03-08T06:59:00+00:00")
    )
    assert not snapshot_dispatch_allowed(
        gap, datetime.fromisoformat("2026-03-08T07:00:00+00:00")
    )
    assert snapshot_dispatch_allowed(
        None, datetime.fromisoformat("2026-03-08T07:00:00+00:00")
    )
    with pytest.raises(ValueError, match="aware"):
        snapshot_dispatch_allowed(None, datetime(2026, 1, 1))


@pytest.mark.parametrize(
    "change",
    [
        {"capture_credential": {"username": "u", "password": "p"}},
        {"snapshot_window": {"start": "23:00", "end": "01:00"}},
    ],
)
def test_capture_and_window_mutations_ensure_schedules(client, change):
    source = client.post(
        "/sources",
        json={
            "key": "schedule",
            "name": "Schedule",
            "engine": "postgresql",
            "access": _access(),
        },
    ).json()["source"]
    assert source["capture_state"] == "disabled"
    assert source["capture_credential_updated_at"] is None
    assert get_source_store().get_source(source["id"]).capture_revision == 0
    schedules = get_schedule_store()
    rows, _ = schedules.list_by_owner_ref(f"metadata:source:{source['id']}")
    assert len(rows) == 2
    for row in rows:
        assert schedules.delete(row.id)
    path = f"/sources/{source['id']}"
    response = client.patch(path, json=change)
    assert response.status_code == 200, response.text
    assert len(response.json()["schedules"]) == 2
    if "snapshot_window" in change:
        assert response.json()["source"]["snapshot_window"] == change["snapshot_window"]
        assert (
            client.patch(path, json={"name": "Retain window"}).json()["source"][
                "snapshot_window"
            ]
            == change["snapshot_window"]
        )
        assert (
            client.patch(path, json={"snapshot_window": None}).json()["source"][
                "snapshot_window"
            ]
            is None
        )
    else:
        client.patch(path, json={"capture_credential": None})
        cleared = get_source_store().get_source(source["id"])
        response = client.patch(path, json={"capture_credential": None})
        assert (
            get_source_store().get_source(source["id"]).capture_revision
            == cleared.capture_revision
        )
        assert response.json()["source"]["capture_credential_updated_at"] is not None
    audit = client.get("/audit/events")
    assert audit.status_code == 200
    assert "capture_credential_ciphertext" not in audit.text
    assert '"password"' not in audit.text


def test_window_uses_live_schedule_timezone_without_settings_permission(client):
    from backend.admin.system_parameters.resolver import set_parameter

    source = client.post(
        "/sources",
        json={
            "key": "live-zone",
            "name": "Live zone",
            "engine": "postgresql",
            "access": _access(),
            "snapshot_window": {"start": "09:00", "end": "10:00"},
        },
    ).json()["source"]
    window = SnapshotWindow(start="09:00", end="10:00")
    instant = datetime.fromisoformat("2026-11-15T01:30:00+00:00")
    assert not snapshot_dispatch_allowed(window, instant)
    set_parameter("schedule_timezone", "Asia/Shanghai", actor_user_id=None)
    assert snapshot_dispatch_allowed(window, instant)
    assert (
        client.get(f"/sources/{source['id']}").json()["source"]["schedule_timezone"]
        == "Asia/Shanghai"
    )
    assert get_source_store().get_source(source["id"]).snapshot_window == {
        "start": "09:00",
        "end": "10:00",
    }
