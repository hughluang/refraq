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
        "trigger.manual",
        "trigger.scheduled",
        "read.source_query",
        "read.sql",
        "transform.code",
        "transform.deduplicate",
        "transform.filter",
        "transform.if",
        "transform.merge",
        "transform.set_fields",
        "volume.batch_read",
        "volume.dataset_query",
        "volume.for",
        "volume.materialize",
        "state.variable",
        "write.entity",
        "action.email",
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
    assert by_type["transform.code"]["permission"] == "channel:code_write"
    assert by_type["read.source_query"]["permission"] == "channel:source_query"
    assert (
        by_type["transform.code"]["config_schema"]["properties"]["code"]["contentMediaType"]
        == "text/x-python"
    )
    assert (
        by_type["read.source_query"]["config_schema"]["properties"]["source_id"]["x-refraq-ref"]
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
    changed["nodes"] = [{**SCHEDULED_GRAPH["nodes"][0], "config": {"cron": "15 * * * *"}}]
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


def test_global_variable_list_and_delete(client: TestClient) -> None:
    from backend.channel.variables import get_variable_store

    saved = get_variable_store().apply(operation="set", name="lease", value={"held": True})
    assert saved.applied is True
    listed = client.get("/channel-variables")
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["name"] == "lease"
    removed = client.delete("/channel-variables/lease")
    assert removed.status_code == 204
    assert client.get("/channel-variables").json()["items"] == []
    events, _cursor = get_audit_store().list_events(limit=20)
    assert any(event.action == "channel.variable_delete" for event in events)


def _guarded_graph(type_id: str, config: dict, *, trigger_name: str = "Run manually") -> dict:
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


def _writer_client(account: str) -> TestClient:
    role = create_role(
        get_role_store(),
        key=f"role_{account}",
        name=account,
        permissions=["console:access", "channel:read", "channel:write"],
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
        removed["nodes"] = [node for node in removed["nodes"] if node["id"] != "nd_guard"]
        removed["edges"] = []
        deleted = writer.put(
            f"/channels/{channel_id}/draft",
            json={"base_revision": current["draft_revision"], "graph": removed},
        )
        assert deleted.status_code == 200, deleted.text
        assert all(node["id"] != "nd_guard" for node in deleted.json()["graph"]["nodes"])
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
        assert plain.get(f"/channels/{channel_id}/runs/{job_id}/executions").status_code == 403
        assert plain.get(rows).status_code == 403
    with TestClient(app) as allowed:
        _login(allowed, "reader", "secret")
        assert allowed.get(f"/channels/{channel_id}/runs/{job_id}").status_code == 200
        assert allowed.get(f"/channels/{channel_id}/runs/{job_id}/executions").status_code == 200
    assert running.status == "running"


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
        started = client.post(f"/channels/{channel_id}/runs", json={"target": "published"})
        assert started.status_code == 202, started.text
        job_id = started.json()["run"]["job_id"]
        assert mark_failed(job_id, error_code="CHANNEL_NODE_FAILED", error_summary="failed")
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
        assert mark_failed(draft_id, error_code="CHANNEL_NODE_FAILED", error_summary="failed")
        refused = client.post(f"/channels/{channel_id}/runs/{draft_id}/rerun")
        assert_problem(refused, status=422, code="CHANNEL_RUN_NOT_RERUNNABLE")
    finally:
        set_dispatcher(previous)
