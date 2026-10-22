"""Channel Notes on the graph document (memory store)."""

from __future__ import annotations

import copy
import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.tests.problem import assert_problem  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.main import app  # noqa: E402

NOTE = {
    "id": "nt_intro",
    "position": {"x": -40.5, "y": 120},
    "size": {"width": 240, "height": 120},
    "text": "Reads suppliers.\nRuns hourly.",
}

GRAPH = {
    "nodes": [
        {
            "id": "nd_trigger",
            "ref": "run_manually",
            "type": "trigger.manual",
            "name": "Run manually",
            "position": {"x": 0, "y": 0},
            "config": {},
            "on_error": "stop",
            "retry": None,
        }
    ],
    "edges": [],
    "notes": [NOTE],
    "settings": {"run_timeout_sec": None, "error_channel_id": None},
}


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


def _channel(client: TestClient) -> str:
    created = client.post("/channels", json={"name": "Notes", "description": None})
    assert created.status_code == 201, created.text
    return created.json()["channel"]["id"]


def test_draft_save_keeps_notes(client: TestClient) -> None:
    channel_id = _channel(client)
    saved = client.put(
        f"/channels/{channel_id}/draft", json={"base_revision": 1, "graph": GRAPH}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["graph"]["notes"] == [NOTE]
    opened = client.get(f"/channels/{channel_id}/draft")
    assert opened.json()["graph"]["notes"] == [NOTE]


def _with_notes(*notes: dict) -> dict:
    graph = copy.deepcopy(GRAPH)
    graph["notes"] = list(notes)
    return graph


def _note(**changes: object) -> dict:
    return {**copy.deepcopy(NOTE), **changes}


@pytest.mark.parametrize(
    ("graph", "field"),
    [
        (_with_notes(_note(text="x" * 4001)), "graph.notes.0.text"),
        (_with_notes(_note(size={"width": 159, "height": 120})), "graph.notes.0.size.width"),
        (_with_notes(_note(size={"width": 240, "height": 2001})), "graph.notes.0.size.height"),
        (_with_notes(_note(id="bad id")), "graph.notes.0.id"),
        (_with_notes(_note(color="yellow")), "graph.notes.0.color"),
        (_with_notes(NOTE, _note()), "graph"),
        (_with_notes(_note(id="nd_trigger")), "graph"),
        (
            _with_notes(*[_note(id=f"nt_{index}") for index in range(201)]),
            "graph.notes",
        ),
    ],
    ids=[
        "text-too-long",
        "too-narrow",
        "too-tall",
        "malformed-id",
        "unknown-field",
        "duplicate-note-id",
        "note-id-collides-with-node",
        "too-many-notes",
    ],
)
def test_note_shape_violations_are_rejected(
    client: TestClient, graph: dict, field: str
) -> None:
    channel_id = _channel(client)
    for response in (
        client.put(f"/channels/{channel_id}/draft", json={"base_revision": 1, "graph": graph}),
        client.post(f"/channels/{channel_id}/draft/validate", json={"graph": graph}),
    ):
        body = assert_problem(response, status=422, code="REQUEST_INVALID")
        assert field in {item["field"] for item in body["details"]}, body
    assert client.get(f"/channels/{channel_id}/draft").json()["draft_revision"] == 1


def test_note_id_must_not_collide_with_an_edge_id(client: TestClient) -> None:
    channel_id = _channel(client)
    graph = copy.deepcopy(GRAPH)
    graph["nodes"].append({**graph["nodes"][0], "id": "nd_other", "ref": "other", "name": "Other"})
    graph["edges"] = [
        {
            "id": "ed_1",
            "source": {"node_id": "nd_trigger", "port": "main"},
            "target": {"node_id": "nd_other", "port": "main"},
        }
    ]
    graph["notes"] = [_note(id="ed_1")]
    response = client.put(
        f"/channels/{channel_id}/draft", json={"base_revision": 1, "graph": graph}
    )
    assert_problem(response, status=422, code="REQUEST_INVALID")


def test_graph_without_notes_round_trips_without_the_key(client: TestClient) -> None:
    channel_id = _channel(client)
    assert "notes" not in client.get(f"/channels/{channel_id}/draft").json()["graph"]
    legacy = copy.deepcopy(GRAPH)
    del legacy["notes"]
    saved = client.put(
        f"/channels/{channel_id}/draft", json={"base_revision": 1, "graph": legacy}
    )
    assert saved.status_code == 200, saved.text
    assert "notes" not in saved.json()["graph"]
    emptied = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": 2, "graph": _with_notes()},
    )
    assert emptied.status_code == 200, emptied.text
    assert "notes" not in emptied.json()["graph"]
    checked = client.post(f"/channels/{channel_id}/draft/validate", json={"graph": legacy})
    assert checked.json()["valid"] is True, checked.text


def test_validate_ignores_notes(client: TestClient) -> None:
    channel_id = _channel(client)
    with_notes = client.post(f"/channels/{channel_id}/draft/validate", json={"graph": GRAPH})
    assert with_notes.status_code == 200, with_notes.text
    without = copy.deepcopy(GRAPH)
    del without["notes"]
    plain = client.post(f"/channels/{channel_id}/draft/validate", json={"graph": without})
    assert with_notes.json() == plain.json()
    assert with_notes.json()["valid"] is True


def test_publish_and_runs_carry_notes(client: TestClient) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job

    channel_id = _channel(client)
    saved = client.put(
        f"/channels/{channel_id}/draft", json={"base_revision": 1, "graph": GRAPH}
    )
    assert saved.status_code == 200, saved.text
    published = client.post(f"/channels/{channel_id}/publish", json={"draft_revision": 2})
    assert published.status_code == 201, published.text
    assert published.json()["version"]["graph"]["notes"] == [NOTE]
    version = client.get(f"/channels/{channel_id}/versions/1").json()["version"]
    assert version["graph"]["notes"] == [NOTE]

    previous = set_dispatcher(run_job)
    try:
        started = [
            client.post(f"/channels/{channel_id}/runs", json={"target": target})
            for target in ("draft", "published")
        ]
    finally:
        set_dispatcher(previous)
    for response in started:
        assert response.status_code == 202, response.text
        job_id = response.json()["run"]["job_id"]
        detail = client.get(f"/channels/{channel_id}/runs/{job_id}").json()
        assert detail["run"]["status"] == "succeeded"
        assert detail["graph"]["notes"] == [NOTE]
        assert "node_executions" not in detail
        assert [item["node_id"] for item in detail["node_summaries"]] == ["nd_trigger"]
        listed = client.get(f"/channels/{channel_id}/runs/{job_id}/executions")
        assert listed.status_code == 200, listed.text
        assert [item["node_id"] for item in listed.json()["items"]] == ["nd_trigger"]


def test_template_preview_accepts_notes(client: TestClient) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job

    channel_id = _channel(client)
    client.put(f"/channels/{channel_id}/draft", json={"base_revision": 1, "graph": GRAPH})
    previous = set_dispatcher(run_job)
    try:
        started = client.post(f"/channels/{channel_id}/runs", json={"target": "draft"})
    finally:
        set_dispatcher(previous)
    job_id = started.json()["run"]["job_id"]
    graph = copy.deepcopy(GRAPH)
    graph["nodes"].append(
        {
            "id": "nd_keep",
            "ref": "keep",
            "type": "state.variable",
            "name": "Keep",
            "position": {"x": 0, "y": 100},
            "config": {"operation": "set", "name": "lease", "value": "{{ self.run.id }}"},
            "on_error": "stop",
            "retry": None,
        }
    )
    graph["edges"] = [
        {
            "id": "ed_keep",
            "source": {"node_id": "nd_trigger", "port": "main"},
            "target": {"node_id": "nd_keep", "port": "main"},
        }
    ]
    preview = client.post(
        f"/channels/{channel_id}/runs/{job_id}/template-preview",
        json={"graph": graph, "node_id": "nd_keep", "path": ["value"]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["value"] == job_id


def test_editing_notes_needs_no_node_type_permission(client: TestClient) -> None:
    from backend.admin.roles import create_role

    channel_id = _channel(client)
    graph = copy.deepcopy(GRAPH)
    graph["nodes"].append(
        {
            "id": "nd_code",
            "ref": "code",
            "type": "transform.code",
            "name": "Code",
            "position": {"x": 240, "y": 0},
            "config": {"code": "return {'ok': True}"},
            "on_error": "stop",
            "retry": None,
        }
    )
    saved = client.put(
        f"/channels/{channel_id}/draft", json={"base_revision": 1, "graph": graph}
    )
    assert saved.status_code == 200, saved.text

    role = create_role(
        get_role_store(),
        key="note_writer",
        name="Note writer",
        permissions=["console:access", "channel:read", "channel:write"],
    )
    get_user_store().create_user(
        account="note_writer",
        display_name="Note writer",
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    with TestClient(app) as writer:
        login = writer.post(
            "/auth/login", json={"account": "note_writer", "password": "secret"}
        )
        assert login.status_code == 200, login.text
        current = writer.get(f"/channels/{channel_id}/draft").json()
        edited = current["graph"]
        edited["notes"] = [
            _note(text="Edited", size={"width": 400, "height": 300}),
            _note(id="nt_more", position={"x": 500, "y": 500}),
        ]
        kept = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": edited},
        )
        assert kept.status_code == 200, kept.text
        assert [note["id"] for note in kept.json()["graph"]["notes"]] == ["nt_intro", "nt_more"]
