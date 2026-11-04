"""Data Channel HTTP tests against the memory store."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.tests.problem import assert_problem  # noqa: E402
from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.channel.run_store import get_run_store  # noqa: E402
from backend.channel.store import get_channel_store  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.jobs.store import get_job_store  # noqa: E402
from backend.main import app  # noqa: E402

TRIGGER_GRAPH = {
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
    "settings": {"run_timeout_sec": None, "error_channel_id": None},
}


def _login(client: TestClient, account: str, password: str) -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": password}
    )
    assert response.status_code == 200, response.text


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
        _login(test_client, "admin", "secret")
        yield test_client


def test_unauthenticated_is_rejected() -> None:
    with TestClient(app) as client:
        response = client.get("/channels")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_read_permission_cannot_write() -> None:
    roles = get_role_store()
    seed_roles(roles)
    role = create_role(
        roles,
        key="channel_reader",
        name="Channel reader",
        permissions=["console:access", "channel:read"],
    )
    get_user_store().create_user(
        account="reader",
        display_name="Reader",
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    with TestClient(app) as client:
        _login(client, "reader", "secret")
        assert client.get("/channels").status_code == 200
        denied = client.post(
            "/channels", json={"name": "Material", "description": None}
        )
    assert denied.status_code == 403


def test_stop_at_ignores_errors_outside_the_closure(client: TestClient) -> None:
    from backend.channel.channel_run import set_dispatcher

    previous = set_dispatcher(lambda _job_id: None)
    try:
        _stop_at_ignores_errors_outside_the_closure(client)
    finally:
        set_dispatcher(previous)


def _stop_at_ignores_errors_outside_the_closure(client: TestClient) -> None:
    created = client.post("/channels", json={"name": "Material", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    graph = {
        "nodes": [
            *TRIGGER_GRAPH["nodes"],
            {
                "id": "nd_bad",
                "ref": "bad_node",
                "type": "not.a.type",
                "name": "Bad",
                "position": {"x": 200, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "ed_bad",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_bad", "port": "main"},
            }
        ],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": 1, "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    started = client.post(
        f"/channels/{channel_id}/runs",
        json={"target": "draft", "stop_at_node_id": "nd_trigger"},
    )
    assert started.status_code == 202, started.text
    assert started.json()["run"]["stop_at_node_id"] == "nd_trigger"
    refused = client.post(
        f"/channels/{channel_id}/runs",
        json={"target": "draft", "stop_at_node_id": "nd_missing"},
    )
    body = assert_problem(refused, status=422, code="CHANNEL_GRAPH_INVALID")
    assert body["problems"] == []
    scoped = client.post(
        f"/channels/{channel_id}/runs",
        json={"target": "draft", "stop_at_node_id": "nd_bad"},
    )
    body = assert_problem(scoped, status=422, code="CHANNEL_GRAPH_INVALID")
    assert body["problems"]
    assert {item["node_id"] for item in body["problems"]} <= {"nd_bad", None}
    assert all(item["severity"] == "error" for item in body["problems"])
    whole = client.post(f"/channels/{channel_id}/runs", json={"target": "draft"})
    body = assert_problem(whole, status=422, code="CHANNEL_GRAPH_INVALID")
    assert body["problems"]
    publish = client.post(f"/channels/{channel_id}/publish", json={"draft_revision": 2})
    body = assert_problem(publish, status=422, code="CHANNEL_GRAPH_INVALID")
    assert body["problems"]


def test_create_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/channels", json={"name": "Material", "description": None, "active": True}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_draft_conflict_and_invalid_publish(client: TestClient) -> None:
    created = client.post("/channels", json={"name": "Material", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    assert created.json()["channel"]["active"] is False
    assert created.json()["channel"]["draft_revision"] == 1
    assert created.json()["channel"]["latest_version"] is None

    conflict = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": 9, "graph": TRIGGER_GRAPH},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CHANNEL_DRAFT_CONFLICT"

    broken = {
        "nodes": [
            {
                "id": "nd_read",
                "ref": "read_suppliers",
                "type": "write.entity",
                "name": "Read",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            }
        ],
        "edges": [],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": 1, "graph": broken},
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()["draft_revision"]
    published = client.post(
        f"/channels/{channel_id}/publish",
        json={"draft_revision": revision},
    )
    assert published.status_code == 422
    body = published.json()
    assert body["code"] == "CHANNEL_GRAPH_INVALID"
    assert body["detail"]

    before = client.get(f"/channels/{channel_id}/draft")
    assert before.status_code == 200, before.text
    checked = client.post(
        f"/channels/{channel_id}/draft/validate",
        json={"graph": broken},
    )
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert "draft_revision" not in body
    assert body["valid"] is False
    assert body["problems"]
    assert body["ports"]
    assert "schema" in body["ports"][0]
    assert set(body["context"]) == {"channel", "run", "platform"}
    after = client.get(f"/channels/{channel_id}/draft")
    assert after.json()["draft_revision"] == before.json()["draft_revision"]
    assert after.json()["graph"] == before.json()["graph"]


def test_stored_graph_without_ref_is_readable_and_validate_rejects_it(
    client: TestClient,
) -> None:
    created = client.post("/channels", json={"name": "Legacy", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    legacy = {
        "nodes": [
            {
                "id": "nd_trigger",
                "type": "trigger.manual",
                "name": "Run",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_read",
                "type": "read.entity",
                "name": "Read",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_write",
                "type": "write.entity",
                "name": "Write",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "ed_1",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_read", "port": "main"},
            },
            {
                "id": "ed_2",
                "source": {"node_id": "nd_read", "port": "main"},
                "target": {"node_id": "nd_write", "port": "main"},
            },
        ],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }
    stored = get_channel_store().replace_draft(
        channel_id,
        base_revision=created.json()["channel"]["draft_revision"],
        graph=legacy,
        now=utc_now(),
    )
    opened = client.get(f"/channels/{channel_id}/draft")
    assert opened.status_code == 200, opened.text
    assert opened.json()["graph"]["nodes"] == legacy["nodes"]
    assert "ref" not in opened.json()["graph"]["nodes"][0]
    version = get_channel_store().publish_version(
        channel_id,
        draft_revision=stored.draft_revision,
        published_at=utc_now(),
        published_by_user_id="user_admin",
    )
    fetched = client.get(f"/channels/{channel_id}/versions/{version.number}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["version"]["graph"]["nodes"] == legacy["nodes"]
    checked = client.post(
        f"/channels/{channel_id}/draft/validate",
        json={"graph": legacy},
    )
    assert checked.status_code == 422
    assert checked.json()["code"] == "REQUEST_INVALID"


def test_node_type_catalog_and_audit(client: TestClient) -> None:
    catalog = client.get("/channel-node-types")
    assert catalog.status_code == 200, catalog.text
    items = catalog.json()["items"]
    assert [item["type"] for item in items] == [
        "trigger.error",
        "trigger.inbound",
        "trigger.manual",
        "trigger.scheduled",
        "read.changes",
        "read.source_query",
        "read.sql",
        "transform.code",
        "transform.deduplicate",
        "transform.filter",
        "transform.if",
        "transform.merge",
        "transform.set_fields",
        "volume.batch_read",
        "volume.changes_dataset",
        "volume.dataset_query",
        "volume.for",
        "volume.materialize",
        "volume.until",
        "state.variable",
        "write.entity",
        "action.email",
        "action.http",
        "action.respond",
        "action.webhook",
    ]
    manual = next(item for item in items if item["type"] == "trigger.manual")
    assert manual["trigger"] is True
    assert manual["label"] == "Manual trigger"
    assert manual["summary"]
    assert manual["description"]
    assert manual["inputs"] == []
    assert manual["outputs"][0]["port"] == "main"
    assert manual["outputs"][0]["coarse_type"] == "object"
    assert manual["outputs"][0]["description"]
    assert manual["type_version"] == 1
    error_trigger = next(item for item in items if item["type"] == "trigger.error")
    assert error_trigger["trigger"] is True
    assert error_trigger["config_schema"]["properties"] == {}
    by_type = {item["type"]: item for item in items}
    assert by_type["volume.for"]["container"] == {"round_templates": []}
    assert by_type["volume.batch_read"]["container"] == {"round_templates": []}
    assert by_type["volume.until"]["container"] == {"round_templates": ["until"]}
    assert all(
        item["container"] is None
        for item in items
        if item["type"] not in {"volume.for", "volume.batch_read", "volume.until"}
    )
    assert by_type["transform.code"]["permission"] == "channel:code_write"
    assert by_type["read.source_query"]["permission"] == "channel:source_query"
    assert (
        by_type["transform.code"]["config_schema"]["properties"]["code"][
            "contentMediaType"
        ]
        == "text/x-python"
    )
    assert (
        by_type["read.source_query"]["config_schema"]["properties"]["source_id"][
            "x-refraq-ref"
        ]
        == "source"
    )
    assert all(
        item["permission"] is None
        for item in items
        if item["type"] not in {"transform.code", "read.source_query"}
    )
    write = next(item for item in items if item["type"] == "write.entity")
    sql = next(item for item in items if item["type"] == "read.sql")
    assert "x-refraq-ref" in write["config_schema"]["properties"]["entity_id"]
    assert "x-refraq-template" in write["config_schema"]["properties"]["source"]
    sql_field = sql["config_schema"]["properties"]["sql"]
    assert "x-refraq-template" in sql_field
    assert "x-refraq-ref" not in sql_field
    assert "Quote literals in the statement." in sql_field["description"]
    assert sql["config_schema"]["properties"]["source"]["x-refraq-ref"] == "sql_source"
    assert "source" in sql["config_schema"]["required"]

    created = client.post(
        "/channels", json={"name": "Material", "description": "from U9"}
    )
    assert created.status_code == 201
    events, _cursor = get_audit_store().list_events(limit=20)
    assert any(event.action == "channel.create" for event in events)


def test_activate_and_deactivate(client: TestClient) -> None:
    created = client.post("/channels", json={"name": "Material", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    assert created.json()["channel"]["active"] is False

    activated = client.post(f"/channels/{channel_id}/activate")
    assert activated.status_code == 200, activated.text
    assert activated.json()["channel"]["active"] is True
    again = client.post(f"/channels/{channel_id}/activate")
    assert again.status_code == 200
    assert again.json()["channel"]["active"] is True

    deactivated = client.post(f"/channels/{channel_id}/deactivate")
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["channel"]["active"] is False
    current = client.get(f"/channels/{channel_id}")
    assert current.status_code == 200
    assert current.json()["channel"]["active"] is False


SCHEDULED_GRAPH = {
    "nodes": [
        {
            "id": "nd_hourly",
            "ref": "hourly",
            "type": "trigger.scheduled",
            "name": "Hourly",
            "position": {"x": 0, "y": 0},
            "config": {"cron": "0 * * * *", "interval_seconds": None, "start_at": None},
            "on_error": "stop",
            "retry": None,
        }
    ],
    "edges": [],
    "settings": {"run_timeout_sec": 60, "error_channel_id": None},
}


def _save_draft(client: TestClient, channel_id: str, graph: dict) -> int:
    current = client.get(f"/channels/{channel_id}/draft")
    assert current.status_code == 200, current.text
    revision = current.json()["draft_revision"]
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": revision, "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    return saved.json()["draft_revision"]


def test_publish_syncs_and_activation_toggles_the_schedule(client: TestClient) -> None:
    from backend.worker.schedules import get_schedule_store

    created = client.post("/channels", json={"name": "Material", "description": None})
    channel_id = created.json()["channel"]["id"]
    revision = _save_draft(client, channel_id, SCHEDULED_GRAPH)
    published = client.post(
        f"/channels/{channel_id}/publish", json={"draft_revision": revision}
    )
    assert published.status_code == 201, published.text
    store = get_schedule_store()
    row = store.get_by_key(f"channel_run:{channel_id}")
    assert row is not None
    assert row.enabled is False
    assert row.locked is True
    assert row.undeletable is True
    assert row.running_timeout_sec is None
    assert row.next_run_at is None
    assert row.owner_ref == f"channel:{channel_id}"

    changed = dict(SCHEDULED_GRAPH)
    changed["nodes"] = [
        {**SCHEDULED_GRAPH["nodes"][0], "config": {"cron": "15 * * * *"}}
    ]
    _save_draft(client, channel_id, changed)
    assert store.get_by_key(f"channel_run:{channel_id}").cron == "0 * * * *"

    activated = client.post(f"/channels/{channel_id}/activate")
    assert activated.status_code == 200
    row = store.get_by_key(f"channel_run:{channel_id}")
    assert row.enabled is True
    assert row.next_run_at is not None

    renamed = client.patch(f"/channels/{channel_id}", json={"name": "Materials"})
    assert renamed.status_code == 200, renamed.text
    assert "Materials" in store.get_by_key(f"channel_run:{channel_id}").name

    manual = _save_draft(client, channel_id, TRIGGER_GRAPH)
    published_manual = client.post(
        f"/channels/{channel_id}/publish", json={"draft_revision": manual}
    )
    assert published_manual.status_code == 201, published_manual.text
    assert store.get_by_key(f"channel_run:{channel_id}") is None

    deleted = client.delete(f"/channels/{channel_id}")
    assert deleted.status_code == 204


def _credential(client: TestClient, name: str = "Hook token") -> str:
    created = client.post(
        "/inbound-credentials",
        json={
            "name": name,
            "type": "token",
            "secret": "token-secret-9f3a",
            "config": {"location": "header", "name": "X-Hook-Token"},
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["inbound_credential"]["id"]


def _channel(client: TestClient, name: str) -> str:
    created = client.post("/channels", json={"name": name, "description": None})
    assert created.status_code == 201, created.text
    return created.json()["channel"]["id"]


def _hook_node(
    credential_id: str,
    path: str,
    *,
    mode: str = "immediate",
    sample: dict | None = None,
) -> dict:
    response: dict = {"mode": mode}
    if mode == "immediate":
        response["body"] = {"kind": "static", "text": "ok"}
    config: dict = {
        "path": path,
        "credential_id": credential_id,
        "response": response,
    }
    if sample is not None:
        config["sample_request"] = sample
    return {
        "id": "nd_hook",
        "ref": "hook",
        "type": "trigger.inbound",
        "name": "Inbound",
        "position": {"x": 0, "y": 0},
        "config": config,
        "on_error": "stop",
        "retry": None,
    }


def _inbound_graph(*nodes: dict, edges: list | None = None) -> dict:
    return {
        "nodes": list(nodes),
        "edges": [] if edges is None else edges,
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }


def _publish(client: TestClient, channel_id: str, graph: dict) -> object:
    revision = _save_draft(client, channel_id, graph)
    return client.post(
        f"/channels/{channel_id}/publish", json={"draft_revision": revision}
    )


def test_publish_registers_one_inbound_path(client: TestClient) -> None:
    from backend.channel.inbound_paths import get_inbound_path_store

    credential_id = _credential(client)
    channel_id = _channel(client, "Orders")
    published = _publish(
        client, channel_id, _inbound_graph(_hook_node(credential_id, "orders"))
    )
    assert published.status_code == 201, published.text
    store = get_inbound_path_store()
    row = store.get("orders")
    assert row is not None
    assert row.channel_id == channel_id
    assert row.node_id == "nd_hook"

    drafted = _save_draft(
        client, channel_id, _inbound_graph(_hook_node(credential_id, "shipments"))
    )
    assert store.get("orders") is not None
    assert store.get("orders").channel_id == channel_id
    assert store.get("shipments") is None

    moved = client.post(
        f"/channels/{channel_id}/publish", json={"draft_revision": drafted}
    )
    assert moved.status_code == 201, moved.text
    assert store.get("orders") is None
    shipped = store.get("shipments")
    assert shipped is not None
    assert shipped.channel_id == channel_id
    assert shipped.node_id == "nd_hook"

    activated = client.post(f"/channels/{channel_id}/activate")
    assert activated.status_code == 200, activated.text
    deactivated = client.post(f"/channels/{channel_id}/deactivate")
    assert deactivated.status_code == 200, deactivated.text
    assert store.get("shipments").channel_id == channel_id

    replaced = _publish(client, channel_id, TRIGGER_GRAPH)
    assert replaced.status_code == 201, replaced.text
    assert store.get("shipments") is None

    again = _publish(
        client, channel_id, _inbound_graph(_hook_node(credential_id, "orders"))
    )
    assert again.status_code == 201, again.text
    deleted = client.delete(f"/channels/{channel_id}")
    assert deleted.status_code == 204
    assert store.get("orders") is None


def test_taken_inbound_path_does_not_replace_the_other_channel(client: TestClient) -> None:
    from backend.channel.inbound_paths import get_inbound_path_store

    credential_id = _credential(client, "Shared token")
    owner = _channel(client, "Owner")
    other = _channel(client, "Other")
    held = _publish(client, owner, _inbound_graph(_hook_node(credential_id, "orders")))
    assert held.status_code == 201, held.text
    refused = _publish(
        client, other, _inbound_graph(_hook_node(credential_id, "orders"))
    )
    assert_problem(refused, status=409, code="CHANNEL_INBOUND_PATH_TAKEN")
    row = get_inbound_path_store().get("orders")
    assert row is not None
    assert row.channel_id == owner
    assert row.node_id == "nd_hook"
    versions = client.get(f"/channels/{other}/versions")
    assert versions.status_code == 200, versions.text
    assert versions.json()["total"] == 0


def test_publish_refuses_a_missing_inbound_credential(client: TestClient) -> None:
    from backend.channel.inbound_paths import get_inbound_path_store

    channel_id = _channel(client, "Missing credential")
    graph = _inbound_graph(_hook_node("icr_missing", "orders"))
    checked = client.post(
        f"/channels/{channel_id}/draft/validate", json={"graph": graph}
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["valid"] is True
    refused = _publish(client, channel_id, graph)
    assert_problem(refused, status=422, code="CHANNEL_INBOUND_CREDENTIAL_NOT_FOUND")
    assert get_inbound_path_store().get("orders") is None
    versions = client.get(f"/channels/{channel_id}/versions")
    assert versions.status_code == 200, versions.text
    assert versions.json()["total"] == 0


def test_test_run_uses_the_sample_and_records_an_undelivered_response(
    client: TestClient,
) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job

    credential_id = _credential(client, "Sample token")
    channel_id = _channel(client, "Sample")
    bare = _publish(
        client,
        channel_id,
        _inbound_graph(_hook_node(credential_id, "bare")),
    )
    assert bare.status_code == 201, bare.text
    previous = set_dispatcher(run_job)
    try:
        started = client.post(
            f"/channels/{channel_id}/runs", json={"target": "draft"}
        )
    finally:
        set_dispatcher(previous)
    assert started.status_code == 202, started.text
    job_id = started.json()["run"]["job_id"]
    run = get_run_store().get_run(job_id)
    assert run is not None and run.context is not None
    execution = get_run_store().list_executions(job_id)
    assert execution[0].node_id == "nd_hook"
    assert execution[0].output == {
        "method": "POST",
        "headers": {},
        "query": {},
        "body": None,
        "raw_body": None,
        "event_id": None,
        "received_at": run.context["run"]["started_at"],
    }

    sample = {
        "method": "PUT",
        "headers": {"X-Request-Id": "abc"},
        "query": {"id": "9"},
        "body": {"n": 1},
    }
    reply = {
        "id": "nd_reply",
        "ref": "reply",
        "type": "action.respond",
        "name": "Respond",
        "position": {"x": 240, "y": 0},
        "config": {
            "status": "202",
            "content_type": "text/plain",
            "headers": {"X-Trace": "abc"},
            "body": '"accepted"',
        },
        "on_error": "stop",
        "retry": None,
    }
    edge = {
        "id": "ed_reply",
        "source": {"node_id": "nd_hook", "port": "main"},
        "target": {"node_id": "nd_reply", "port": "main"},
    }
    saved = _save_draft(
        client,
        channel_id,
        _inbound_graph(
            _hook_node(credential_id, "bare", mode="respond_node", sample=sample),
            reply,
            edges=[edge],
        ),
    )
    assert saved
    previous = set_dispatcher(run_job)
    try:
        answered = client.post(
            f"/channels/{channel_id}/runs", json={"target": "draft"}
        )
    finally:
        set_dispatcher(previous)
    assert answered.status_code == 202, answered.text
    answered_id = answered.json()["run"]["job_id"]
    answered_run = get_run_store().get_run(answered_id)
    assert answered_run is not None and answered_run.context is not None
    by_node = {
        item.node_id: item
        for item in get_run_store().list_executions(answered_id)
    }
    assert by_node["nd_hook"].output == {
        "method": "PUT",
        "headers": {"x-request-id": "abc"},
        "query": {"id": "9"},
        "body": {"n": 1},
        "raw_body": None,
        "event_id": None,
        "received_at": answered_run.context["run"]["started_at"],
    }
    assert by_node["nd_reply"].output == {
        "status": 202,
        "headers": {"X-Trace": "abc", "Content-Type": "text/plain"},
        "body": "accepted",
        "delivered": False,
    }


def test_global_variable_list_and_delete(client: TestClient) -> None:
    from backend.channel.variables import get_variable_store

    saved = get_variable_store().apply(
        operation="set", name="lease", value={"held": True}
    )
    assert saved.applied is True
    bad_name = client.delete("/channel-variables/not a name")
    assert_problem(
        bad_name,
        status=422,
        code="CHANNEL_VARIABLE_NAME_INVALID",
        detail="Global Variable name is invalid",
    )
    missing_value = client.delete("/channel-variables/absent")
    assert_problem(
        missing_value,
        status=404,
        code="CHANNEL_VARIABLE_NOT_FOUND",
        detail="Global Variable not found",
    )
    listed = client.get("/channel-variables")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["name"] == "lease"
    removed = client.delete("/channel-variables/lease")
    assert removed.status_code == 204
    assert client.get("/channel-variables").json()["items"] == []
    events, _cursor = get_audit_store().list_events(limit=20)
    assert any(event.action == "channel.variable_delete" for event in events)


def test_channel_variable_http(client: TestClient) -> None:
    from backend.channel.variables import get_variable_store

    created = client.post("/channels", json={"name": "Material", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    other = client.post("/channels", json={"name": "Other", "description": None})
    assert other.status_code == 201, other.text
    other_id = other.json()["channel"]["id"]
    store = get_variable_store()
    store.apply(operation="set", name="lease", value={"held": True})
    store.apply(operation="set", name="cursor", value=1, channel_id=channel_id)
    store.apply(operation="set", name="cursor", value=2, channel_id=other_id)

    site = client.get("/channel-variables")
    assert site.status_code == 200, site.text
    assert [item["name"] for item in site.json()["items"]] == ["lease"]

    missing = client.get("/channels/chn_missing/variables")
    assert_problem(missing, status=404, code="CHANNEL_NOT_FOUND")
    bad_name = client.delete(f"/channels/{channel_id}/variables/not a name")
    assert_problem(
        bad_name,
        status=422,
        code="CHANNEL_VARIABLE_NAME_INVALID",
        detail="Channel Variable name is invalid",
    )
    absent_channel = client.delete("/channels/chn_missing/variables/cursor")
    assert_problem(absent_channel, status=404, code="CHANNEL_NOT_FOUND")
    before, _cursor = get_audit_store().list_events(limit=50)
    owned_before = [
        event for event in before if event.action == "channel.owned_variable_delete"
    ]
    absent = client.delete(f"/channels/{channel_id}/variables/missing")
    assert_problem(
        absent,
        status=404,
        code="CHANNEL_VARIABLE_NOT_FOUND",
        detail="Channel Variable not found",
    )
    after_miss, _cursor = get_audit_store().list_events(limit=50)
    assert [
        event for event in after_miss if event.action == "channel.owned_variable_delete"
    ] == owned_before

    listed = client.get(f"/channels/{channel_id}/variables")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["name"] == "cursor"
    assert listed.json()["items"][0]["value"] == 1
    removed = client.delete(f"/channels/{channel_id}/variables/cursor")
    assert removed.status_code == 204
    assert client.get(f"/channels/{channel_id}/variables").json()["items"] == []
    events, _cursor = get_audit_store().list_events(limit=50)
    deleted = [
        event for event in events if event.action == "channel.owned_variable_delete"
    ]
    assert deleted[-1].resource_type == "channel_owned_variable"
    assert deleted[-1].resource_id == f"{channel_id}/cursor"
    assert deleted[-1].detail == {"channel_id": channel_id, "name": "cursor"}
    assert store.apply(operation="get", name="cursor", channel_id=other_id).value == 2
    assert store.apply(operation="get", name="lease").found is True

    gone = client.delete(f"/channels/{channel_id}")
    assert gone.status_code == 204
    assert store.apply(operation="get", name="lease").found is True
    assert store.apply(operation="get", name="cursor", channel_id=other_id).value == 2
    assert store.list_live(limit=50, offset=0, channel_id=channel_id)[1] == 0


def _guarded_graph(
    type_id: str, config: dict, *, trigger_name: str = "Run manually"
) -> dict:
    return {
        "nodes": [
            {
                "id": "nd_trigger",
                "ref": "run_manually",
                "type": "trigger.manual",
                "name": trigger_name,
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_guard",
                "ref": "guarded",
                "type": type_id,
                "name": "Guarded node",
                "position": {"x": 240, "y": 0},
                "config": config,
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "ed_guard",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_guard", "port": "main"},
            }
        ],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }


def _writer_client(
    account: str, permissions: list[str] | None = None
) -> TestClient:
    role = create_role(
        get_role_store(),
        key=f"role_{account}",
        name=account,
        permissions=permissions
        or ["console:access", "channel:read", "channel:write"],
    )
    get_user_store().create_user(
        account=account,
        display_name=account,
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    client = TestClient(app)
    client.__enter__()
    _login(client, account, "secret")
    return client


@pytest.mark.parametrize(
    ("type_id", "permission", "config", "edited"),
    [
        (
            "transform.code",
            "channel:code_write",
            {"code": "return {'ok': True}"},
            {"code": "return {'ok': False}"},
        ),
        (
            "read.source_query",
            "channel:source_query",
            {"source_id": "src_missing", "sql": "SELECT 1"},
            {"source_id": "src_missing", "sql": "SELECT 2"},
        ),
    ],
)
def test_guarded_node_save_and_publish_permissions(
    client: TestClient,
    type_id: str,
    permission: str,
    config: dict,
    edited: dict,
) -> None:
    account = "writer_" + type_id.replace(".", "_")
    writer = _writer_client(account)
    try:
        created = client.post("/channels", json={"name": type_id, "description": None})
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        graph = _guarded_graph(type_id, config)
        added = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 1, "graph": graph},
        )
        body = assert_problem(added, status=403, code="AUTH_FORBIDDEN")
        assert "Guarded node" in body["detail"]
        assert permission in body["detail"]
        assert writer.get(f"/channels/{channel_id}/draft").json()["draft_revision"] == 1
        saved = client.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 1, "graph": graph},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["draft_revision"] == 2

        refused = writer.post(
            f"/channels/{channel_id}/publish",
            json={"draft_revision": 2},
        )
        body = assert_problem(refused, status=403, code="AUTH_FORBIDDEN")
        assert "Guarded node" in body["detail"]
        published = client.post(
            f"/channels/{channel_id}/publish",
            json={"draft_revision": 2},
        )
        if type_id == "transform.code":
            assert published.status_code == 201, published.text
        else:
            assert_problem(published, status=422, code="CHANNEL_GRAPH_INVALID")

        current = writer.get(f"/channels/{channel_id}/draft").json()
        renamed = current["graph"]
        trigger = next(node for node in renamed["nodes"] if node["id"] == "nd_trigger")
        trigger["name"] = "Start"
        kept = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": renamed},
        )
        assert kept.status_code == 200, kept.text

        current = writer.get(f"/channels/{channel_id}/draft").json()
        changed = current["graph"]
        guard = next(node for node in changed["nodes"] if node["id"] == "nd_guard")
        guard["config"] = edited
        modified = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": changed},
        )
        body = assert_problem(modified, status=403, code="AUTH_FORBIDDEN")
        assert "Guarded node" in body["detail"]
        current = writer.get(f"/channels/{channel_id}/draft").json()
        bumped = current["graph"]
        guard = next(node for node in bumped["nodes"] if node["id"] == "nd_guard")
        guard["type_version"] = 2
        versioned = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": bumped},
        )
        assert_problem(versioned, status=403, code="AUTH_FORBIDDEN")

        current = writer.get(f"/channels/{channel_id}/draft").json()
        removed = current["graph"]
        removed["nodes"] = [
            node for node in removed["nodes"] if node["id"] != "nd_guard"
        ]
        removed["edges"] = []
        deleted = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": removed},
        )
        assert deleted.status_code == 200, deleted.text
        assert all(
            node["id"] != "nd_guard" for node in deleted.json()["graph"]["nodes"]
        )
    finally:
        writer.__exit__(None, None, None)


def _registered_source(client: TestClient, *, key: str, name: str) -> dict:
    created = client.post(
        "/sources",
        json={
            "key": key,
            "name": name,
            "kind": "database",
            "engine": "postgresql",
            "access": {
                "host": "127.0.0.1",
                "port": 5432,
                "username": "u",
                "password": "super-secret-password",
                "ssl_mode": "require",
                "database": "MES",
                "schema": "public",
                "extra": {},
            },
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["source"]


def _sql_source_config(source_id: str, sql: str = "SELECT 1") -> dict:
    return {"source": {"kind": "source", "source_id": source_id}, "sql": sql}


def test_source_access_sql_node_requires_maintainer(client: TestClient) -> None:
    from backend.metadata.source_access import change_level, create_membership

    source = _registered_source(client, key="wh-secret", name="Warehouse secret")
    writer = _writer_client("sql_author")
    user = get_user_store().get_by_account("sql_author")
    assert user is not None
    try:
        created = client.post(
            "/channels", json={"name": "SQL access", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        entity_graph = _guarded_graph(
            "read.sql", {"source": {"kind": "entity"}, "sql": "SELECT 1"}
        )
        entity_saved = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 1, "graph": entity_graph},
        )
        assert entity_saved.status_code == 200, entity_saved.text

        graph = _guarded_graph("read.sql", _sql_source_config(source["id"]))
        refused = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 2, "graph": graph},
        )
        body = assert_problem(refused, status=403, code="AUTH_FORBIDDEN")
        assert body["detail"] == "Node 'Guarded node' requires maintainer on the Source"
        assert source["key"] not in body["detail"]
        assert source["name"] not in body["detail"]
        assert "sources:write" not in body["detail"]
        assert "query:run" not in body["detail"]

        membership = create_membership(
            subject_type="user",
            subject_id=user.id,
            target=source["id"],
            level="viewer",
        )
        viewer = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 2, "graph": graph},
        )
        assert_problem(viewer, status=403, code="AUTH_FORBIDDEN")
        change_level(membership.id, "steward")
        steward = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 2, "graph": graph},
        )
        assert_problem(steward, status=403, code="AUTH_FORBIDDEN")
        change_level(membership.id, "maintainer")
        allowed = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 2, "graph": graph},
        )
        assert allowed.status_code == 200, allowed.text
        stored = allowed.json()["graph"]["nodes"]
        guard = next(node for node in stored if node["id"] == "nd_guard")
        assert guard["config"]["source"]["source_id"] == source["id"]
    finally:
        writer.__exit__(None, None, None)


@pytest.mark.parametrize("type_id", ["read.sql", "volume.dataset_query"])
def test_source_access_changed_source_node_requires_maintainer(
    client: TestClient, type_id: str
) -> None:
    from backend.metadata.source_access import create_membership

    source = _registered_source(client, key=f"key-{type_id}", name=f"Name {type_id}")
    writer = _writer_client("chg_" + type_id.replace(".", "_"))
    user = get_user_store().get_by_account("chg_" + type_id.replace(".", "_"))
    assert user is not None
    try:
        created = client.post(
            "/channels", json={"name": type_id, "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        graph = _guarded_graph(type_id, _sql_source_config(source["id"]))
        saved = client.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 1, "graph": graph},
        )
        assert saved.status_code == 200, saved.text

        current = writer.get(f"/channels/{channel_id}/draft").json()
        renamed = current["graph"]
        trigger = next(node for node in renamed["nodes"] if node["id"] == "nd_trigger")
        trigger["name"] = "Start"
        trigger["position"] = {"x": 12, "y": 4}
        kept = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": renamed},
        )
        assert kept.status_code == 200, kept.text

        current = writer.get(f"/channels/{channel_id}/draft").json()
        changed = current["graph"]
        guard = next(node for node in changed["nodes"] if node["id"] == "nd_guard")
        guard["config"] = _sql_source_config(source["id"], "SELECT 2")
        modified = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": changed},
        )
        body = assert_problem(modified, status=403, code="AUTH_FORBIDDEN")
        assert body["detail"] == "Node 'Guarded node' requires maintainer on the Source"

        current = writer.get(f"/channels/{channel_id}/draft").json()
        bumped = current["graph"]
        guard = next(node for node in bumped["nodes"] if node["id"] == "nd_guard")
        guard["type_version"] = 2
        versioned = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": bumped},
        )
        assert_problem(versioned, status=403, code="AUTH_FORBIDDEN")

        other = "volume.dataset_query" if type_id == "read.sql" else "read.sql"
        current = writer.get(f"/channels/{channel_id}/draft").json()
        retyped = current["graph"]
        guard = next(node for node in retyped["nodes"] if node["id"] == "nd_guard")
        guard["type"] = other
        switched = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": retyped},
        )
        assert_problem(switched, status=403, code="AUTH_FORBIDDEN")

        current = writer.get(f"/channels/{channel_id}/draft").json()
        removed = current["graph"]
        removed["nodes"] = [
            node for node in removed["nodes"] if node["id"] != "nd_guard"
        ]
        removed["edges"] = []
        deleted = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": removed},
        )
        assert deleted.status_code == 200, deleted.text

        create_membership(
            subject_type="user",
            subject_id=user.id,
            target=source["id"],
            level="maintainer",
        )
        again = _guarded_graph(type_id, _sql_source_config(source["id"]))
        current = writer.get(f"/channels/{channel_id}/draft").json()
        restored = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": again},
        )
        assert restored.status_code == 200, restored.text
    finally:
        writer.__exit__(None, None, None)


def test_source_access_live_query_requires_viewer_not_query_run(
    client: TestClient,
) -> None:
    from backend.metadata.source_access import create_membership

    source = _registered_source(client, key="live-key", name="Live name")
    permissions = [
        "console:access",
        "channel:read",
        "channel:write",
        "channel:source_query",
    ]
    writer = _writer_client("live_author", permissions)
    user = get_user_store().get_by_account("live_author")
    assert user is not None
    assert "query:run" not in permissions
    try:
        created = client.post(
            "/channels", json={"name": "Live query", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        graph = _guarded_graph(
            "read.source_query",
            {"source_id": source["id"], "sql": "SELECT 1"},
        )
        refused = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 1, "graph": graph},
        )
        body = assert_problem(refused, status=403, code="AUTH_FORBIDDEN")
        assert body["detail"] == "Node 'Guarded node' requires viewer on the Source"
        assert "query:run" not in body["detail"]
        assert source["key"] not in body["detail"]
        assert source["name"] not in body["detail"]

        create_membership(
            subject_type="user",
            subject_id=user.id,
            target=source["id"],
            level="viewer",
        )
        allowed = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 1, "graph": graph},
        )
        assert allowed.status_code == 200, allowed.text
    finally:
        writer.__exit__(None, None, None)


def test_source_access_publish_checks_every_referenced_source(
    client: TestClient,
) -> None:
    source = _registered_source(client, key="pub-key", name="Publish name")
    writer = _writer_client("publisher")
    try:
        created = client.post(
            "/channels", json={"name": "Publish access", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        graph = _guarded_graph("read.sql", _sql_source_config(source["id"]))
        graph["nodes"].append(
            {
                "id": "nd_entity",
                "ref": "entity_sql",
                "type": "read.sql",
                "name": "Entity SQL",
                "position": {"x": 480, "y": 0},
                "config": {"source": {"kind": "entity"}, "sql": "SELECT 1"},
                "on_error": "stop",
                "retry": None,
            }
        )
        graph["edges"].append(
            {
                "id": "ed_entity",
                "source": {"node_id": "nd_guard", "port": "main"},
                "target": {"node_id": "nd_entity", "port": "main"},
            }
        )
        saved = client.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 1, "graph": graph},
        )
        assert saved.status_code == 200, saved.text
        revision = saved.json()["draft_revision"]
        refused = writer.post(
            f"/channels/{channel_id}/publish",
            json={"draft_revision": revision},
        )
        body = assert_problem(refused, status=403, code="AUTH_FORBIDDEN")
        assert body["detail"] == "Node 'Guarded node' requires maintainer on the Source"
        assert "Entity SQL" not in body["detail"]
        published = client.post(
            f"/channels/{channel_id}/publish",
            json={"draft_revision": revision},
        )
        assert published.status_code == 201, published.text
    finally:
        writer.__exit__(None, None, None)


def test_source_access_reads_hide_inaccessible_source(client: TestClient) -> None:
    from backend.metadata.source_access import create_membership

    source = _registered_source(client, key="hidden-key", name="Hidden name")
    other = _registered_source(client, key="shown-key", name="Shown name")
    reader = _writer_client("channel_reader")
    user = get_user_store().get_by_account("channel_reader")
    assert user is not None
    create_membership(
        subject_type="user",
        subject_id=user.id,
        target=other["id"],
        level="viewer",
    )
    try:
        created = client.post(
            "/channels", json={"name": "Hidden source", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        graph = _guarded_graph("read.sql", _sql_source_config(source["id"]))
        graph["nodes"].append(
            {
                "id": "nd_live",
                "ref": "live_read",
                "type": "read.source_query",
                "name": "Live",
                "position": {"x": 480, "y": 0},
                "config": {"source_id": other["id"], "sql": "SELECT 1"},
                "on_error": "stop",
                "retry": None,
            }
        )
        graph["edges"].append(
            {
                "id": "ed_live",
                "source": {"node_id": "nd_guard", "port": "main"},
                "target": {"node_id": "nd_live", "port": "main"},
            }
        )
        saved = client.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 1, "graph": graph},
        )
        assert saved.status_code == 200, saved.text
        admin_draft = saved.json()
        admin_hidden = next(
            item
            for item in admin_draft["source_displays"]
            if item["source_id"] == source["id"]
        )
        assert admin_hidden["key"] == source["key"]
        assert admin_hidden["name"] == source["name"]
        assert "inaccessible" not in admin_hidden

        opened = reader.get(f"/channels/{channel_id}/draft")
        assert opened.status_code == 200, opened.text
        body = opened.json()
        guard = next(node for node in body["graph"]["nodes"] if node["id"] == "nd_guard")
        assert guard["config"]["source"]["source_id"] == source["id"]
        assert "inaccessible" not in str(body["graph"])
        hidden = next(
            item
            for item in body["source_displays"]
            if item["source_id"] == source["id"]
        )
        shown = next(
            item for item in body["source_displays"] if item["source_id"] == other["id"]
        )
        assert hidden == {"source_id": source["id"], "inaccessible": True}
        assert source["key"] not in hidden
        assert source["name"] not in hidden
        assert shown == {
            "source_id": other["id"],
            "key": other["key"],
            "name": other["name"],
        }
        assert "inaccessible" not in shown

        current = body
        renamed = current["graph"]
        trigger = next(node for node in renamed["nodes"] if node["id"] == "nd_trigger")
        trigger["name"] = "Start"
        kept = reader.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": renamed},
        )
        assert kept.status_code == 200, kept.text
        kept_guard = next(
            node for node in kept.json()["graph"]["nodes"] if node["id"] == "nd_guard"
        )
        assert kept_guard["config"]["source"]["source_id"] == source["id"]
        stored = get_channel_store().get(channel_id)
        assert stored is not None
        stored_guard = next(
            node for node in stored.draft_graph["nodes"] if node["id"] == "nd_guard"
        )
        assert stored_guard["config"]["source"]["source_id"] == source["id"]
        assert "inaccessible" not in str(stored.draft_graph)

        published = client.post(
            f"/channels/{channel_id}/publish",
            json={"draft_revision": kept.json()["draft_revision"]},
        )
        assert published.status_code == 201, published.text
        number = published.json()["version"]["number"]
        version = reader.get(f"/channels/{channel_id}/versions/{number}")
        assert version.status_code == 200, version.text
        version_body = version.json()["version"]
        version_guard = next(
            node
            for node in version_body["graph"]["nodes"]
            if node["id"] == "nd_guard"
        )
        assert version_guard["config"]["source"]["source_id"] == source["id"]
        marker = next(
            item
            for item in version_body["source_displays"]
            if item["source_id"] == source["id"]
        )
        visible = next(
            item
            for item in version_body["source_displays"]
            if item["source_id"] == other["id"]
        )
        assert marker == {"source_id": source["id"], "inaccessible": True}
        assert source["key"] not in marker
        assert source["name"] not in marker
        assert visible["key"] == other["key"]
        assert visible["name"] == other["name"]
    finally:
        reader.__exit__(None, None, None)


def test_source_access_run_stays_on_system_identity(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.admin.user_store import ensure_system_user
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job
    from backend.metadata.query.service import QueryOutcome

    source = _registered_source(client, key="run-key", name="Run name")
    writer = _writer_client("runner")
    actors: list[str | None] = []

    def _query(**kwargs):
        actors.append(kwargs.get("actor_user_id"))
        return QueryOutcome(
            columns=["n"],
            declarations=[],
            rows=[[1]],
            truncated=False,
            duration_ms=1,
        )

    monkeypatch.setattr(
        "backend.channel.nodes.read.source_query.run_controlled_query",
        _query,
    )
    try:
        created = client.post(
            "/channels", json={"name": "System run", "description": None}
        )
        assert created.status_code == 201, created.text
        channel_id = created.json()["channel"]["id"]
        graph = _guarded_graph(
            "read.source_query",
            {"source_id": source["id"], "sql": "SELECT 1"},
        )
        saved = client.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 1, "graph": graph},
        )
        assert saved.status_code == 200, saved.text
        published = client.post(
            f"/channels/{channel_id}/publish",
            json={"draft_revision": saved.json()["draft_revision"]},
        )
        assert published.status_code == 201, published.text
        previous = set_dispatcher(run_job)
        try:
            started = writer.post(
                f"/channels/{channel_id}/runs",
                json={"target": "published"},
            )
        finally:
            set_dispatcher(previous)
        assert started.status_code == 202, started.text
        job_id = started.json()["run"]["job_id"]
        detail = client.get(f"/channels/{channel_id}/runs/{job_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["run"]["status"] == "succeeded"
        system = ensure_system_user(get_user_store())
        assert actors == [system.id]
        assert system.id != get_user_store().get_by_account("runner").id
    finally:
        writer.__exit__(None, None, None)


def _audit_count() -> int:
    total = 0
    cursor: str | None = None
    while True:
        events, cursor = get_audit_store().list_events(limit=200, cursor=cursor)
        total += len(events)
        if cursor is None:
            return total


def _persisted_counts(channel_id: str) -> tuple[int, int, int, int]:
    jobs, job_total = get_job_store().list()
    runs, run_total = get_run_store().list_runs(
        channel_id, status=None, target=None, limit=100, offset=0
    )
    job_ids = {job.id for job in jobs}
    executions = sum(len(get_run_store().list_executions(job_id)) for job_id in job_ids)
    for run in runs:
        if run.job_id not in job_ids:
            executions += len(get_run_store().list_executions(run.job_id))
    return job_total, run_total, executions, _audit_count()


def test_test_run_creates_run_state(client: TestClient) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job

    created = client.post("/channels", json={"name": "Test run", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    draft = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": 1, "graph": TRIGGER_GRAPH},
    )
    assert draft.status_code == 200, draft.text
    before = _persisted_counts(channel_id)
    previous = set_dispatcher(run_job)
    try:
        response = client.post(
            f"/channels/{channel_id}/runs",
            json={"target": "draft", "stop_at_node_id": "nd_trigger"},
        )
    finally:
        set_dispatcher(previous)
    assert response.status_code == 202, response.text
    job_id = response.json()["run"]["job_id"]
    detail = client.get(f"/channels/{channel_id}/runs/{job_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run"]["status"] == "succeeded"
    listed_runs = client.get(f"/channels/{channel_id}/runs")
    assert listed_runs.status_code == 200, listed_runs.text
    listed_run = next(item for item in listed_runs.json()["items"] if item["job_id"] == job_id)
    assert listed_run["nodes"] == [
        {"id": "nd_trigger", "name": "Run manually", "ref": "run_manually"}
    ]
    assert "graph" not in listed_run
    assert "node_executions" not in body
    assert body["node_summaries"] == [
        {
            "node_id": "nd_trigger",
            "execution_count": 1,
            "status_counts": {"succeeded": 1},
        }
    ]
    execution = get_run_store().get_execution(job_id, 1)
    assert execution is not None
    execution.output = {"rows": [{"n": index} for index in range(101)]}
    execution.output_bytes = 1
    get_run_store().finish_execution(execution)
    listed = client.get(f"/channels/{channel_id}/runs/{job_id}/executions")
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert page["total"] == 1
    assert page["limit"] == 50
    assert page["offset"] == 0
    shown = page["items"][0]
    assert len(shown["output_preview"]["rows"]) == 100
    assert shown["output_truncated"] is True
    assert shown["container_seq"] is None
    assert shown["round"] is None
    assert shown["preview_only"] is False
    assert shown["preview_totals"] == {}
    after = _persisted_counts(channel_id)
    assert after[0] == before[0] + 1
    assert after[1] == before[1] + 1
    assert after[2] == before[2] + 1
    assert after[3] == before[3] + 1


def test_run_history_filters_before_paging(client: TestClient) -> None:
    from datetime import timedelta

    from backend.channel.run_store import ChannelRunRecord
    from backend.jobs.store import create_queued_job, mark_failed

    created = client.post("/channels", json={"name": "Filtered history", "description": None})
    channel_id = created.json()["channel"]["id"]
    now = utc_now()
    expected = []
    for index in range(55):
        job = create_queued_job(
            kind="channel_run", input={}, created_at=now + timedelta(seconds=index)
        )
        target = "draft" if index == 1 else "published"
        get_run_store().insert_run(ChannelRunRecord(
            job_id=job.id, channel_id=channel_id, target=target,
            version=None, draft_revision=None, graph=None, trigger_node_id="start",
            ignore_checkpoints=False, outcome=None, failed_node_id=None,
            skipped_node_ids=[], created_at=job.created_at,
        ))
        if index < 3:
            mark_failed(job.id, error_code="CHANNEL_NODE_FAILED", error_summary="Failed")
            if target == "published":
                expected.insert(0, job.id)
    for offset in range(3):
        response = client.get(
            f"/channels/{channel_id}/runs",
            params={"status": "failed", "target": "published", "limit": 1, "offset": offset},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert [run["job_id"] for run in body["items"]] == expected[offset:offset + 1]

    get_job_store().delete(expected[0])
    missing = client.get(f"/channels/{channel_id}/runs/{expected[0]}")
    assert missing.status_code == 404, missing.text
    response = client.get(f"/channels/{channel_id}/runs", params={"status": "failed", "target": "published"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert [run["job_id"] for run in response.json()["items"]] == expected[1:]


def test_execution_list_filters_pages_and_requires_read(client: TestClient) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job

    created = client.post("/channels", json={"name": "Paged runs", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": 1, "graph": TRIGGER_GRAPH},
    )
    assert saved.status_code == 200, saved.text
    previous = set_dispatcher(run_job)
    try:
        started = client.post(f"/channels/{channel_id}/runs", json={"target": "draft"})
    finally:
        set_dispatcher(previous)
    assert started.status_code == 202, started.text
    job_id = started.json()["run"]["job_id"]
    store = get_run_store()
    failed = store.start_execution(job_id, "nd_step", container_seq=1, round=0)
    failed.status = "failed"
    failed.finished_at = utc_now()
    failed.output = {"n": 1}
    failed.output_bytes = 1
    failed.error_code = "CHANNEL_NODE_FAILED"
    failed.error_message = "nope"
    store.finish_execution(failed)
    preview = store.start_execution(job_id, "nd_step", container_seq=1, round=1)
    preview.status = "succeeded"
    preview.finished_at = utc_now()
    preview.output = {"rows": [{"n": 1}]}
    preview.output_bytes = 4
    preview.preview_only = True
    preview.preview_totals = {"rows": 1000000}
    store.finish_execution(preview)
    running = store.start_execution(job_id, "nd_step", container_seq=1, round=2)

    detail = client.get(f"/channels/{channel_id}/runs/{job_id}")
    assert detail.status_code == 200, detail.text
    assert "node_executions" not in detail.json()
    assert detail.json()["node_summaries"] == [
        {
            "node_id": "nd_trigger",
            "execution_count": 1,
            "status_counts": {"succeeded": 1},
        },
        {
            "node_id": "nd_step",
            "execution_count": 3,
            "status_counts": {"failed": 1, "succeeded": 1, "running": 1},
        },
    ]

    steps = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"node_id": "nd_step", "container_seq": 1},
    )
    assert steps.status_code == 200, steps.text
    step_page = steps.json()
    assert step_page["total"] == 3
    assert [item["seq"] for item in step_page["items"]] == [2, 3, 4]
    assert [item["round"] for item in step_page["items"]] == [0, 1, 2]
    shown = step_page["items"][1]
    assert shown["preview_only"] is True
    assert shown["preview_totals"] == {"rows": 1000000}
    assert shown["container_seq"] == 1
    assert shown["status"] == "succeeded"

    one_round = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"round": 0, "status": "failed"},
    )
    assert one_round.json()["total"] == 1
    assert one_round.json()["items"][0]["seq"] == 2
    assert one_round.json()["items"][0]["error_code"] == "CHANNEL_NODE_FAILED"

    first = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"limit": 1, "offset": 0},
    )
    assert first.json()["items"][0]["seq"] == 1
    assert first.json()["total"] == 4
    assert first.json()["limit"] == 1
    second = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"limit": 1, "offset": 1},
    )
    assert second.json()["items"][0]["seq"] == 2
    past = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"offset": 4},
    )
    assert past.json()["items"] == []
    assert past.json()["total"] == 4
    assert past.json()["limit"] == 50
    empty = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"node_id": "nd_missing"},
    )
    assert empty.json()["items"] == []
    assert empty.json()["total"] == 0

    invalid = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"status": "nope"},
    )
    assert_problem(invalid, status=422, code="REQUEST_INVALID")
    missing = client.get(f"/channels/{channel_id}/runs/job_missing/executions")
    assert_problem(missing, status=404, code="CHANNEL_RUN_NOT_FOUND")
    other = client.get(f"/channels/chn_other/runs/{job_id}")
    assert_problem(other, status=404, code="CHANNEL_RUN_NOT_FOUND")

    role = create_role(
        get_role_store(),
        key="plain_user",
        name="Plain user",
        permissions=["console:access"],
    )
    get_user_store().create_user(
        account="plain",
        display_name="Plain",
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    reader = create_role(
        get_role_store(),
        key="channel_reader",
        name="Channel reader",
        permissions=["console:access", "channel:read"],
    )
    get_user_store().create_user(
        account="reader",
        display_name="Reader",
        password_hash=hash_password("secret"),
        role_id=reader.id,
        status="active",
    )
    rows = f"/channels/{channel_id}/runs/{job_id}/datasets/dmissing/rows"
    with TestClient(app) as plain:
        _login(plain, "plain", "secret")
        assert plain.get(f"/channels/{channel_id}/runs/{job_id}").status_code == 403
        assert (
            plain.get(f"/channels/{channel_id}/runs/{job_id}/executions").status_code
            == 403
        )
        assert plain.get(rows).status_code == 403
        assert (
            plain.get(
                f"/channels/{channel_id}/runs/{job_id}/executions/1/rounds"
            ).status_code
            == 403
        )
    with TestClient(app) as allowed:
        _login(allowed, "reader", "secret")
        assert allowed.get(f"/channels/{channel_id}/runs/{job_id}").status_code == 200
        assert (
            allowed.get(f"/channels/{channel_id}/runs/{job_id}/executions").status_code
            == 200
        )
        assert_problem(
            allowed.get(f"/channels/{channel_id}/runs/{job_id}/executions/1/rounds"),
            status=422,
            code="REQUEST_INVALID",
            detail="Execution is not a container",
        )
    assert running.status == "running"


def _api_node(
    node_id: str,
    type_id: str,
    name: str,
    config: dict,
    y: int,
    *,
    parent: str | None = None,
) -> dict:
    node = {
        "id": node_id,
        "ref": node_id.removeprefix("nd_"),
        "type": type_id,
        "name": name,
        "position": {"x": 0, "y": y},
        "config": config,
        "on_error": "stop",
        "retry": None,
    }
    if parent is not None:
        node["parent"] = parent
    return node


def _api_edge(
    edge_id: str, source: str, target: str, *, source_port: str = "main"
) -> dict:
    return {
        "id": edge_id,
        "source": {"node_id": source, "port": source_port},
        "target": {"node_id": target, "port": "main"},
    }


def _settings() -> dict:
    return {"run_timeout_sec": None, "error_channel_id": None}


def _run_draft(client: TestClient, channel_id: str, graph: dict) -> str:
    from backend.channel.channel_run import set_dispatcher
    from backend.channel.tasks import run_job

    _save_draft(client, channel_id, graph)
    previous = set_dispatcher(run_job)
    try:
        started = client.post(f"/channels/{channel_id}/runs", json={"target": "draft"})
    finally:
        set_dispatcher(previous)
    assert started.status_code == 202, started.text
    return started.json()["run"]["job_id"]


def test_execution_list_includes_rendered_input(
    client: TestClient, monkeypatch
) -> None:
    import json

    monkeypatch.setattr(
        "backend.channel.nodes.read.sql.run_channel_sql",
        lambda statement, **kwargs: {"rows": [{"n": 1}], "count": 1, "rowcount": 1},
    )
    created = client.post(
        "/channels", json={"name": "Rendered input", "description": None}
    )
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    numbers = list(range(101))
    graph = {
        "nodes": [
            _api_node("nd_trigger", "trigger.manual", "Run", {}, 0),
            _api_node(
                "nd_sql",
                "read.sql",
                "SQL",
                {"source": {"kind": "entity"}, "sql": "select {{ 1 }}"},
                1,
            ),
            _api_node(
                "nd_fields",
                "transform.set_fields",
                "Fields",
                {
                    "fields": [
                        {"name": "total", "value": "{{ 2 + 3 }}"},
                        {"name": "label", "value": '"ok"'},
                        {"name": "nums", "value": json.dumps(numbers)},
                        {"name": "box", "value": json.dumps({"nums": numbers})},
                    ]
                },
                2,
            ),
        ],
        "edges": [
            _api_edge("ed_sql", "nd_trigger", "nd_sql"),
            _api_edge("ed_fields", "nd_sql", "nd_fields"),
        ],
        "settings": _settings(),
    }
    job_id = _run_draft(client, channel_id, graph)
    listed = client.get(f"/channels/{channel_id}/runs/{job_id}/executions")
    assert listed.status_code == 200, listed.text
    by_node = {item["node_id"]: item for item in listed.json()["items"]}
    assert by_node["nd_trigger"]["input_preview"] == {}
    assert by_node["nd_trigger"]["input_truncated"] is False
    assert by_node["nd_trigger"]["input_totals"] == {}
    assert by_node["nd_sql"]["input_preview"] == {"sql": {"value": "select 1"}}
    assert by_node["nd_sql"]["input_truncated"] is False
    assert by_node["nd_sql"]["input_totals"] == {}
    fields = by_node["nd_fields"]
    assert fields["input_preview"]["fields.0.value"] == {"value": 5}
    assert fields["input_preview"]["fields.1.value"] == {"value": "ok"}
    assert fields["input_preview"]["fields.2.value"]["value"] == list(range(100))
    assert fields["input_preview"]["fields.3.value"]["value"]["nums"] == list(
        range(100)
    )
    assert fields["input_truncated"] is True
    assert fields["input_totals"] == {"fields.2.value": 101, "fields.3.value.nums": 101}
    assert fields["preview_only"] is False
    stored = get_run_store().get_execution(job_id, fields["seq"])
    assert stored is not None
    assert len(stored.input["fields.2.value"]["value"]) == 100
    assert len(stored.output["nums"]) == 101
    assert len(stored.output["box"]["nums"]) == 101


def test_execution_records_a_render_error(client: TestClient) -> None:
    created = client.post(
        "/channels", json={"name": "Render error", "description": None}
    )
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    graph = {
        "nodes": [
            _api_node("nd_trigger", "trigger.manual", "Run", {}, 0),
            _api_node("nd_gate", "transform.if", "Gate", {"condition": "{{ 1 }}"}, 1),
        ],
        "edges": [_api_edge("ed_gate", "nd_trigger", "nd_gate")],
        "settings": _settings(),
    }
    job_id = _run_draft(client, channel_id, graph)
    listed = client.get(f"/channels/{channel_id}/runs/{job_id}/executions")
    assert listed.status_code == 200, listed.text
    gate = next(item for item in listed.json()["items"] if item["node_id"] == "nd_gate")
    assert gate["status"] == "failed"
    assert gate["error_code"] == "CHANNEL_VALUE_TYPE_MISMATCH"
    assert gate["input_preview"] == {
        "condition": {
            "error": {
                "code": "CHANNEL_VALUE_TYPE_MISMATCH",
                "message": "Value does not match the declared type",
            }
        }
    }
    assert gate["input_truncated"] is False
    assert gate["input_totals"] == {}


def test_container_rounds_page_and_reject_a_non_container(client: TestClient) -> None:
    created = client.post("/channels", json={"name": "Rounds", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    graph = {
        "nodes": [
            _api_node("nd_trigger", "trigger.manual", "Run", {}, 0),
            _api_node("nd_walk", "volume.for", "Walk", {"items": "[1, 2, 3]"}, 1),
            _api_node(
                "nd_step",
                "transform.set_fields",
                "Step",
                {"fields": [{"name": "n", "value": "1"}]},
                2,
                parent="nd_walk",
            ),
            _api_node(
                "nd_tail",
                "transform.set_fields",
                "Tail",
                {"fields": [{"name": "n", "value": "2"}]},
                3,
                parent="nd_walk",
            ),
            _api_node(
                "nd_after",
                "transform.set_fields",
                "After",
                {"fields": [{"name": "n", "value": "3"}]},
                4,
            ),
        ],
        "edges": [
            _api_edge("ed_in", "nd_trigger", "nd_walk"),
            _api_edge("ed_each", "nd_walk", "nd_step", source_port="each"),
            _api_edge("ed_tail", "nd_step", "nd_tail"),
            _api_edge("ed_done", "nd_walk", "nd_after", source_port="done"),
        ],
        "settings": _settings(),
    }
    job_id = _run_draft(client, channel_id, graph)
    listed = client.get(f"/channels/{channel_id}/runs/{job_id}/executions")
    assert listed.status_code == 200, listed.text
    by_node = {item["node_id"]: item for item in listed.json()["items"]}
    walk_seq = by_node["nd_walk"]["seq"]
    rounds = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions/{walk_seq}/rounds"
    )
    assert rounds.status_code == 200, rounds.text
    body = rounds.json()
    assert body["total"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["items"] == [
        {
            "round": index,
            "step_preview": {"current": index + 1, "index": index, "count": 3},
            "step_truncated": False,
            "step_totals": {},
            "status_counts": {"succeeded": 2},
        }
        for index in range(3)
    ]
    assert by_node["nd_walk"]["input_preview"] == {"items": {"value": [1, 2, 3]}}
    assert by_node["nd_walk"]["input_totals"] == {"items": 3}
    second = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions/{walk_seq}/rounds",
        params={"limit": 1, "offset": 1},
    )
    assert second.status_code == 200, second.text
    assert second.json()["total"] == 3
    assert second.json()["limit"] == 1
    assert second.json()["offset"] == 1
    assert second.json()["items"] == [
        {
            "round": 1,
            "step_preview": {"current": 2, "index": 1, "count": 3},
            "step_truncated": False,
            "step_totals": {},
            "status_counts": {"succeeded": 2},
        }
    ]
    past = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions/{walk_seq}/rounds",
        params={"offset": 3},
    )
    assert past.json()["items"] == []
    assert past.json()["total"] == 3
    assert past.json()["limit"] == 50
    assert past.json()["offset"] == 3
    empty_graph = {
        "nodes": [
            _api_node("nd_trigger", "trigger.manual", "Run", {}, 0),
            _api_node("nd_walk", "volume.for", "Walk", {"items": "[1]"}, 1),
            _api_node(
                "nd_after",
                "transform.set_fields",
                "After",
                {"fields": [{"name": "n", "value": "1"}]},
                2,
            ),
        ],
        "edges": [
            _api_edge("ed_in", "nd_trigger", "nd_walk"),
            _api_edge("ed_done", "nd_walk", "nd_after", source_port="done"),
        ],
        "settings": _settings(),
    }
    empty_job = _run_draft(client, channel_id, empty_graph)
    empty_listed = client.get(f"/channels/{channel_id}/runs/{empty_job}/executions")
    assert empty_listed.status_code == 200, empty_listed.text
    empty_walk = next(
        item for item in empty_listed.json()["items"] if item["node_id"] == "nd_walk"
    )
    empty_rounds = client.get(
        f"/channels/{channel_id}/runs/{empty_job}/executions/{empty_walk['seq']}/rounds"
    )
    assert empty_rounds.status_code == 200, empty_rounds.text
    assert empty_rounds.json()["total"] == 1
    assert empty_rounds.json()["items"][0]["status_counts"] == {}
    assert empty_rounds.json()["items"][0]["round"] == 0
    assert_problem(
        client.get(
            f"/channels/{channel_id}/runs/{job_id}/executions/{walk_seq}/rounds",
            params={"limit": 201},
        ),
        status=422,
        code="REQUEST_INVALID",
    )
    assert_problem(
        client.get(
            f"/channels/{channel_id}/runs/{job_id}/executions/{by_node['nd_trigger']['seq']}/rounds"
        ),
        status=422,
        code="REQUEST_INVALID",
        detail="Execution is not a container",
    )
    assert_problem(
        client.get(
            f"/channels/{channel_id}/runs/{job_id}/executions/{by_node['nd_step']['seq']}/rounds"
        ),
        status=422,
        code="REQUEST_INVALID",
        detail="Execution is not a container",
    )
    assert_problem(
        client.get(f"/channels/{channel_id}/runs/{job_id}/executions/99/rounds"),
        status=404,
        code="CHANNEL_RUN_NOT_FOUND",
    )
    assert_problem(
        client.get(f"/channels/{channel_id}/runs/job_missing/executions/1/rounds"),
        status=404,
        code="CHANNEL_RUN_NOT_FOUND",
    )


def test_rerun_pins_a_failed_published_version(client: TestClient) -> None:
    from backend.channel.channel_run import set_dispatcher
    from backend.jobs.store import mark_failed

    previous = set_dispatcher(lambda _job_id: None)
    try:
        created = client.post("/channels", json={"name": "Rerun", "description": None})
        assert created.status_code == 201, created.text
        assert created.json()["channel"]["failure_streak"] == 0
        assert created.json()["channel"]["persistently_failing"] is False
        channel_id = created.json()["channel"]["id"]
        saved = client.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": 1, "graph": TRIGGER_GRAPH},
        )
        assert saved.status_code == 200, saved.text
        published = client.post(
            f"/channels/{channel_id}/publish",
            json={"draft_revision": saved.json()["draft_revision"]},
        )
        assert published.status_code == 201, published.text
        started = client.post(
            f"/channels/{channel_id}/runs", json={"target": "published"}
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["run"]["job_id"]
        assert mark_failed(
            job_id, error_code="CHANNEL_NODE_FAILED", error_summary="failed"
        )
        rerun = client.post(f"/channels/{channel_id}/runs/{job_id}/rerun")
        assert rerun.status_code == 202, rerun.text
        body = rerun.json()["run"]
        assert body["job_id"] != job_id
        assert body["target"] == "published"
        assert body["version"] == 1
        assert body["trigger_kind"] == "user"
        queued = get_job_store().get(body["job_id"])
        assert queued is not None
        assert queued.input["pin_version"] is True
        assert queued.input["version"] == 1
        assert "retry_of_job_id" not in queued.input
        events, _cursor = get_audit_store().list_events(limit=50, cursor=None)
        assert any(event.action == "channel.rerun_enqueue" for event in events)
        draft = client.post(f"/channels/{channel_id}/runs", json={"target": "draft"})
        assert draft.status_code == 202, draft.text
        draft_id = draft.json()["run"]["job_id"]
        assert mark_failed(
            draft_id, error_code="CHANNEL_NODE_FAILED", error_summary="failed"
        )
        refused = client.post(f"/channels/{channel_id}/runs/{draft_id}/rerun")
        assert_problem(refused, status=422, code="CHANNEL_RUN_NOT_RERUNNABLE")
    finally:
        set_dispatcher(previous)


def test_channel_reader_reads_site_capacity_without_settings_read() -> None:
    from backend.channel.dataset_registry import reset_dataset_store

    reset_dataset_store()
    roles = get_role_store()
    seed_roles(roles)
    role = create_role(
        roles,
        key="capacity_reader",
        name="Capacity reader",
        permissions=["console:access", "channel:read"],
    )
    get_user_store().create_user(
        account="capacity_reader",
        display_name="Capacity reader",
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    with TestClient(app) as reader:
        _login(reader, "capacity_reader", "secret")
        response = reader.get("/channel-dataset-capacity")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "used_bytes": 0,
        "ceiling_bytes": 107374182400,
    }


def test_capacity_sums_loading_and_ready_including_an_empty_table(
    client: TestClient,
) -> None:
    from backend.channel.dataset_registry import (
        DatasetRecord,
        get_dataset_store,
        reset_dataset_store,
    )

    reset_dataset_store()
    store = get_dataset_store()
    store.save(
        _capacity_row("dst_ready_empty", status="ready", size_bytes=10, row_count=0)
    )
    store.save(_capacity_row("dst_loading", status="loading", size_bytes=5, row_count=0))
    store.save(_capacity_row("dst_dropped", status="dropped", size_bytes=100, row_count=4))
    store.save(_capacity_row("dst_lost", status="lost", size_bytes=7, row_count=0))

    response = client.get("/channel-dataset-capacity")
    assert response.status_code == 200, response.text
    assert response.json()["used_bytes"] == 15
    assert response.json()["ceiling_bytes"] == 107374182400
    assert set(response.json()) == {"used_bytes", "ceiling_bytes"}


def test_capacity_ceiling_follows_a_later_parameter_edit(client: TestClient) -> None:
    from backend.channel.dataset_registry import reset_dataset_store

    reset_dataset_store()
    before = client.get("/channel-dataset-capacity")
    assert before.status_code == 200, before.text
    assert before.json()["ceiling_bytes"] == 107374182400
    patched = client.patch(
        "/settings",
        json={"values": {"channel_dataset_max_total_gb": 2}},
    )
    assert patched.status_code == 200, patched.text
    after = client.get("/channel-dataset-capacity")
    assert after.status_code == 200, after.text
    assert after.json() == {"used_bytes": 0, "ceiling_bytes": 2147483648}


def test_capacity_returns_unclamped_overshoot_and_leaves_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.channel.dataset_registry import (
        DatasetQuotaExceeded,
        DatasetRegistry,
        get_dataset_store,
        reset_dataset_store,
    )

    reset_dataset_store()
    store = get_dataset_store()
    store.save(
        _capacity_row("dst_over", status="ready", size_bytes=107374182410, row_count=0)
    )
    store.save(_capacity_row("dst_dropped", status="dropped", size_bytes=3, row_count=1))

    response = client.get("/channel-dataset-capacity")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "used_bytes": 107374182410,
        "ceiling_bytes": 107374182400,
    }
    over = store.get("dst_over")
    dropped = store.get("dst_dropped")
    assert over is not None
    assert over.status == "ready"
    assert over.size_bytes == 107374182410
    assert over.row_count == 0
    assert dropped is not None
    assert dropped.status == "dropped"
    assert dropped.size_bytes == 3

    def forbid(relation: str, query: str) -> tuple[int, int]:
        raise AssertionError(f"table create {relation} {query}")

    monkeypatch.setattr(
        "backend.channel.dataset_registry.create_table_from_query", forbid
    )
    with pytest.raises(DatasetQuotaExceeded) as caught:
        DatasetRegistry(store).create_from_query(
            job_id="job_1",
            node_id="node_2",
            seq=2,
            query="SELECT 1 AS n",
        )
    assert caught.value.code == "CHANNEL_DATASET_QUOTA_EXCEEDED"
    assert store.get("dst_over") is not None
    assert store.get("dst_dropped") is not None


def test_dataset_capacity_requires_a_session() -> None:
    with TestClient(app) as anon:
        response = anon.get("/channel-dataset-capacity")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_dataset_capacity_refuses_without_channel_read() -> None:
    roles = get_role_store()
    seed_roles(roles)
    role = create_role(
        roles,
        key="capacity_denied",
        name="Capacity denied",
        permissions=["console:access", "settings:read"],
    )
    get_user_store().create_user(
        account="capacity_denied",
        display_name="Capacity denied",
        password_hash=hash_password("secret"),
        role_id=role.id,
        status="active",
    )
    with TestClient(app) as denied:
        _login(denied, "capacity_denied", "secret")
        response = denied.get("/channel-dataset-capacity")
    assert_problem(response, status=403, code="AUTH_FORBIDDEN")


def _capacity_row(
    dataset_id: str, *, status: str, size_bytes: int, row_count: int
) -> "DatasetRecord":
    from backend.channel.dataset_registry import DatasetRecord

    return DatasetRecord(
        id=dataset_id,
        job_id="job_capacity",
        node_id="node_capacity",
        seq=1,
        relation=f"channel_dataset.ds_{dataset_id}",
        columns=[],
        row_count=row_count,
        size_bytes=size_bytes,
        status=status,
        created_at=utc_now(),
    )


def test_channel_datasets_pages_loading_and_ready_largest_first(
    client: TestClient,
) -> None:
    from datetime import datetime, timedelta, timezone

    from backend.channel.dataset_registry import get_dataset_store, reset_dataset_store
    from backend.channel.run_store import ChannelRunRecord

    reset_dataset_store()
    created = client.post(
        "/channels", json={"name": "Order sync", "description": None}
    )
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    job_id = "job_page"
    get_run_store().insert_run(
        ChannelRunRecord(
            job_id=job_id,
            channel_id=channel_id,
            target="published",
            version=1,
            draft_revision=None,
            graph={
                "nodes": [
                    {"id": "n_query", "name": "Query orders"},
                    {"id": "n_blank"},
                ],
                "edges": [],
            },
            trigger_node_id="n_query",
            ignore_checkpoints=False,
            outcome=None,
            failed_node_id=None,
            skipped_node_ids=[],
            created_at=datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc),
        )
    )
    early = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)
    middle = datetime(2026, 11, 4, 2, 0, tzinfo=timezone.utc)
    late = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)
    store = get_dataset_store()
    store.save(
        _usage_row(
            "ds_big",
            job_id=job_id,
            node_id="n_query",
            status="ready",
            size_bytes=300,
            row_count=120000,
            created_at=early,
            expires_at=early + timedelta(days=1),
        )
    )
    store.save(
        _usage_row(
            "ds_mid_late",
            job_id=job_id,
            node_id="n_query",
            status="ready",
            size_bytes=200,
            row_count=2,
            created_at=late,
            expires_at=late,
        )
    )
    store.save(
        _usage_row(
            "ds_mid_early",
            job_id=job_id,
            node_id="n_query",
            status="ready",
            size_bytes=200,
            row_count=1,
            created_at=middle,
            expires_at=middle,
        )
    )
    store.save(
        _usage_row(
            "ds_tie_a",
            job_id=job_id,
            node_id="n_query",
            status="ready",
            size_bytes=100,
            row_count=1,
            created_at=early,
            expires_at=early,
        )
    )
    store.save(
        _usage_row(
            "ds_tie_b",
            job_id=job_id,
            node_id="n_query",
            status="ready",
            size_bytes=100,
            row_count=1,
            created_at=early,
            expires_at=early,
        )
    )
    store.save(
        _usage_row(
            "ds_loading",
            job_id=job_id,
            node_id="n_blank",
            status="loading",
            size_bytes=50,
            row_count=0,
            created_at=early,
            expires_at=None,
        )
    )
    store.save(
        _usage_row(
            "ds_dropped",
            job_id=job_id,
            node_id="n_query",
            status="dropped",
            size_bytes=999,
            row_count=9,
            created_at=late,
            expires_at=late,
        )
    )
    store.save(
        _usage_row(
            "ds_lost",
            job_id=job_id,
            node_id="n_query",
            status="lost",
            size_bytes=888,
            row_count=8,
            created_at=late,
            expires_at=late,
        )
    )

    response = client.get("/channel-datasets")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 6
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [
        "ds_big",
        "ds_mid_late",
        "ds_mid_early",
        "ds_tie_b",
        "ds_tie_a",
        "ds_loading",
    ]
    assert body["items"][0] == {
        "id": "ds_big",
        "job_id": job_id,
        "channel_id": channel_id,
        "channel_name": "Order sync",
        "node_id": "n_query",
        "node_name": "Query orders",
        "status": "ready",
        "size_bytes": 300,
        "row_count": 120000,
        "created_at": "2026-11-04T01:00:00Z",
        "expires_at": "2026-11-05T01:00:00Z",
    }
    assert body["items"][5] == {
        "id": "ds_loading",
        "job_id": job_id,
        "channel_id": channel_id,
        "channel_name": "Order sync",
        "node_id": "n_blank",
        "node_name": "n_blank",
        "status": "loading",
        "size_bytes": 50,
        "row_count": 0,
        "created_at": "2026-11-04T01:00:00Z",
        "expires_at": None,
    }
    assert "relation" not in body["items"][0]
    assert "columns" not in body["items"][0]
    assert "seq" not in body["items"][0]


def test_channel_datasets_keeps_rows_when_the_channel_or_run_is_gone(
    client: TestClient,
) -> None:
    from datetime import datetime, timezone

    from backend.channel.dataset_registry import get_dataset_store, reset_dataset_store
    from backend.channel.run_store import ChannelRunRecord

    reset_dataset_store()
    created = client.post(
        "/channels", json={"name": "Order sync", "description": None}
    )
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    kept = datetime(2026, 11, 4, 1, 12, tzinfo=timezone.utc)
    store = get_dataset_store()
    runs = get_run_store()

    def insert(job_id: str, graph: dict | None) -> None:
        runs.insert_run(
            ChannelRunRecord(
                job_id=job_id,
                channel_id=channel_id,
                target="published",
                version=1,
                draft_revision=None,
                graph=graph,
                trigger_node_id="n_query",
                ignore_checkpoints=False,
                outcome=None,
                failed_node_id=None,
                skipped_node_ids=[],
                created_at=kept,
            )
        )

    insert("job_named", {"nodes": [{"id": "n_query", "name": "Query orders"}], "edges": []})
    insert("job_blank_name", {"nodes": [{"id": "n_query", "name": ""}], "edges": []})
    insert("job_no_graph", None)
    insert("job_gone", {"nodes": [{"id": "n_query", "name": "Query orders"}], "edges": []})
    store.save(
        _usage_row(
            "ds_named",
            job_id="job_named",
            node_id="n_query",
            status="ready",
            size_bytes=40,
            row_count=3,
            created_at=kept,
            expires_at=kept,
        )
    )
    store.save(
        _usage_row(
            "ds_blank_name",
            job_id="job_blank_name",
            node_id="n_query",
            status="ready",
            size_bytes=30,
            row_count=1,
            created_at=kept,
            expires_at=kept,
        )
    )
    store.save(
        _usage_row(
            "ds_no_graph",
            job_id="job_no_graph",
            node_id="n_query",
            status="loading",
            size_bytes=20,
            row_count=0,
            created_at=kept,
            expires_at=None,
        )
    )
    store.save(
        _usage_row(
            "ds_gone",
            job_id="job_gone",
            node_id="n_query",
            status="ready",
            size_bytes=10,
            row_count=4,
            created_at=kept,
            expires_at=kept,
        )
    )
    deleted = client.delete(f"/channels/{channel_id}")
    assert deleted.status_code == 204, deleted.text
    runs.delete_run("job_gone")

    response = client.get("/channel-datasets")
    assert response.status_code == 200, response.text
    by_id = {item["id"]: item for item in response.json()["items"]}
    assert set(by_id) == {"ds_named", "ds_blank_name", "ds_no_graph", "ds_gone"}
    assert by_id["ds_named"]["channel_id"] == channel_id
    assert by_id["ds_named"]["channel_name"] == channel_id
    assert by_id["ds_named"]["node_name"] == "Query orders"
    assert by_id["ds_blank_name"]["channel_id"] == channel_id
    assert by_id["ds_blank_name"]["node_name"] == "n_query"
    assert by_id["ds_no_graph"]["channel_id"] == channel_id
    assert by_id["ds_no_graph"]["node_name"] == "n_query"
    assert by_id["ds_gone"]["channel_id"] is None
    assert by_id["ds_gone"]["channel_name"] == ""
    assert by_id["ds_gone"]["node_name"] == "n_query"


def test_channel_datasets_read_does_not_change_rows(client: TestClient) -> None:
    from datetime import datetime, timezone

    from backend.channel.dataset_registry import get_dataset_store, reset_dataset_store

    reset_dataset_store()
    kept = datetime(2026, 11, 4, 1, 12, tzinfo=timezone.utc)
    store = get_dataset_store()
    store.save(
        _usage_row(
            "ds_loading",
            job_id="job_usage",
            node_id="n_query",
            status="loading",
            size_bytes=50,
            row_count=0,
            created_at=kept,
            expires_at=None,
        )
    )
    store.save(
        _usage_row(
            "ds_dropped",
            job_id="job_usage",
            node_id="n_query",
            status="dropped",
            size_bytes=9,
            row_count=2,
            created_at=kept,
            expires_at=kept,
        )
    )
    before = {
        "ds_loading": store.get("ds_loading"),
        "ds_dropped": store.get("ds_dropped"),
    }
    response = client.get("/channel-datasets")
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["id"] == "ds_loading"
    assert "CHANNEL_DATASET_QUOTA_EXCEEDED" not in response.text
    after_loading = store.get("ds_loading")
    after_dropped = store.get("ds_dropped")
    assert after_loading == before["ds_loading"]
    assert after_dropped == before["ds_dropped"]
    assert after_loading is not None
    assert after_loading.status == "loading"
    assert after_loading.size_bytes == 50
    assert after_loading.row_count == 0
    assert after_loading.expires_at is None
    assert after_dropped is not None
    assert after_dropped.status == "dropped"


def test_channel_datasets_echoes_the_page_and_rejects_out_of_range(
    client: TestClient,
) -> None:
    from datetime import datetime, timezone

    from backend.channel.dataset_registry import get_dataset_store, reset_dataset_store

    reset_dataset_store()
    kept = datetime(2026, 11, 4, 1, 12, tzinfo=timezone.utc)
    store = get_dataset_store()
    store.save(
        _usage_row(
            "ds_large",
            job_id="job_usage",
            node_id="n_query",
            status="ready",
            size_bytes=20,
            row_count=1,
            created_at=kept,
            expires_at=None,
        )
    )
    store.save(
        _usage_row(
            "ds_small",
            job_id="job_usage",
            node_id="n_query",
            status="ready",
            size_bytes=10,
            row_count=1,
            created_at=kept,
            expires_at=None,
        )
    )
    first = client.get("/channel-datasets", params={"limit": 1, "offset": 0})
    assert first.status_code == 200, first.text
    assert first.json() == {
        "items": [
            {
                "id": "ds_large",
                "job_id": "job_usage",
                "channel_id": None,
                "channel_name": "",
                "node_id": "n_query",
                "node_name": "n_query",
                "status": "ready",
                "size_bytes": 20,
                "row_count": 1,
                "created_at": "2026-11-04T01:12:00Z",
                "expires_at": None,
            }
        ],
        "total": 2,
        "limit": 1,
        "offset": 0,
    }
    past = client.get("/channel-datasets", params={"offset": 5})
    assert past.status_code == 200, past.text
    assert past.json()["items"] == []
    assert past.json()["total"] == 2
    assert past.json()["limit"] == 50
    assert past.json()["offset"] == 5
    assert_problem(
        client.get("/channel-datasets", params={"limit": 201}),
        status=422,
        code="REQUEST_INVALID",
    )
    assert_problem(
        client.get("/channel-datasets", params={"offset": -1}),
        status=422,
        code="REQUEST_INVALID",
    )
    assert_problem(
        client.get("/channel-datasets", params={"limit": 0}),
        status=422,
        code="REQUEST_INVALID",
    )


def test_channel_datasets_requires_channel_read() -> None:
    from backend.channel.dataset_registry import reset_dataset_store

    reset_dataset_store()
    with TestClient(app) as anon:
        anonymous = anon.get("/channel-datasets")
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "AUTH_UNAUTHENTICATED"

    roles = get_role_store()
    seed_roles(roles)
    denied_role = create_role(
        roles,
        key="dataset_list_denied",
        name="Dataset list denied",
        permissions=["console:access", "settings:read"],
    )
    get_user_store().create_user(
        account="dataset_list_denied",
        display_name="Dataset list denied",
        password_hash=hash_password("secret"),
        role_id=denied_role.id,
        status="active",
    )
    reader_role = create_role(
        roles,
        key="dataset_list_reader",
        name="Dataset list reader",
        permissions=["console:access", "channel:read"],
    )
    get_user_store().create_user(
        account="dataset_list_reader",
        display_name="Dataset list reader",
        password_hash=hash_password("secret"),
        role_id=reader_role.id,
        status="active",
    )
    with TestClient(app) as denied:
        _login(denied, "dataset_list_denied", "secret")
        refused = denied.get("/channel-datasets")
    assert_problem(refused, status=403, code="AUTH_FORBIDDEN")
    with TestClient(app) as reader:
        _login(reader, "dataset_list_reader", "secret")
        allowed = reader.get("/channel-datasets")
    assert allowed.status_code == 200, allowed.text
    assert allowed.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def _usage_row(
    dataset_id: str,
    *,
    job_id: str,
    node_id: str,
    status: str,
    size_bytes: int,
    row_count: int,
    created_at: "datetime",
    expires_at: "datetime | None",
) -> "DatasetRecord":
    from backend.channel.dataset_registry import DatasetRecord

    return DatasetRecord(
        id=dataset_id,
        job_id=job_id,
        node_id=node_id,
        seq=7,
        relation=f"channel_dataset.{dataset_id}",
        columns=[{"name": "n", "type": "int8"}],
        row_count=row_count,
        size_bytes=size_bytes,
        status=status,
        created_at=created_at,
        expires_at=expires_at,
    )
