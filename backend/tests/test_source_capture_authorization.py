"""Capture fields obey Role plus Source instance authorization."""

from backend.tests.test_source_lifecycle_access import client, _login, _user_id, _access
from backend.metadata.source_access import create_membership


def test_capture_authorization_and_identity_projection(client):
    _login(client, "admin")
    response = client.post(
        "/sources",
        json={
            "key": "private-capture",
            "name": "Private",
            "engine": "postgresql",
            "access": _access(),
            "capture_credential": {
                "username": "capture-private-user",
                "password": "capture-private-password",
            },
        },
    )
    assert response.status_code == 201
    source_id = response.json()["source"]["id"]
    path = f"/sources/{source_id}"
    _login(client, "writer")
    assert client.patch(path, json={"capture_credential": None}).status_code == 404
    create_membership(
        subject_type="user",
        subject_id=_user_id("writer"),
        target=source_id,
        level="viewer",
    )
    assert client.patch(path, json={"capture_credential": None}).status_code == 403
    _login(client, "grantor")
    items = client.get("/sources").json()["items"]
    assert len(items) == 1
    assert set(items[0]) == {"id", "key", "name", "kind", "engine", "status"}
    assert client.patch(path, json={"capture_credential": None}).status_code == 403
    assert (
        client.patch("/sources/missing", json={"capture_credential": None}).status_code
        == 403
    )
    _login(client, "admin")
    assert client.get(path).json()["source"]["capture_credential_set"] is True
    assert client.patch(path, json={"capture_credential": None}).status_code == 200
