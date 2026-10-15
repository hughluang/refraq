"""Template Preview against a recorded Channel Run (memory store, real sandbox)."""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.tests.problem import assert_problem  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.channel.run_store import get_run_store  # noqa: E402
from backend.channel.runner import run_channel_job  # noqa: E402
from backend.main import app  # noqa: E402


def _node(node_id: str, ref: str, node_type: str, y: int, config: dict) -> dict:
    return {
        "id": node_id,
        "ref": ref,
        "type": node_type,
        "name": ref.replace("_", " ").capitalize(),
        "position": {"x": 0, "y": y},
        "config": config,
        "on_error": "stop",
        "retry": None,
    }


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"ed_{source}_{target}",
        "source": {"node_id": source, "port": "main"},
        "target": {"node_id": target, "port": "main"},
    }


def _graph(**keep: str) -> dict:
    """Trigger, then a variable write whose templates read it, then a read of that write."""
    return {
        "nodes": [
            _node("nd_trigger", "run_manually", "trigger.manual", 0, {"payload": {"count": 3}}),
            _node(
                "nd_keep",
                "keep",
                "state.variable",
                100,
                {
                    "operation": "set",
                    "name": "lease",
                    "value": "{{ self.run_manually.output.count * 2 }}",
                    **keep,
                },
            ),
            _node(
                "nd_read",
                "read_back",
                "state.variable",
                200,
                {"operation": "get", "name": "{{ self.keep.output.name }}"},
            ),
        ],
        "edges": [_edge("nd_trigger", "nd_keep"), _edge("nd_keep", "nd_read")],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }


def _login(client: TestClient, account: str) -> None:
    response = client.post("/auth/login", json={"account": account, "password": "secret"})
    assert response.status_code == 200, response.text


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import backend.channel.tasks as tasks

    monkeypatch.setattr(tasks.run_job, "apply_async", lambda *args, **kwargs: None)
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
        _login(test_client, "admin")
        yield test_client


def _run_trigger_only(client: TestClient) -> tuple[str, str]:
    created = client.post("/channels", json={"name": "Preview", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    saved = client.put(
        f"/channels/{channel_id}/draft", json={"base_revision": 1, "graph": _graph()}
    )
    assert saved.status_code == 200, saved.text
    started = client.post(
        f"/channels/{channel_id}/runs",
        json={"target": "draft", "stop_at_node_id": "nd_trigger"},
    )
    assert started.status_code == 202, started.text
    job_id = started.json()["run"]["job_id"]
    assert run_channel_job(job_id) == {"status": "succeeded"}
    return channel_id, job_id


def _preview(
    client: TestClient,
    channel_id: str,
    job_id: str,
    graph: dict,
    node_id: str,
    path: list[Any],
) -> Any:
    return client.post(
        f"/channels/{channel_id}/runs/{job_id}/template-preview",
        json={"graph": graph, "node_id": node_id, "path": path},
    )


def _result(*args: Any) -> dict:
    response = _preview(*args)
    assert response.status_code == 200, response.text
    return response.json()


def test_run_records_the_expression_context_it_evaluated_with(client: TestClient) -> None:
    channel_id, job_id = _run_trigger_only(client)
    context = get_run_store().get_run(job_id).context
    assert context is not None
    assert context["channel"]["id"] == channel_id
    assert context["run"]["id"] == job_id
    assert context["run"]["target"] == "draft"
    assert set(context["platform"]) >= {"now", "schedule_timezone", "parameters"}


def test_preview_evaluates_the_current_template_against_the_run(client: TestClient) -> None:
    channel_id, job_id = _run_trigger_only(client)
    scope = (client, channel_id, job_id)
    assert _result(*scope, _graph(), "nd_keep", ["value"]) == {
        "state": "ok",
        "value": 6,
        "truncated": False,
    }
    assert _result(*scope, _graph(value="{{ self.run.id }}"), "nd_keep", ["value"]) == {
        "state": "ok",
        "value": job_id,
        "truncated": False,
    }
    renamed = _graph(name="lease-{{ self.run_manually.output.count }}")
    assert _result(*scope, renamed, "nd_keep", ["name"])["value"] == "lease-3"
    long = _result(*scope, _graph(value="{{ list(range(150)) }}"), "nd_keep", ["value"])
    assert long["state"] == "ok"
    assert long["value"] == list(range(100))
    assert long["truncated"] is True


def test_preview_reports_the_failure_the_node_would_record(client: TestClient) -> None:
    channel_id, job_id = _run_trigger_only(client)
    scope = (client, channel_id, job_id)
    absent = _result(
        *scope, _graph(value="{{ self.run_manually.output.absent }}"), "nd_keep", ["value"]
    )
    assert absent["state"] == "failed"
    assert absent["code"] == "CHANNEL_NODE_FAILED"
    assert "absent" in absent["message"]
    mismatch = _result(*scope, _graph(name="{{ None }}"), "nd_keep", ["name"])
    assert mismatch["state"] == "failed"
    assert mismatch["code"] == "CHANNEL_VALUE_TYPE_MISMATCH"
    downstream = _result(*scope, _graph(value="{{ self.read_back.output }}"), "nd_keep", ["value"])
    assert downstream["state"] == "failed"
    assert downstream["code"] == "CHANNEL_TEMPLATE_REF_INVALID"
    broken = _result(*scope, _graph(value="{{ 1 +"), "nd_keep", ["value"])
    assert broken["code"] == "CHANNEL_EXPRESSION_INVALID"


def test_preview_names_what_the_run_did_not_record(client: TestClient) -> None:
    channel_id, job_id = _run_trigger_only(client)
    scope = (client, channel_id, job_id)
    assert _result(*scope, _graph(), "nd_read", ["name"]) == {
        "state": "missing",
        "node_ids": ["nd_keep"],
        "context": False,
    }
    store = get_run_store()
    record = store.get_run(job_id)
    record.context = None
    store.update_run(record)
    assert _result(*scope, _graph(value="{{ self.run.id }}"), "nd_keep", ["value"]) == {
        "state": "missing",
        "node_ids": [],
        "context": True,
    }
    assert _result(*scope, _graph(), "nd_keep", ["value"])["value"] == 6


def test_preview_refuses_what_is_not_a_template_of_this_channels_run(client: TestClient) -> None:
    channel_id, job_id = _run_trigger_only(client)
    not_template = _preview(client, channel_id, job_id, _graph(), "nd_keep", ["operation"])
    assert_problem(not_template, status=422, code="REQUEST_INVALID")
    no_node = _preview(client, channel_id, job_id, _graph(), "nd_absent", ["value"])
    assert_problem(no_node, status=422, code="REQUEST_INVALID")
    unknown = _preview(client, channel_id, "job_absent", _graph(), "nd_keep", ["value"])
    assert_problem(unknown, status=404, code="CHANNEL_RUN_NOT_FOUND")
    other = client.post("/channels", json={"name": "Other", "description": None})
    other_id = other.json()["channel"]["id"]
    foreign = _preview(client, other_id, job_id, _graph(), "nd_keep", ["value"])
    assert_problem(foreign, status=404, code="CHANNEL_RUN_NOT_FOUND")


def test_preview_requires_channel_write(client: TestClient) -> None:
    channel_id, job_id = _run_trigger_only(client)
    role = create_role(
        get_role_store(),
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
    with TestClient(app) as reader:
        _login(reader, "reader")
        denied = _preview(reader, channel_id, job_id, _graph(), "nd_keep", ["value"])
    assert denied.status_code == 403
