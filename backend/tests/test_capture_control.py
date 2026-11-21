"""Capture control intent through the real Source HTTP boundary."""

import pytest

from backend.core.time import utc_now
from backend.metadata.capture.control import record_applied_evidence
from backend.metadata.errors import SourceCaptureControlConflict
from backend.tests.test_sources_jobs import client, _access
from backend.metadata.capture.control import capture_status
from backend.metadata.sources.store import get_source_store


def test_binding_survives_clear_and_blocks_delete_and_retarget(client, monkeypatch):
    response = client.post(
        "/sources",
        json={
            "key": "retained",
            "name": "Retained",
            "engine": "postgresql",
            "access": _access(),
            "capture_credential": {"username": "capture", "password": "private"},
        },
    )
    assert response.status_code == 201, response.text
    source_id = response.json()["source"]["id"]
    initial = capture_status(source_id)
    status = client.get(f"/sources/{source_id}/capture-status")
    assert status.status_code == 200
    assert status.json() == initial
    assert initial["binding_id"]
    assert initial["control"]["control_revision"] == 1
    assert initial["control"]["credential_revision"] == 1
    assert initial["availability"] == "unknown"
    assert initial["operations"][-1]["kind"] == "stop"
    assert (
        client.patch(
            f"/sources/{source_id}",
            json={
                "capture_credential": None,
                "status": "disabled",
            },
        ).status_code
        == 200
    )
    stopped = capture_status(source_id)
    assert stopped["binding_id"] == initial["binding_id"]
    assert stopped["control"]["control_revision"] == 2
    assert stopped["control"]["credential_revision"] == 2
    assert stopped["control"]["stop_ack"] is None
    assert stopped["availability"] == "unknown"
    assert stopped["operations"][-1]["kind"] == "stop"
    assert [op["state"] for op in stopped["operations"]] == ["superseded", "pending"]
    assert (
        client.patch(
            f"/sources/{source_id}",
            json={
                "access": _access(host="different"),
            },
        ).json()["code"]
        == "SOURCE_CAPTURE_SCOPE_LOCKED"
    )
    from backend.metadata.sources import service

    def unexpected_cascade(*args):
        pytest.fail("retained Source must be checked before cascade")

    monkeypatch.setattr(service.get_catalog_store(), "delete_objects_for_source", unexpected_cascade)
    monkeypatch.setattr(service.get_structure_diff_store(), "delete_for_source", unexpected_cascade)
    monkeypatch.setattr(service, "delete_source_schedules_by_source_id", unexpected_cascade)
    denied = client.delete(f"/sources/{source_id}")
    assert denied.status_code == 409
    assert denied.json()["code"] == "SOURCE_CAPTURE_RESOURCES_RETAINED"
    assert get_source_store().get_source(source_id) is not None


def test_control_and_credential_revisions_are_independent(client):
    source = client.post(
        "/sources",
        json={
            "key": "revisions",
            "name": "Revisions",
            "engine": "postgresql",
            "access": _access(),
            "capture_credential": {"username": "capture", "password": "private"},
        },
    ).json()["source"]
    path = f"/sources/{source['id']}"
    client.patch(path, json={"snapshot_window": {"start": "01:00", "end": "02:00"}})
    state = capture_status(source["id"])
    assert state["control"]["control_revision"] == 2
    assert state["control"]["credential_revision"] == 1
    client.patch(path, json={"name": "No executable change"})
    assert capture_status(source["id"])["control"]["control_revision"] == 2
    assert "private" not in str(state)
    assert "capture_credential_ciphertext" not in str(state)


def test_stop_requires_exact_current_evidence_and_duplicate_identity(client):
    source = client.post(
        "/sources",
        json={
            "key": "proof",
            "name": "Proof",
            "engine": "postgresql",
            "access": _access(),
            "capture_credential": {"username": "capture", "password": "private"},
        },
    ).json()["source"]
    source_id = source["id"]
    client.patch(f"/sources/{source_id}", json={"status": "disabled"})
    command, = (op for op in capture_status(source_id)["operations"] if op["state"] == "pending")
    evidence = {
        key: command[key]
        for key in (
            "operation_id",
            "source_id",
            "binding_id",
            "owner_epoch",
            "runtime_instance_id",
            "capture_generation",
            "control_revision",
            "credential_revision",
        )
    }
    evidence["observed_at"] = utc_now().isoformat()
    for key in (
        "target_fence_ref",
        "owner_exclusion_ref",
        "retired_commands_rejected_ref",
        "task_stopped_ref",
        "source_session_stopped_ref",
        "inflight_drained_ref",
    ):
        evidence[key] = "proof-id"
    kwargs = {"source_id": source_id, "operation_id": command["operation_id"]}
    with pytest.raises(SourceCaptureControlConflict):
        record_applied_evidence(**kwargs, evidence={**evidence, "control_revision": 1})
    assert capture_status(source_id)["control"]["stop_ack"] is None
    assert record_applied_evidence(**kwargs, evidence=evidence) == evidence
    assert record_applied_evidence(**kwargs, evidence=evidence) == evidence
    assert all(op["state"] != "pending" for op in capture_status(source_id)["operations"])
    client.patch(f"/sources/{source_id}", json={"capture_credential": None})
    assert capture_status(source_id)["control"]["stop_ack"] is None
    with pytest.raises(SourceCaptureControlConflict):
        record_applied_evidence(**kwargs, evidence=evidence)


def test_ordinary_disabled_unbound_delete_is_preserved(client):
    source = client.post(
        "/sources",
        json={
            "key": "unbound",
            "name": "Unbound",
            "engine": "postgresql",
            "access": _access(),
        },
    ).json()["source"]
    path = f"/sources/{source['id']}"
    client.patch(path, json={"status": "disabled"})
    assert client.delete(path).status_code == 204
