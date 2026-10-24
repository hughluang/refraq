"""Template Preview against a recorded Channel Run (memory store, real sandbox)."""

from __future__ import annotations

import copy
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
from backend.channel.run_store import ChannelRunRecord, get_run_store  # noqa: E402
from backend.channel.runner import run_channel_job  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.main import app  # noqa: E402


def _node(
    node_id: str,
    ref: str,
    node_type: str,
    y: int,
    config: dict,
    *,
    parent: str | None = None,
) -> dict:
    node = {
        "id": node_id,
        "ref": ref,
        "type": node_type,
        "name": ref.replace("_", " ").capitalize(),
        "position": {"x": 0, "y": y},
        "config": config,
        "on_error": "stop",
        "retry": None,
    }
    if parent is not None:
        node["parent"] = parent
    return node


def _edge(source: str, target: str, *, source_port: str = "main") -> dict:
    return {
        "id": f"ed_{source}_{source_port}_{target}",
        "source": {"node_id": source, "port": source_port},
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
def client() -> TestClient:
    from backend.channel.channel_run import set_dispatcher

    previous = set_dispatcher(lambda _job_id: None)
    try:
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
    finally:
        set_dispatcher(previous)


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
    scope: list[dict[str, Any]] | None = None,
) -> Any:
    body: dict[str, Any] = {"graph": graph, "node_id": node_id, "path": path}
    if scope is not None:
        body["scope"] = scope
    return client.post(
        f"/channels/{channel_id}/runs/{job_id}/template-preview",
        json=body,
    )


def _sample(
    client: TestClient,
    channel_id: str,
    job_id: str,
    graph: dict,
    node_id: str,
    scope: list[dict[str, Any]] | None = None,
) -> Any:
    body: dict[str, Any] = {"graph": graph, "node_id": node_id}
    if scope is not None:
        body["scope"] = scope
    return client.post(
        f"/channels/{channel_id}/runs/{job_id}/node-sample",
        json=body,
    )


def _execution_seq(
    client: TestClient,
    channel_id: str,
    job_id: str,
    node_id: str,
    *,
    round_index: int | None = None,
) -> int:
    params: dict[str, Any] = {"node_id": node_id, "limit": 200}
    if round_index is not None:
        params["round"] = round_index
    listed = client.get(f"/channels/{channel_id}/runs/{job_id}/executions", params=params)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items, node_id
    return int(items[-1]["seq"])


def _trigger_binding(client: TestClient, channel_id: str, job_id: str) -> dict[str, Any]:
    return {
        "node_id": "nd_trigger",
        "seq": _execution_seq(client, channel_id, job_id, "nd_trigger"),
        "source": "execution",
    }


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
    trigger = _trigger_binding(client, channel_id, job_id)
    assert _result(*scope, _graph(), "nd_keep", ["value"]) == {
        "state": "ok",
        "value": 6,
        "truncated": False,
        "scope": [],
        "bindings": [trigger],
    }
    assert _result(*scope, _graph(value="{{ self.run.id }}"), "nd_keep", ["value"]) == {
        "state": "ok",
        "value": job_id,
        "truncated": False,
        "scope": [],
        "bindings": [trigger],
    }
    renamed = _graph(name="lease-{{ self.run_manually.output.count }}")
    assert _result(*scope, renamed, "nd_keep", ["name"])["value"] == "lease-3"
    long = _result(*scope, _graph(value="{{ list(range(150)) }}"), "nd_keep", ["value"])
    assert long["state"] == "ok"
    assert long["value"] == list(range(100))
    assert long["truncated"] is True
    assert long["scope"] == []
    assert long["bindings"] == [trigger]


def test_preview_reports_the_failure_the_node_would_record(client: TestClient) -> None:
    channel_id, job_id = _run_trigger_only(client)
    scope = (client, channel_id, job_id)
    absent = _result(
        *scope, _graph(value="{{ self.run_manually.output.absent }}"), "nd_keep", ["value"]
    )
    assert absent["state"] == "failed"
    assert absent["code"] == "CHANNEL_NODE_FAILED"
    assert "absent" in absent["message"]
    assert absent["scope"] == []
    assert absent["bindings"] == [_trigger_binding(client, channel_id, job_id)]
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
    trigger = _trigger_binding(client, channel_id, job_id)
    assert _result(*scope, _graph(), "nd_read", ["name"]) == {
        "state": "missing",
        "node_ids": ["nd_keep"],
        "context": False,
        "scope": [],
        "bindings": [
            {"node_id": "nd_keep", "source": "execution"},
            trigger,
        ],
    }
    store = get_run_store()
    record = store.get_run(job_id)
    record.context = None
    store.update_run(record)
    assert _result(*scope, _graph(value="{{ self.run.id }}"), "nd_keep", ["value"]) == {
        "state": "missing",
        "node_ids": [],
        "context": True,
        "scope": [],
        "bindings": [trigger],
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
        denied_sample = _sample(reader, channel_id, job_id, _graph(), "nd_keep")
    assert denied.status_code == 403
    assert denied_sample.status_code == 403


def _settings() -> dict[str, Any]:
    return {"run_timeout_sec": None, "error_channel_id": None}


def _run_saved(client: TestClient, graph: dict, *, name: str) -> tuple[str, str]:
    created = client.post("/channels", json={"name": name, "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": 1, "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    started = client.post(f"/channels/{channel_id}/runs", json={"target": "draft"})
    assert started.status_code == 202, started.text
    job_id = started.json()["run"]["job_id"]
    assert run_channel_job(job_id) == {"status": "succeeded"}
    return channel_id, job_id


def _for_graph() -> dict[str, Any]:
    return {
        "nodes": [
            _node("nd_trigger", "run_manually", "trigger.manual", 0, {}),
            _node("nd_walk", "walk", "volume.for", 100, {"items": "[1, 2, 3]"}),
            _node(
                "nd_step",
                "step",
                "transform.set_fields",
                200,
                {"fields": [{"name": "n", "value": "{{ self.walk.output.current }}"}]},
                parent="nd_walk",
            ),
            _node(
                "nd_tail",
                "tail",
                "transform.set_fields",
                300,
                {
                    "fields": [
                        {"name": "from_walk", "value": "{{ self.walk.output }}"},
                        {"name": "from_step", "value": '{{ self.nodes["Step"].output.n }}'},
                        {"name": "nums", "value": "{{ [1, 2, 3] }}"},
                    ]
                },
                parent="nd_walk",
            ),
            _node(
                "nd_after",
                "after",
                "transform.set_fields",
                400,
                {"fields": [{"name": "iters", "value": "{{ self.walk.output.iterations }}"}]},
            ),
        ],
        "edges": [
            _edge("nd_trigger", "nd_walk"),
            _edge("nd_walk", "nd_step", source_port="each"),
            _edge("nd_step", "nd_tail"),
            _edge("nd_walk", "nd_after", source_port="done"),
        ],
        "settings": _settings(),
    }


def _upstream(body: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(item for item in body["upstream"] if item["node_id"] == node_id)


def test_for_round_sample_binds_the_step_and_the_same_round(client: TestClient) -> None:
    graph = _for_graph()
    channel_id, job_id = _run_saved(client, graph, name="For rounds")
    before = client.get(f"/channels/{channel_id}/runs/{job_id}/executions", params={"limit": 200})
    assert before.status_code == 200, before.text
    walk_seq = _execution_seq(client, channel_id, job_id, "nd_walk")
    step_seq = _execution_seq(client, channel_id, job_id, "nd_step", round_index=1)
    trigger_seq = _execution_seq(client, channel_id, job_id, "nd_trigger")
    chosen = [{"container_node_id": "nd_walk", "round": 1}]

    response = _sample(client, channel_id, job_id, graph, "nd_tail", chosen)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == [
        {
            "container_node_id": "nd_walk",
            "container_seq": walk_seq,
            "round": 1,
            "rounds_total": 3,
        }
    ]
    assert body["config_changed"] is False
    assert [item["node_id"] for item in body["upstream"]] == ["nd_walk", "nd_step", "nd_trigger"]
    walk = _upstream(body, "nd_walk")
    assert walk["referenced"] is True
    assert walk["state"] == "ok"
    assert walk["source"] == "round_step"
    assert walk["seq"] is None
    assert walk["value"] == {"current": 2, "index": 1, "count": 3}
    assert "iterations" not in walk["value"]
    assert walk["truncated"] is False
    assert walk["totals"] == {}
    assert walk["error"] is None
    step = _upstream(body, "nd_step")
    assert step["referenced"] is True
    assert step["state"] == "ok"
    assert step["source"] == "execution"
    assert step["seq"] == step_seq
    assert step["value"] == {"n": 2}
    listed = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"node_id": "nd_step", "round": 1, "limit": 200},
    )
    assert listed.json()["items"][-1]["container_seq"] == walk_seq
    assert listed.json()["items"][-1]["round"] == 1
    trigger = _upstream(body, "nd_trigger")
    assert trigger["referenced"] is False
    assert trigger["source"] == "execution"
    assert trigger["seq"] == trigger_seq
    assert trigger["state"] == "ok"
    node = body["node"]
    assert node["state"] == "ok"
    assert node["status"] == "succeeded"
    assert node["output"]["from_walk"] == {"current": 2, "index": 1, "count": 3}
    assert node["output"]["from_step"] == 2
    assert node["output"]["nums"] == [1, 2, 3]
    assert node["output_truncated"] is False
    assert node["totals"] == {}
    assert node["error"] is None
    tail_listed = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"node_id": "nd_tail", "round": 1, "limit": 200},
    )
    tail_exec = tail_listed.json()["items"][-1]
    assert node["seq"] == tail_exec["seq"]
    assert node["input"] == tail_exec["input_preview"]
    assert node["input_totals"] == tail_exec["input_totals"]
    assert node["input_totals"]["fields.2.value"] == 3
    after_sample = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions", params={"limit": 200}
    )
    assert after_sample.json() == before.json()

    default = _sample(client, channel_id, job_id, graph, "nd_tail")
    assert default.status_code == 200, default.text
    default_body = default.json()
    assert default_body["scope"][0]["round"] == 2
    assert default_body["scope"][0]["rounds_total"] == 3
    assert default_body["scope"][0]["container_seq"] == walk_seq
    assert _upstream(default_body, "nd_walk")["value"] == {"current": 3, "index": 2, "count": 3}
    assert _upstream(default_body, "nd_step")["value"] == {"n": 3}

    spare = copy.deepcopy(graph)
    spare["nodes"].append(
        _node(
            "nd_spare",
            "spare",
            "transform.set_fields",
            250,
            {"fields": [{"name": "n", "value": "{{ self.walk.output.current }}"}]},
            parent="nd_walk",
        )
    )
    spare["edges"].append(_edge("nd_walk", "nd_spare", source_port="each"))
    untouched = _sample(client, channel_id, job_id, spare, "nd_spare")
    assert untouched.status_code == 200, untouched.text
    untouched_body = untouched.json()
    assert untouched_body["scope"] == [
        {
            "container_node_id": "nd_walk",
            "container_seq": walk_seq,
            "round": 2,
            "rounds_total": 3,
        }
    ]
    assert _upstream(untouched_body, "nd_walk")["value"]["current"] == 3
    assert untouched_body["node"]["state"] == "not_recorded"
    assert untouched_body["node"]["output"] is None

    missing_round = _sample(
        client,
        channel_id,
        job_id,
        graph,
        "nd_tail",
        [{"container_node_id": "nd_walk", "round": 9}],
    )
    assert missing_round.status_code == 200, missing_round.text
    missing_body = missing_round.json()
    assert missing_body["scope"][0]["round"] == 9
    assert missing_body["scope"][0]["rounds_total"] == 3
    assert missing_body["scope"][0]["container_seq"] == walk_seq
    assert _upstream(missing_body, "nd_walk")["state"] == "not_recorded"
    assert _upstream(missing_body, "nd_walk")["source"] == "round_step"
    assert _upstream(missing_body, "nd_walk")["value"] is None
    assert _upstream(missing_body, "nd_step")["state"] == "not_recorded"
    assert missing_body["node"]["state"] == "not_recorded"

    edited = copy.deepcopy(graph)
    edited["nodes"][3]["config"]["fields"][2]["value"] = "{{ [1] }}"
    changed = _sample(client, channel_id, job_id, edited, "nd_tail", chosen)
    assert changed.status_code == 200, changed.text
    assert changed.json()["config_changed"] is True

    outside = _sample(client, channel_id, job_id, graph, "nd_after")
    assert outside.status_code == 200, outside.text
    outside_body = outside.json()
    assert outside_body["scope"] == []
    outside_walk = _upstream(outside_body, "nd_walk")
    assert outside_walk["source"] == "execution"
    assert outside_walk["seq"] == walk_seq
    assert len(outside_walk["value"]["iterations"]) == 3
    assert set(outside_walk["value"]["iterations"][0]) == {"step", "tail"}

    preview = _result(
        client,
        channel_id,
        job_id,
        graph,
        "nd_tail",
        ["fields", 0, "value"],
        chosen,
    )
    assert preview == {
        "state": "ok",
        "value": {"current": 2, "index": 1, "count": 3},
        "truncated": False,
        "scope": body["scope"],
        "bindings": [
            {"node_id": "nd_walk", "source": "round_step"},
            {"node_id": "nd_step", "seq": step_seq, "source": "execution"},
            {"node_id": "nd_trigger", "seq": trigger_seq, "source": "execution"},
        ],
    }
    default_preview = _result(client, channel_id, job_id, graph, "nd_tail", ["fields", 0, "value"])
    assert default_preview["value"] == {"current": 3, "index": 2, "count": 3}
    assert default_preview["scope"][0]["round"] == 2
    iterations = _result(client, channel_id, job_id, graph, "nd_after", ["fields", 0, "value"])
    assert iterations["state"] == "ok"
    assert len(iterations["value"]) == 3
    assert iterations["scope"] == []
    assert iterations["bindings"][0] == {
        "node_id": "nd_walk",
        "seq": walk_seq,
        "source": "execution",
    }

    assert_problem(
        _sample(client, channel_id, job_id, graph, "nd_tail", scope=[]),
        status=422,
        code="REQUEST_INVALID",
    )
    assert_problem(
        _sample(
            client,
            channel_id,
            job_id,
            graph,
            "nd_tail",
            [{"container_node_id": "nd_other", "round": 0}],
        ),
        status=422,
        code="REQUEST_INVALID",
    )
    assert_problem(
        _sample(
            client,
            channel_id,
            job_id,
            graph,
            "nd_tail",
            [{"container_node_id": "nd_walk", "round": -1}],
        ),
        status=422,
        code="REQUEST_INVALID",
    )
    assert_problem(
        _sample(client, channel_id, job_id, graph, "nd_absent"),
        status=422,
        code="REQUEST_INVALID",
    )
    assert_problem(
        _sample(client, channel_id, "job_absent", graph, "nd_tail"),
        status=404,
        code="CHANNEL_RUN_NOT_FOUND",
    )
    assert_problem(
        _preview(client, channel_id, job_id, graph, "nd_tail", ["fields", 0, "value"], []),
        status=422,
        code="REQUEST_INVALID",
    )

    store = get_run_store()
    record = store.get_run(job_id)
    record.graph = copy.deepcopy(record.graph)
    record.graph["nodes"] = [node for node in record.graph["nodes"] if node["id"] != "nd_tail"]
    store.update_run(record)
    removed = _sample(client, channel_id, job_id, graph, "nd_tail", chosen)
    assert removed.status_code == 200, removed.text
    assert removed.json()["config_changed"] is True


def _seed(client: TestClient, graph: dict, *, name: str) -> tuple[str, str]:
    created = client.post("/channels", json={"name": name, "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    job_id = f"job_{channel_id}"
    get_run_store().insert_run(
        ChannelRunRecord(
            job_id=job_id,
            channel_id=channel_id,
            target="draft",
            version=None,
            draft_revision=1,
            graph=copy.deepcopy(graph),
            trigger_node_id=str(graph["nodes"][0]["id"]),
            ignore_checkpoints=False,
            outcome="succeeded",
            failed_node_id=None,
            skipped_node_ids=[],
            created_at=utc_now(),
            context=None,
        )
    )
    return channel_id, job_id


def _finish(record: Any, **fields: Any) -> Any:
    record.status = fields.get("status", "succeeded")
    record.output = fields.get("output")
    record.error_code = fields.get("error_code")
    record.error_message = fields.get("error_message")
    record.finished_at = None if record.status == "running" else utc_now()
    record.preview_only = bool(fields.get("preview_only", False))
    record.preview_totals = dict(fields.get("preview_totals") or {})
    if "input" in fields:
        record.input = fields["input"]
        record.input_totals = fields.get("input_totals")
    get_run_store().finish_execution(record)
    return record


def test_skipped_execution_keeps_output_and_error(client: TestClient) -> None:
    graph = {
        "nodes": [
            _node("nd_trigger", "run_manually", "trigger.manual", 0, {}),
            _node(
                "nd_skip",
                "skip",
                "transform.set_fields",
                100,
                {"fields": [{"name": "n", "value": "1"}]},
            ),
            _node(
                "nd_next",
                "next",
                "transform.set_fields",
                200,
                {"fields": [{"name": "seen", "value": "{{ self.skip.output }}"}]},
            ),
        ],
        "edges": [_edge("nd_trigger", "nd_skip"), _edge("nd_skip", "nd_next")],
        "settings": _settings(),
    }
    channel_id, job_id = _seed(client, graph, name="Skipped")
    store = get_run_store()
    trigger = store.start_execution(job_id, "nd_trigger")
    _finish(trigger, output={"rows": [], "count": 1, "rowcount": 1})
    skipped = store.start_execution(job_id, "nd_skip")
    _finish(
        skipped,
        status="skipped",
        output={"skipped": True, "reasons": ["match_key"]},
        error_message="incompatible head",
    )
    own = _sample(client, channel_id, job_id, graph, "nd_skip")
    assert own.status_code == 200, own.text
    own_node = own.json()["node"]
    assert own_node["state"] == "skipped"
    assert own_node["status"] == "skipped"
    assert own_node["output"] == {"skipped": True, "reasons": ["match_key"]}
    assert own_node["error"] == {"code": None, "message": "incompatible head"}
    shown = _sample(client, channel_id, job_id, graph, "nd_next")
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert [item["node_id"] for item in body["upstream"]] == ["nd_skip", "nd_trigger"]
    skip = _upstream(body, "nd_skip")
    assert skip["state"] == "ok"
    assert skip["source"] == "execution"
    assert skip["value"] == {"skipped": True, "reasons": ["match_key"]}
    assert skip["error"] == {"code": None, "message": "incompatible head"}
    assert skip["seq"] == skipped.seq
    recorded = _upstream(body, "nd_trigger")
    assert recorded["value"] == {"rows": [], "count": 1, "rowcount": 1}
    assert recorded["totals"] == {}
    assert recorded["truncated"] is False


def test_batch_round_rows_keep_clip_totals(client: TestClient) -> None:
    graph = {
        "nodes": [
            _node("nd_trigger", "run_manually", "trigger.manual", 0, {}),
            _node(
                "nd_batch",
                "batch",
                "volume.batch_read",
                100,
                {"dataset": "{{ self.run_manually.output }}", "batch_size": 1000},
            ),
            _node(
                "nd_body",
                "body",
                "transform.set_fields",
                200,
                {"fields": [{"name": "rows", "value": "{{ self.batch.output.rows }}"}]},
                parent="nd_batch",
            ),
        ],
        "edges": [
            _edge("nd_trigger", "nd_batch"),
            _edge("nd_batch", "nd_body", source_port="each"),
        ],
        "settings": _settings(),
    }
    channel_id, job_id = _seed(client, graph, name="Batch rows")
    store = get_run_store()
    batch = store.start_execution(job_id, "nd_batch")
    _finish(batch, output={"count": 1, "total": 150, "batch_size": 1000})
    rows = [{"code": f"S-{index:03d}", "tags": ["a"]} for index in range(150)]
    store.insert_round(
        job_id,
        container_seq=batch.seq,
        round=0,
        step={"rows": rows, "index": 0, "count": 1, "total": 150},
        step_totals={"rows": 150, "rows.0.tags": 1},
    )
    body_exec = store.start_execution(job_id, "nd_body", container_seq=batch.seq, round=0)
    _finish(body_exec, output={"rows": rows[:1]})
    scope = [{"container_node_id": "nd_batch", "round": 0}]
    response = _sample(client, channel_id, job_id, graph, "nd_body", scope)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == [
        {
            "container_node_id": "nd_batch",
            "container_seq": batch.seq,
            "round": 0,
            "rounds_total": 1,
        }
    ]
    batch_slot = _upstream(body, "nd_batch")
    assert batch_slot["source"] == "round_step"
    assert batch_slot["state"] == "ok"
    assert batch_slot["seq"] is None
    assert batch_slot["referenced"] is True
    assert "batch_size" not in batch_slot["value"]
    assert len(batch_slot["value"]["rows"]) == 100
    assert batch_slot["value"]["rows"][0] == {"code": "S-000", "tags": ["a"]}
    assert batch_slot["value"]["total"] == 150
    assert batch_slot["truncated"] is True
    assert batch_slot["totals"] == {"rows": 150, "rows.0.tags": 1}
    preview = _result(
        client,
        channel_id,
        job_id,
        graph,
        "nd_body",
        ["fields", 0, "value"],
        scope,
    )
    assert preview["state"] == "ok"
    assert len(preview["value"]) == 100
    assert preview["value"][0] == {"code": "S-000", "tags": ["a"]}
    assert preview["truncated"] is True
    assert preview["scope"] == body["scope"]
    assert {"node_id": "nd_batch", "source": "round_step"} in preview["bindings"]


def test_node_sample_folds_preview_totals_with_the_response_clip(client: TestClient) -> None:
    graph = {
        "nodes": [
            _node("nd_empty", "empty", "transform.set_fields", 0, {"fields": []}),
            _node("nd_long", "long_list", "transform.set_fields", 100, {"fields": []}),
            _node("nd_wide", "wide", "transform.set_fields", 200, {"fields": []}),
        ],
        "edges": [],
        "settings": _settings(),
    }
    channel_id, job_id = _seed(client, graph, name="Totals")
    store = get_run_store()
    empty = store.start_execution(job_id, "nd_empty")
    _finish(empty, output={"rows": [], "count": 1, "rowcount": 1})
    long = store.start_execution(job_id, "nd_long")
    _finish(long, output={"rows": list(range(150))})
    wide = store.start_execution(job_id, "nd_wide")
    _finish(
        wide,
        output={"rows": list(range(100)), "tags": ["a", "b"]},
        preview_only=True,
        preview_totals={"rows": 1000000, "tags": 2},
        input={
            "source": {"value": list(range(100))},
            "note": {"value": ["a", "b"]},
        },
        input_totals={"source": 1000000, "note": 2},
    )
    empty_body = _sample(client, channel_id, job_id, graph, "nd_empty").json()
    assert empty_body["node"]["output"] == {"rows": [], "count": 1, "rowcount": 1}
    assert empty_body["node"]["totals"] == {}
    assert empty_body["node"]["output_truncated"] is False
    long_body = _sample(client, channel_id, job_id, graph, "nd_long").json()
    assert len(long_body["node"]["output"]["rows"]) == 100
    assert long_body["node"]["output"]["rows"][0] == 0
    assert long_body["node"]["output"]["rows"][-1] == 99
    assert long_body["node"]["output_truncated"] is True
    assert long_body["node"]["totals"] == {"rows": 150}
    wide_body = _sample(client, channel_id, job_id, graph, "nd_wide").json()["node"]
    assert len(wide_body["output"]["rows"]) == 100
    assert wide_body["output"]["tags"] == ["a", "b"]
    assert wide_body["output_truncated"] is True
    assert wide_body["totals"] == {"rows": 1000000, "tags": 2}
    assert wide_body["input_totals"] == {"source": 1000000, "note": 2}
    assert len(wide_body["input"]["source"]["value"]) == 100
    assert wide_body["input"]["note"]["value"] == ["a", "b"]
