"""Sub Data Channel validation, lifecycle guards, and inline synchronous execution."""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.channel.channel_run import set_dispatcher  # noqa: E402
from backend.channel.dataset_ref import dataset_reference  # noqa: E402
from backend.channel.dataset_registry import (  # noqa: E402
    DatasetRecord,
    get_dataset_store,
)
from backend.channel.locks import try_acquire_channel_run_lock  # noqa: E402
from backend.channel.runner import run_channel_job  # noqa: E402
from backend.channel.store import get_channel_store  # noqa: E402
from backend.channel.variables import get_variable_store  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.entity.history.service import (  # noqa: E402
    HistorySide,
    IncrementalEvent,
    IncrementalPosition,
)
from backend.main import app  # noqa: E402


def _node(
    node_id: str,
    ref: str,
    type_id: str,
    name: str,
    config: dict[str, Any] | None = None,
    *,
    parent: str | None = None,
    on_error: str = "stop",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": node_id,
        "ref": ref,
        "type": type_id,
        "name": name,
        "position": {"x": 0, "y": 0},
        "config": config or {},
        "on_error": on_error,
        "retry": None,
    }
    if parent is not None:
        item["parent"] = parent
    return item


def _edge(
    edge_id: str,
    source_id: str,
    target_id: str,
    *,
    source_port: str = "main",
    target_port: str = "main",
) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": {"node_id": source_id, "port": source_port},
        "target": {"node_id": target_id, "port": target_port},
    }


def _graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None = None,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = {
        "run_timeout_sec": 30,
        "error_channel_id": None,
        "keep_succeeded_runs": True,
        "keep_failed_runs": True,
        "keep_test_runs": True,
        "concurrency": "allow",
    }
    if settings:
        merged.update(settings)
    return {"nodes": nodes, "edges": edges or [], "settings": merged}


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
    previous = set_dispatcher(lambda job_id: run_channel_job(job_id))
    try:
        with TestClient(app) as test_client:
            res = test_client.post(
                "/auth/login", json={"account": "admin", "password": "secret"}
            )
            assert res.status_code == 200, res.text
            yield test_client
    finally:
        set_dispatcher(previous)


def _create_channel(client: TestClient, name: str) -> str:
    res = client.post("/channels", json={"name": name, "description": None})
    assert res.status_code == 201, res.text
    return str(res.json()["channel"]["id"])


def _validate(
    client: TestClient, channel_id: str, graph: dict[str, Any]
) -> dict[str, Any]:
    res = client.post(
        f"/channels/{channel_id}/draft/validate", json={"graph": graph}
    )
    assert res.status_code == 200, res.text
    return res.json()


def _save_and_publish(
    client: TestClient,
    channel_id: str,
    graph: dict[str, Any],
    *,
    active: bool = True,
) -> dict[str, Any]:
    draft = client.get(f"/channels/{channel_id}/draft").json()
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": draft["draft_revision"], "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    rev = saved.json()["draft_revision"]
    pub = client.post(
        f"/channels/{channel_id}/publish", json={"draft_revision": rev}
    )
    assert pub.status_code == 201, pub.text
    if active:
        act = client.post(f"/channels/{channel_id}/activate")
        assert act.status_code == 200, act.text
    return pub.json()["version"]


def test_subchannel_trigger_validation_and_standalone_sample_run(
    client: TestClient,
) -> None:
    sub_id = _create_channel(client, "Sub Validator")
    bad_graph = _graph(
        [
            _node(
                "nd_trig",
                "sub_in",
                "trigger.subchannel",
                "Sub Trigger",
                {
                    "input": [
                        {
                            "name": "bad-name",
                            "type": "string",
                            "required": True,
                            "default": "nope",
                        },
                        {
                            "name": "rows",
                            "type": "dataset",
                            "required": False,
                            "default": {},
                        },
                    ],
                    "sample_input": {"undeclared": 1},
                },
            )
        ]
    )
    body = _validate(client, sub_id, bad_graph)
    assert body["valid"] is False
    paths = {tuple(p["path"]) for p in body["problems"]}
    assert ("input", 0, "name") in paths
    assert ("input", 0, "default") in paths
    assert ("input", 1, "default") in paths
    assert ("sample_input", "undeclared") in paths

    good_graph = _graph(
        [
            _node(
                "nd_trig",
                "sub_in",
                "trigger.subchannel",
                "Sub Trigger",
                {
                    "input": [
                        {"name": "topic", "type": "string", "required": True},
                        {
                            "name": "batch_size",
                            "type": "integer",
                            "required": False,
                            "default": 50,
                        },
                    ],
                    "sample_input": {"topic": "orders"},
                },
            ),
            _node(
                "nd_ret",
                "ret",
                "action.return",
                "Return",
                {
                    "value": "{{ {'topic': self.sub_in.output.topic, 'batch': self.sub_in.output.batch_size} }}"
                },
            ),
        ],
        [_edge("ed_1", "nd_trig", "nd_ret")],
    )
    _save_and_publish(client, sub_id, good_graph, active=False)

    # Standalone test run works even while active=False, applying sample_input + defaults.
    started = client.post(
        f"/channels/{sub_id}/runs", json={"target": "published"}
    )
    assert started.status_code == 202, started.text
    run_out = started.json()["run"]
    assert run_out["status"] == "succeeded"
    detail = client.get(f"/channels/{sub_id}/runs/{run_out['job_id']}").json()["run"]
    assert detail["return_value"] == {"topic": "orders", "batch": 50}


def test_return_rejected_outside_subchannel_and_call_channel_validation_and_guards(
    client: TestClient,
) -> None:
    manual_id = _create_channel(client, "Manual Channel")
    bad_return = _graph(
        [
            _node("nd_t", "trig", "trigger.manual", "Manual"),
            _node("nd_r", "ret", "action.return", "Return", {"value": "{{ 1 }}"}),
        ],
        [_edge("ed_1", "nd_t", "nd_r")],
    )
    val = _validate(client, manual_id, bad_return)
    assert any(
        p["code"] == "CHANNEL_NODE_CONFIG_INVALID" and p["node_id"] == "nd_r"
        for p in val["problems"]
    )
    _save_and_publish(
        client,
        manual_id,
        _graph([_node("nd_t", "trig", "trigger.manual", "Manual")]),
    )

    sub_a = _create_channel(client, "Sub A")
    sub_b = _create_channel(client, "Sub B")
    _save_and_publish(
        client,
        sub_b,
        _graph(
            [
                _node(
                    "nd_t",
                    "sub_in",
                    "trigger.subchannel",
                    "Sub Trigger",
                    {
                        "input": [
                            {"name": "count", "type": "integer", "required": True}
                        ]
                    },
                )
            ]
        ),
    )

    # Filter GET /channels by published_trigger_type
    listed = client.get(
        "/channels", params={"published_trigger_type": "trigger.subchannel"}
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert [item["id"] for item in items] == [sub_b]
    assert items[0]["latest_version"]["trigger_type"] == "trigger.subchannel"

    # Self-call, non-subchannel target, missing required input, extra input, type mismatch
    check_self = _validate(
        client,
        sub_a,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node(
                    "nd_c",
                    "call_self",
                    "action.call_channel",
                    "Call Self",
                    {"channel_id": sub_a, "inputs": {}},
                ),
            ],
            [_edge("e1", "nd_t", "nd_c")],
        ),
    )
    assert {p["code"] for p in check_self["problems"]} == {
        "CHANNEL_REFERENCE_UNRESOLVED"
    }

    check_wrong_trig = _validate(
        client,
        sub_a,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node(
                    "nd_c",
                    "call_man",
                    "action.call_channel",
                    "Call Manual",
                    {"channel_id": manual_id, "inputs": {}},
                ),
            ],
            [_edge("e1", "nd_t", "nd_c")],
        ),
    )
    assert {p["code"] for p in check_wrong_trig["problems"]} == {
        "CHANNEL_SUBCHANNEL_TRIGGER_REQUIRED"
    }

    check_inputs = _validate(
        client,
        sub_a,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node(
                    "nd_c",
                    "call_b",
                    "action.call_channel",
                    "Call B",
                    {"channel_id": sub_b, "inputs": {"extra": "1"}},
                ),
            ],
            [_edge("e1", "nd_t", "nd_c")],
        ),
    )
    problem_paths = {tuple(p["path"]): p["code"] for p in check_inputs["problems"]}
    assert problem_paths[("inputs", "count")] == "CHANNEL_NODE_CONFIG_INVALID"
    assert problem_paths[("inputs", "extra")] == "CHANNEL_NODE_CONFIG_INVALID"

    check_type = _validate(
        client,
        sub_a,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node(
                    "nd_c",
                    "call_b",
                    "action.call_channel",
                    "Call B",
                    {"channel_id": sub_b, "inputs": {"count": "not_an_int"}},
                ),
            ],
            [_edge("e1", "nd_t", "nd_c")],
        ),
    )
    assert any(
        p["code"] == "CHANNEL_TEMPLATE_TYPE_MISMATCH"
        for p in check_type["problems"]
    )

    # Publish Sub A calling Sub B, then check transitive cycle when Sub B tries to call Sub A
    _save_and_publish(
        client,
        sub_a,
        _graph(
            [
                _node("nd_t", "sub_in", "trigger.subchannel", "Sub Trigger"),
                _node(
                    "nd_c",
                    "call_b",
                    "action.call_channel",
                    "Call B",
                    {"channel_id": sub_b, "inputs": {"count": "10"}},
                ),
            ],
            [_edge("e1", "nd_t", "nd_c")],
        ),
    )
    cycle_val = _validate(
        client,
        sub_b,
        _graph(
            [
                _node(
                    "nd_t",
                    "sub_in",
                    "trigger.subchannel",
                    "Sub Trigger",
                    {
                        "input": [
                            {"name": "count", "type": "integer", "required": True}
                        ]
                    },
                ),
                _node(
                    "nd_c",
                    "call_a",
                    "action.call_channel",
                    "Call A",
                    {"channel_id": sub_a, "inputs": {}},
                ),
            ],
            [_edge("e1", "nd_t", "nd_c")],
        ),
    )
    assert any(
        p["code"] == "CHANNEL_SUBCHANNEL_CYCLE" for p in cycle_val["problems"]
    )

    # CHANNEL_IN_USE guards: cannot delete sub_b or change its trigger away from trigger.subchannel
    del_res = client.delete(f"/channels/{sub_b}")
    assert del_res.status_code == 409
    assert del_res.json()["code"] == "CHANNEL_IN_USE"

    draft_b = client.get(f"/channels/{sub_b}/draft").json()
    saved_b = client.put(
        f"/channels/{sub_b}/draft",
        json={
            "base_revision": draft_b["draft_revision"],
            "graph": _graph([_node("nd_t", "trig", "trigger.manual", "Manual")]),
        },
    )
    assert saved_b.status_code == 200
    pub_b = client.post(
        f"/channels/{sub_b}/publish",
        json={"draft_revision": saved_b.json()["draft_revision"]},
    )
    assert pub_b.status_code == 409
    assert pub_b.json()["code"] == "CHANNEL_IN_USE"


def test_nested_inline_execution_frame_isolation_and_run_links(
    client: TestClient,
) -> None:
    leaf_id = _create_channel(client, "Leaf Sub")
    mid_id = _create_channel(client, "Mid Sub")
    parent_id = _create_channel(client, "Parent Caller")

    get_variable_store().apply(
        operation="set", name="env_tag", value="parent-var", channel_id=parent_id
    )
    get_variable_store().apply(
        operation="set", name="env_tag", value="mid-var", channel_id=mid_id
    )
    get_variable_store().apply(
        operation="set", name="env_tag", value="leaf-var", channel_id=leaf_id
    )

    _save_and_publish(
        client,
        leaf_id,
        _graph(
            [
                _node(
                    "nd_t",
                    "trig",
                    "trigger.subchannel",
                    "Sub Trigger",
                    {"input": [{"name": "x", "type": "integer", "required": True}]},
                ),
                _node(
                    "nd_var",
                    "v",
                    "state.variable",
                    "Read Var",
                    {"scope": "channel", "operation": "get", "name": "env_tag"},
                ),
                _node(
                    "nd_ret",
                    "ret",
                    "action.return",
                    "Return",
                    {
                        "value": "{{ {'doubled': self.trig.output.x * 2, 'leaf_var': self.v.output.value, 'leaf_channel': self.channel.id, 'leaf_run': self.run.id} }}"
                    },
                ),
            ],
            [_edge("e1", "nd_t", "nd_var"), _edge("e2", "nd_var", "nd_ret")],
        ),
    )

    _save_and_publish(
        client,
        mid_id,
        _graph(
            [
                _node(
                    "nd_t",
                    "trig",
                    "trigger.subchannel",
                    "Sub Trigger",
                    {"input": [{"name": "n", "type": "integer", "required": True}]},
                ),
                _node(
                    "nd_var",
                    "v",
                    "state.variable",
                    "Read Var",
                    {"scope": "channel", "operation": "get", "name": "env_tag"},
                ),
                _node(
                    "nd_call",
                    "call_leaf",
                    "action.call_channel",
                    "Call Leaf",
                    {
                        "channel_id": leaf_id,
                        "inputs": {"x": "{{ self.trig.output.n + 1 }}"},
                    },
                ),
                _node(
                    "nd_ret",
                    "ret",
                    "action.return",
                    "Return",
                    {
                        "value": "{{ {'leaf': self.call_leaf.output.result, 'mid_var': self.v.output.value, 'mid_input': self.trig.output.n} }}"
                    },
                ),
            ],
            [
                _edge("e1", "nd_t", "nd_var"),
                _edge("e2", "nd_var", "nd_call"),
                _edge("e3", "nd_call", "nd_ret"),
            ],
        ),
    )

    _save_and_publish(
        client,
        parent_id,
        _graph(
            [
                _node(
                    "nd_t",
                    "trig",
                    "trigger.manual",
                    "Manual",
                    {"payload": {"seed": 5}},
                ),
                _node(
                    "nd_var",
                    "v",
                    "state.variable",
                    "Read Var",
                    {"scope": "channel", "operation": "get", "name": "env_tag"},
                ),
                _node(
                    "nd_call",
                    "call_mid",
                    "action.call_channel",
                    "Call Mid",
                    {
                        "channel_id": mid_id,
                        "inputs": {"n": "{{ self.trig.output.seed }}"},
                    },
                ),
                _node(
                    "nd_after",
                    "summary",
                    "transform.set_fields",
                    "Summary",
                    {
                        "fields": [
                            {
                                "name": "parent_seed",
                                "value": "{{ self.trig.output.seed }}",
                            },
                            {
                                "name": "parent_var",
                                "value": "{{ self.v.output.value }}",
                            },
                            {
                                "name": "parent_channel",
                                "value": "{{ self.channel.id }}",
                            },
                            {
                                "name": "parent_run",
                                "value": "{{ self.run.id }}",
                            },
                            {
                                "name": "mid_result",
                                "value": "{{ self.call_mid.output.result }}",
                            },
                        ]
                    },
                ),
            ],
            [
                _edge("e1", "nd_t", "nd_var"),
                _edge("e2", "nd_var", "nd_call"),
                _edge("e3", "nd_call", "nd_after"),
            ],
        ),
    )

    res = client.post(f"/channels/{parent_id}/runs", json={"target": "published"})
    assert res.status_code == 202, res.text
    parent_run = res.json()["run"]
    assert parent_run["status"] == "succeeded"
    root_job_id = parent_run["job_id"]
    assert parent_run["parent_job_id"] is None
    assert parent_run["root_job_id"] == root_job_id

    execs = client.get(
        f"/channels/{parent_id}/runs/{root_job_id}/executions"
    ).json()["items"]
    by_node = {item["node_id"]: item for item in execs}
    call_out = by_node["nd_call"]["output_preview"]
    summary_out = by_node["nd_after"]["output_preview"]

    assert summary_out["parent_seed"] == 5
    assert summary_out["parent_var"] == "parent-var"
    assert summary_out["parent_channel"] == parent_id
    assert summary_out["parent_run"] == root_job_id
    assert summary_out["mid_result"]["mid_var"] == "mid-var"
    assert summary_out["mid_result"]["mid_input"] == 5
    assert summary_out["mid_result"]["leaf"]["doubled"] == 12
    assert summary_out["mid_result"]["leaf"]["leaf_var"] == "leaf-var"
    assert summary_out["mid_result"]["leaf"]["leaf_channel"] == leaf_id
    assert summary_out["mid_result"]["leaf"]["leaf_run"] != root_job_id

    # Verify child run detail links back to caller
    mid_job_id = call_out["job_id"]
    mid_detail = client.get(f"/channels/{mid_id}/runs/{mid_job_id}").json()["run"]
    assert mid_detail["trigger_kind"] == "subchannel"
    assert mid_detail["parent_job_id"] == root_job_id
    assert mid_detail["root_job_id"] == root_job_id
    assert mid_detail["caller"] == {
        "channel_id": parent_id,
        "channel_name": "Parent Caller",
        "job_id": root_job_id,
        "node_id": "nd_call",
    }


def test_inactive_concurrency_version_consistency_failure_and_dataset_sharing(
    client: TestClient,
) -> None:
    sub_id = _create_channel(client, "Shared Worker Sub")
    parent_id = _create_channel(client, "Loop Parent")

    # v1 multiplies by 10, keep_succeeded_runs=False to verify dataset retention across discard
    _save_and_publish(
        client,
        sub_id,
        _graph(
            [
                _node(
                    "nd_t",
                    "sub_in",
                    "trigger.subchannel",
                    "Sub Trigger",
                    {
                        "input": [
                            {"name": "item", "type": "integer", "required": True},
                            {
                                "name": "rows",
                                "type": "dataset",
                                "required": False,
                            },
                        ]
                    },
                ),
                _node(
                    "nd_ret",
                    "ret",
                    "action.return",
                    "Return",
                    {"value": "{{ self.sub_in.output.item * 10 }}"},
                ),
            ],
            [_edge("e1", "nd_t", "nd_ret")],
            settings={"concurrency": "forbid", "keep_succeeded_runs": False},
        ),
        active=False,
    )

    _save_and_publish(
        client,
        parent_id,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node(
                    "nd_call",
                    "call_sub",
                    "action.call_channel",
                    "Call Sub",
                    {"channel_id": sub_id, "inputs": {"item": "3"}},
                ),
            ],
            [_edge("e1", "nd_t", "nd_call")],
        ),
    )

    # 1. Inactive sub-channel fails caller with CHANNEL_SUBCHANNEL_INACTIVE
    inactive_run = client.post(
        f"/channels/{parent_id}/runs", json={"target": "published"}
    ).json()["run"]
    assert inactive_run["status"] == "failed"
    assert inactive_run["error_code"] == "CHANNEL_SUBCHANNEL_INACTIVE"

    # Activate sub-channel
    client.post(f"/channels/{sub_id}/activate")

    # 2. Concurrency="forbid" returns outcome="skipped" when contended
    held = try_acquire_channel_run_lock(sub_id)
    assert held is not None
    try:
        contended = client.post(
            f"/channels/{parent_id}/runs", json={"target": "published"}
        ).json()["run"]
        assert contended["status"] == "succeeded"
        execs = client.get(
            f"/channels/{parent_id}/runs/{contended['job_id']}/executions"
        ).json()["items"]
        call_exec = next(item for item in execs if item["node_id"] == "nd_call")
        assert call_exec["output_preview"]["outcome"] == "skipped"
        assert call_exec["output_preview"]["result"] is None
    finally:
        held.release()

    # 3. Dataset sharing across root_job_id + foreign dataset rejection
    ds_sub_id = _create_channel(client, "Dataset Sub")
    _save_and_publish(
        client,
        ds_sub_id,
        _graph(
            [
                _node(
                    "nd_t",
                    "sub_in",
                    "trigger.subchannel",
                    "Sub Trigger",
                    {
                        "input": [
                            {"name": "ds", "type": "dataset", "required": True}
                        ]
                    },
                ),
                _node(
                    "nd_ret",
                    "ret",
                    "action.return",
                    "Return",
                    {"value": "{{ self.sub_in.output.ds }}"},
                ),
            ],
            [_edge("e1", "nd_t", "nd_ret")],
            settings={"keep_succeeded_runs": False},
        ),
    )
    seeded_run = client.post(
        f"/channels/{parent_id}/runs", json={"target": "published"}
    ).json()["run"]
    root_id = seeded_run["job_id"]
    ds_rec = DatasetRecord(
        id="ds_shared_test",
        job_id=root_id,
        root_job_id=root_id,
        node_id="nd_t",
        seq=1,
        relation="channel_datasets.ds_shared_test",
        columns=[{"name": "id", "normalized_type": "integer", "nullable": False}],
        row_count=2,
        size_bytes=64,
        status="ready",
        created_at=utc_now(),
        expires_at=None,
    )
    get_dataset_store().save(ds_rec)
    ds_ref = dataset_reference(
        dataset_id=ds_rec.id, columns=ds_rec.columns, count=2
    )

    caller2 = _create_channel(client, "Dataset Caller")
    _save_and_publish(
        client,
        caller2,
        _graph(
            [
                _node(
                    "nd_t",
                    "trig",
                    "trigger.manual",
                    "Manual",
                    {"payload": {"ds": ds_ref}},
                ),
                _node(
                    "nd_c",
                    "call_ds",
                    "action.call_channel",
                    "Call DS",
                    {
                        "channel_id": ds_sub_id,
                        "inputs": {"ds": "{{ self.trig.output.ds }}"},
                    },
                ),
            ],
            [_edge("e1", "nd_t", "nd_c")],
        ),
    )
    foreign = client.post(
        f"/channels/{caller2}/runs", json={"target": "published"}
    ).json()["run"]
    assert foreign["status"] == "failed"
    assert foreign["error_code"] == "CHANNEL_SUBCHANNEL_INPUT_INVALID"

    # 4. Run-consistent version resolution mid-loop: publish v2 while loop executes!
    loop_caller = _create_channel(client, "Mid-loop Version Consistency")
    _save_and_publish(
        client,
        loop_caller,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node(
                    "nd_for",
                    "loop",
                    "volume.for",
                    "For",
                    {"items": "{{ [1, 2, 3] }}"},
                ),
                _node(
                    "nd_call",
                    "call_sub",
                    "action.call_channel",
                    "Call Sub",
                    {
                        "channel_id": sub_id,
                        "inputs": {"item": "{{ self.loop.output.current }}"},
                    },
                    parent="nd_for",
                ),
            ],
            [
                _edge("e1", "nd_t", "nd_for"),
                _edge("e2", "nd_for", "nd_call", source_port="each"),
            ],
        ),
    )

    orig_list_versions = get_channel_store().list_versions
    published_mid_loop = False

    def _publish_v2_after_first(channel_id: str, *, limit: int, offset: int):
        nonlocal published_mid_loop
        result = orig_list_versions(channel_id, limit=limit, offset=offset)
        if channel_id == sub_id and not published_mid_loop:
            published_mid_loop = True
            draft = get_channel_store().get(sub_id)
            assert draft is not None
            v2_graph = _graph(
                [
                    _node(
                        "nd_t",
                        "sub_in",
                        "trigger.subchannel",
                        "Sub Trigger",
                        {
                            "input": [
                                {"name": "item", "type": "integer", "required": True}
                            ]
                        },
                    ),
                    _node(
                        "nd_ret",
                        "ret",
                        "action.return",
                        "Return",
                        {"value": "{{ self.sub_in.output.item * 999 }}"},
                    ),
                ],
                [_edge("e1", "nd_t", "nd_ret")],
            )
            get_channel_store().replace_draft(
                sub_id,
                base_revision=draft.draft_revision,
                graph=v2_graph,
                now=utc_now(),
            )
            updated = get_channel_store().get(sub_id)
            assert updated is not None
            get_channel_store().publish_version(
                sub_id,
                draft_revision=updated.draft_revision,
                published_at=utc_now(),
                published_by_user_id="usr_system",
            )
        return result

    store = get_channel_store()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(store, "list_versions", _publish_v2_after_first)
    try:
        loop_run = client.post(
            f"/channels/{loop_caller}/runs", json={"target": "published"}
        ).json()["run"]
    finally:
        monkey.undo()

    assert loop_run["status"] == "succeeded"
    loop_execs = client.get(
        f"/channels/{loop_caller}/runs/{loop_run['job_id']}/executions"
    ).json()["items"]
    call_execs = [item for item in loop_execs if item["node_id"] == "nd_call"]
    assert [item["output_preview"]["version"] for item in call_execs] == [1, 1, 1]
    assert [item["output_preview"]["result"] for item in call_execs] == [10, 20, 30]

    # Next fresh root run picks up v2 automatically!
    loop_run_v2 = client.post(
        f"/channels/{loop_caller}/runs", json={"target": "published"}
    ).json()["run"]
    assert loop_run_v2["status"] == "succeeded"
    loop_execs_v2 = client.get(
        f"/channels/{loop_caller}/runs/{loop_run_v2['job_id']}/executions"
    ).json()["items"]
    call_execs_v2 = [item for item in loop_execs_v2 if item["node_id"] == "nd_call"]
    assert [item["output_preview"]["version"] for item in call_execs_v2] == [2, 2, 2]
    assert [item["output_preview"]["result"] for item in call_execs_v2] == [
        999,
        1998,
        2997,
    ]


def test_child_failure_streak_rerun_and_max_depth(client: TestClient) -> None:
    flaky_sub = _create_channel(client, "Flaky Sub")
    _save_and_publish(
        client,
        flaky_sub,
        _graph(
            [
                _node(
                    "nd_t",
                    "sub_in",
                    "trigger.subchannel",
                    "Sub Trigger",
                    {
                        "input": [
                            {"name": "boom", "type": "boolean", "required": True}
                        ]
                    },
                ),
                _node(
                    "nd_code",
                    "work",
                    "transform.code",
                    "Work",
                    {
                        "code": "if self.sub_in.output.boom:\n    raise ValueError('boom!')\nreturn {'ok': True}"
                    },
                ),
                _node(
                    "nd_ret",
                    "ret",
                    "action.return",
                    "Return",
                    {"value": "{{ self.work.output }}"},
                ),
            ],
            [
                _edge("e1", "nd_t", "nd_code"),
                _edge("e2", "nd_code", "nd_ret"),
            ],
        ),
    )

    caller = _create_channel(client, "Flaky Caller")
    _save_and_publish(
        client,
        caller,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node(
                    "nd_c",
                    "call_flaky",
                    "action.call_channel",
                    "Call Flaky",
                    {"channel_id": flaky_sub, "inputs": {"boom": "true"}},
                ),
            ],
            [_edge("e1", "nd_t", "nd_c")],
        ),
    )

    failed_parent = client.post(
        f"/channels/{caller}/runs", json={"target": "published"}
    ).json()["run"]
    assert failed_parent["status"] == "failed"
    assert failed_parent["error_code"] == "CHANNEL_SUBCHANNEL_FAILED"
    assert client.get(f"/channels/{flaky_sub}").json()["channel"][
        "failure_streak"
    ] == 1

    execs = client.get(
        f"/channels/{caller}/runs/{failed_parent['job_id']}/executions"
    ).json()["items"]
    call_exec = next(item for item in execs if item["node_id"] == "nd_c")
    detail = call_exec["error_detail"]
    assert detail["channel_id"] == flaky_sub
    assert detail["failed_node_id"] == "nd_code"
    child_job_id = detail["job_id"]

    # Rerun failed subchannel run directly preserves subchannel_input
    rerun = client.post(
        f"/channels/{flaky_sub}/runs/{child_job_id}/rerun"
    )
    assert rerun.status_code == 202, rerun.text
    assert rerun.json()["run"]["status"] == "failed"
    assert client.get(f"/channels/{flaky_sub}").json()["channel"][
        "failure_streak"
    ] == 2

    # MAX_SUBCHANNEL_CALL_DEPTH (8 nested sub-channels allowed; 9th fails with CHANNEL_SUBCHANNEL_DEPTH_EXCEEDED)
    chain_ids = [_create_channel(client, f"Depth {idx}") for idx in range(10)]
    _save_and_publish(
        client,
        chain_ids[-1],
        _graph(
            [
                _node("nd_t", "sub_in", "trigger.subchannel", "Sub Trigger"),
                _node("nd_r", "ret", "action.return", "Return", {"value": "{{ 1 }}"}),
            ],
            [_edge("e1", "nd_t", "nd_r")],
        ),
    )
    for idx in range(len(chain_ids) - 2, 0, -1):
        _save_and_publish(
            client,
            chain_ids[idx],
            _graph(
                [
                    _node("nd_t", "sub_in", "trigger.subchannel", "Sub Trigger"),
                    _node(
                        "nd_c",
                        "next_sub",
                        "action.call_channel",
                        "Next",
                        {"channel_id": chain_ids[idx + 1], "inputs": {}},
                    ),
                ],
                [_edge("e1", "nd_t", "nd_c")],
            ),
        )
    _save_and_publish(
        client,
        chain_ids[0],
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node(
                    "nd_c",
                    "first_sub",
                    "action.call_channel",
                    "First",
                    {"channel_id": chain_ids[1], "inputs": {}},
                ),
            ],
            [_edge("e1", "nd_t", "nd_c")],
        ),
    )
    deep_run = client.post(
        f"/channels/{chain_ids[0]}/runs", json={"target": "published"}
    ).json()["run"]
    assert deep_run["status"] == "failed"
    deep_execs = client.get(
        f"/channels/{chain_ids[8]}/runs"
    ).json()["items"]
    assert deep_execs[0]["error_code"] == "CHANNEL_SUBCHANNEL_DEPTH_EXCEEDED"


def test_templated_entity_id_change_reader_in_parameterized_notification_subchannel(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replays the ISC-style parameterized incremental notification sub-channel pattern."""
    absent = HistorySide(state="absent", values=None)
    fake_events_by_entity: dict[str, list[IncrementalEvent]] = {
        "ent_capacity": [
            IncrementalEvent(
                sequence=11,
                commit_seq=11,
                operation="create",
                occurred_at="2026-08-15T02:00:00Z",
                source="user",
                subject="usr_1",
                physical_table="entity_data.ent_capacity_v1",
                version_id="ver_1",
                version_number=1,
                before=absent,
                after=HistorySide(
                    state="visible", values={"code": "L1", "qty": 100}
                ),
                business_key_name="code",
            )
        ],
        "ent_inventory": [
            IncrementalEvent(
                sequence=42,
                commit_seq=42,
                operation="update",
                occurred_at="2026-08-15T02:01:00Z",
                source="user",
                subject="usr_1",
                physical_table="entity_data.ent_inventory_v1",
                version_id="ver_2",
                version_number=1,
                before=HistorySide(
                    state="visible", values={"sku": "S9", "qty": 5}
                ),
                after=HistorySide(
                    state="visible", values={"sku": "S9", "qty": 9}
                ),
                business_key_name="sku",
            )
        ],
    }

    class _Opened:
        def __init__(self, entity_id: str, node_id: str, after_seq: int | None):
            self.entity_id = entity_id
            self.node_id = node_id
            self.after_seq = after_seq

    class _Page:
        def __init__(self, events: list[IncrementalEvent]):
            self.events = events
            self.has_more = False
            self.progress = (
                IncrementalPosition(
                    commit_seq=events[-1].commit_seq, seq=events[-1].sequence
                )
                if events
                else None
            )

    def _fake_open(
        entity_id: str,
        node_id: str,
        session: Any,
        *,
        ignore_checkpoints: bool = False,
    ):
        stored = None if ignore_checkpoints else session.stored(node_id, entity_id)
        after_seq = stored.seq if stored is not None else None
        return _Opened(entity_id, node_id, after_seq)

    def _fake_read(opened: _Opened, *, limit: int):
        del limit
        items = [
            ev
            for ev in fake_events_by_entity.get(opened.entity_id, [])
            if opened.after_seq is None or ev.sequence > opened.after_seq
        ]
        return _Page(items)

    monkeypatch.setattr(
        "backend.channel.nodes.read.changes.open_change_range", _fake_open
    )
    monkeypatch.setattr(
        "backend.channel.nodes.read.changes.read_change_range", _fake_read
    )

    notify_sub = _create_channel(client, "ISC Incremental Notify Sub")
    _save_and_publish(
        client,
        notify_sub,
        _graph(
            [
                _node(
                    "nd_t",
                    "sub_in",
                    "trigger.subchannel",
                    "Sub Trigger",
                    {
                        "input": [
                            {
                                "name": "entity_id",
                                "type": "string",
                                "required": True,
                            },
                            {
                                "name": "routing_key",
                                "type": "string",
                                "required": True,
                            },
                        ]
                    },
                ),
                _node(
                    "nd_chg",
                    "changes",
                    "read.changes",
                    "Read Entity Changes",
                    {
                        "entity_id": "{{ self.sub_in.output.entity_id }}",
                        "shape": "entries",
                    },
                ),
                _node(
                    "nd_ret",
                    "ret",
                    "action.return",
                    "Return",
                    {
                        "value": "{{ {'routing_key': self.sub_in.output.routing_key, 'sent': self.changes.output.count, 'last_seq': self.changes.output.last_sequence} }}"
                    },
                ),
            ],
            [
                _edge("e1", "nd_t", "nd_chg"),
                _edge("e2", "nd_chg", "nd_ret"),
            ],
        ),
    )

    cap_channel = _create_channel(client, "MES ISC Capacity Load")
    inv_channel = _create_channel(client, "MES ISC Inventory")
    for cid, ent_id, rkey in [
        (cap_channel, "ent_capacity", "isc.capacity"),
        (inv_channel, "ent_inventory", "isc.inventory"),
    ]:
        _save_and_publish(
            client,
            cid,
            _graph(
                [
                    _node("nd_t", "trig", "trigger.manual", "Manual"),
                    _node(
                        "nd_push",
                        "push",
                        "action.call_channel",
                        "Push to ISC",
                        {
                            "channel_id": notify_sub,
                            "inputs": {
                                "entity_id": ent_id,
                                "routing_key": rkey,
                            },
                        },
                    ),
                ],
                [_edge("e1", "nd_t", "nd_push")],
            ),
        )

    # Run 1 on cap_channel -> sees 1 change (seq 11) and advances checkpoint on (notify_sub, nd_chg, ent_capacity)
    r1 = client.post(
        f"/channels/{cap_channel}/runs", json={"target": "published"}
    ).json()["run"]
    assert r1["status"] == "succeeded"
    e1 = client.get(
        f"/channels/{cap_channel}/runs/{r1['job_id']}/executions"
    ).json()["items"]
    assert next(x for x in e1 if x["node_id"] == "nd_push")["output_preview"][
        "result"
    ] == {"routing_key": "isc.capacity", "sent": 1, "last_seq": 11}

    # Run 2 on cap_channel -> checkpoint already at seq 11 -> sent == 0!
    r2 = client.post(
        f"/channels/{cap_channel}/runs", json={"target": "published"}
    ).json()["run"]
    e2 = client.get(
        f"/channels/{cap_channel}/runs/{r2['job_id']}/executions"
    ).json()["items"]
    assert next(x for x in e2 if x["node_id"] == "nd_push")["output_preview"][
        "result"
    ] == {"routing_key": "isc.capacity", "sent": 0, "last_seq": None}

    # Run 1 on inv_channel -> independent per-entity stream on same subchannel -> sees 1 change (seq 42)!
    r3 = client.post(
        f"/channels/{inv_channel}/runs", json={"target": "published"}
    ).json()["run"]
    e3 = client.get(
        f"/channels/{inv_channel}/runs/{r3['job_id']}/executions"
    ).json()["items"]
    assert next(x for x in e3 if x["node_id"] == "nd_push")["output_preview"][
        "result"
    ] == {"routing_key": "isc.inventory", "sent": 1, "last_seq": 42}


def test_review_regressions_supervised_claim_order_cancel_contract_and_reaper(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.channel.nodes.trigger.subchannel import NODE_TYPE as SUB_TRIGGER
    from backend.channel.references import ChannelReferenceResolver
    from backend.channel.run_store import ChannelRunRecord, get_run_store
    from backend.channel.tasks import settle_orphaned_subchannel_runs
    from backend.core.time import utc_now
    from backend.jobs.store import (
        CLAIMED_ENV,
        claim_queued,
        create_queued_job,
        get_job_store,
        mark_cancelled,
        mark_failed,
    )

    # 1. trigger.subchannel maxItems == 100, leading '_' and Python keywords allowed, non-ASCII rejected,
    #    and _refine required lists only required or default-bearing parameters.
    assert SUB_TRIGGER.config_schema["properties"]["input"]["maxItems"] == 100
    sub_id = _create_channel(client, "Contract & Supervised Sub")
    invalid_unicode = _validate(
        client,
        sub_id,
        _graph(
            [
                _node(
                    "nd_t",
                    "trig",
                    "trigger.subchannel",
                    "Sub Trigger",
                    {
                        "input": [
                            {
                                "name": chr(0x4E2D) + chr(0x6587),
                                "type": "string",
                                "required": True,
                            }
                        ]
                    },
                )
            ]
        ),
    )
    assert invalid_unicode["valid"] is False

    sub_graph = _graph(
        [
            _node(
                "nd_t",
                "trig",
                "trigger.subchannel",
                "Sub Trigger",
                {
                    "input": [
                        {"name": "_cursor", "type": "integer", "required": True},
                        {"name": "from", "type": "string", "required": False, "default": "erp"},
                        {"name": "note", "type": "string", "required": False},
                    ],
                    "sample_input": {"_cursor": 7},
                },
            ),
            _node(
                "nd_r",
                "ret",
                "action.return",
                "Return",
                {
                    "value": "{{ {'c': self.trig.output._cursor, 'src': self.trig.output['from'], 'note': self.trig.output.note} }}"
                },
            ),
        ],
        [_edge("e1", "nd_t", "nd_r")],
    )
    valid_check = _validate(client, sub_id, sub_graph)
    assert valid_check["valid"] is True
    trig_port = next(
        p
        for p in valid_check["ports"]
        if p["node_id"] == "nd_t" and p["direction"] == "output" and p["port"] == "main"
    )
    assert trig_port["schema"]["required"] == ["_cursor", "from"]
    _save_and_publish(client, sub_id, sub_graph, active=True)

    contract = ChannelReferenceResolver("chn_caller").published_subchannel_contract(sub_id)
    assert contract is not None
    assert [p.name for p in contract.inputs] == ["_cursor", "from", "note"]

    # 2. Execution order: inactive check runs BEFORE input template type check;
    #    active runtime input type mismatch returns CHANNEL_SUBCHANNEL_INPUT_INVALID (not CHANNEL_VALUE_TYPE_MISMATCH).
    caller_id = _create_channel(client, "Supervised Caller")
    _save_and_publish(
        client,
        caller_id,
        _graph(
            [
                _node(
                    "nd_t",
                    "trig",
                    "trigger.manual",
                    "Manual",
                    {"payload": {"raw_cursor": "not_an_int"}},
                ),
                _node(
                    "nd_call",
                    "call_sub",
                    "action.call_channel",
                    "Call Sub",
                    {
                        "channel_id": sub_id,
                        "inputs": {"_cursor": "{{ self.trig.output.raw_cursor }}"},
                    },
                ),
            ],
            [_edge("e1", "nd_t", "nd_call")],
        ),
    )
    client.post(f"/channels/{sub_id}/deactivate")
    inactive_run = client.post(
        f"/channels/{caller_id}/runs", json={"target": "published"}
    ).json()["run"]
    assert inactive_run["status"] == "failed"
    assert inactive_run["error_code"] == "CHANNEL_SUBCHANNEL_INACTIVE"

    client.post(f"/channels/{sub_id}/activate")
    bad_input_run = client.post(
        f"/channels/{caller_id}/runs", json={"target": "published"}
    ).json()["run"]
    assert bad_input_run["status"] == "failed"
    assert bad_input_run["error_code"] == "CHANNEL_SUBCHANNEL_INPUT_INVALID"

    # 3. Supervised worker mode (CLAIMED_ENV="1"): parent job is pre-claimed by supervisor,
    #    while child subchannel job is freshly queued and claimed via claim_queued.
    good_caller_id = _create_channel(client, "Good Supervised Caller")
    _save_and_publish(
        client,
        good_caller_id,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual", {"payload": {"n": 12}}),
                _node(
                    "nd_call",
                    "call_sub",
                    "action.call_channel",
                    "Call Sub",
                    {
                        "channel_id": sub_id,
                        "inputs": {"_cursor": "{{ self.trig.output.n }}"},
                    },
                ),
            ],
            [_edge("e1", "nd_t", "nd_call")],
        ),
    )

    def _supervised_dispatch(job_id: str) -> dict[str, str]:
        claim_queued(job_id, claimed_by="worker-supervised")
        monkeypatch.setenv(CLAIMED_ENV, "1")
        try:
            return run_channel_job(job_id)
        finally:
            monkeypatch.delenv(CLAIMED_ENV, raising=False)

    prev = set_dispatcher(_supervised_dispatch)
    try:
        sup_res = client.post(
            f"/channels/{good_caller_id}/runs", json={"target": "published"}
        )
        assert sup_res.status_code == 202, sup_res.text
        sup_run = sup_res.json()["run"]
        assert sup_run["status"] == "succeeded"
        execs = client.get(
            f"/channels/{good_caller_id}/runs/{sup_run['job_id']}/executions"
        ).json()["items"]
        call_out = next(x for x in execs if x["node_id"] == "nd_call")["output_preview"]
        assert call_out["result"] == {"c": 12, "src": "erp", "note": None}
    finally:
        set_dispatcher(prev)

    # 4. Parent cancel stops parent as 'cancelled' (even with on_error='continue'),
    #    whereas direct child cancel fails action.call_channel with reason='cancelled'.
    cancel_sub = _create_channel(client, "Cancelable Sub")
    _save_and_publish(
        client,
        cancel_sub,
        _graph(
            [
                _node("nd_t", "trig", "trigger.subchannel", "Sub Trigger", {"input": []}),
                _node(
                    "nd_code",
                    "step",
                    "transform.code",
                    "Step",
                    {"code": "return {'ok': True}"},
                ),
            ],
            [_edge("e1", "nd_t", "nd_code")],
        ),
    )
    cancel_parent = _create_channel(client, "Cancelable Parent")
    _save_and_publish(
        client,
        cancel_parent,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node(
                    "nd_call",
                    "call_sub",
                    "action.call_channel",
                    "Call Sub",
                    {"channel_id": cancel_sub, "inputs": {}},
                    on_error="continue",
                ),
                _node(
                    "nd_after",
                    "after",
                    "transform.set_fields",
                    "After",
                    {"fields": [{"name": "ran", "value": "true"}]},
                ),
            ],
            [_edge("e1", "nd_t", "nd_call"), _edge("e2", "nd_call", "nd_after")],
        ),
    )

    orig_exec_sub = __import__(
        "backend.channel.channel_run", fromlist=["execute_subchannel_graph"]
    ).execute_subchannel_graph

    mode = {"which": "parent"}

    def _cancel_hook(**kwargs: Any) -> Any:
        child_job = kwargs["job"]
        parent_hooks = kwargs["parent_hooks"]
        if mode["which"] == "parent":
            mark_cancelled(parent_hooks.run_id)
        else:
            mark_cancelled(child_job.id)
        return orig_exec_sub(**kwargs)

    monkeypatch.setattr(
        "backend.channel.channel_run.execute_subchannel_graph", _cancel_hook
    )

    p_cancel = client.post(
        f"/channels/{cancel_parent}/runs", json={"target": "published"}
    ).json()["run"]
    assert p_cancel["status"] == "cancelled"

    mode["which"] = "child_only"
    # Switch on_error to stop on a second caller so we inspect failed error_detail.reason == 'cancelled'
    child_cancel_caller = _create_channel(client, "Child Only Cancel Caller")
    _save_and_publish(
        client,
        child_cancel_caller,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node(
                    "nd_call",
                    "call_sub",
                    "action.call_channel",
                    "Call Sub",
                    {"channel_id": cancel_sub, "inputs": {}},
                ),
            ],
            [_edge("e1", "nd_t", "nd_call")],
        ),
    )
    c_cancel = client.post(
        f"/channels/{child_cancel_caller}/runs", json={"target": "published"}
    ).json()["run"]
    assert c_cancel["status"] == "failed"
    assert c_cancel["error_code"] == "CHANNEL_SUBCHANNEL_FAILED"
    c_execs = client.get(
        f"/channels/{child_cancel_caller}/runs/{c_cancel['job_id']}/executions"
    ).json()["items"]
    call_exec = next(x for x in c_execs if x["node_id"] == "nd_call")
    assert call_exec["error_detail"]["reason"] == "cancelled"
    monkeypatch.setattr(
        "backend.channel.channel_run.execute_subchannel_graph", orig_exec_sub
    )

    # 5. Reaper orphan settlement marks both queued and running child jobs JOB_WORKER_LOST.
    now = utc_now()
    root_job = create_queued_job(kind="channel_run", trigger_kind="user", input={})
    claim_queued(root_job.id, claimed_by="dead-worker")
    queued_child = create_queued_job(
        kind="channel_run", trigger_kind="subchannel", trigger_ref=root_job.id, input={}
    )
    running_child = create_queued_job(
        kind="channel_run", trigger_kind="subchannel", trigger_ref=root_job.id, input={}
    )
    claim_queued(running_child.id, claimed_by="dead-worker")
    rstore = get_run_store()
    for jid, pid in [
        (root_job.id, None),
        (queued_child.id, root_job.id),
        (running_child.id, root_job.id),
    ]:
        rstore.insert_run(
            ChannelRunRecord(
                job_id=jid,
                channel_id=sub_id,
                target="published",
                version=1,
                draft_revision=None,
                graph=None,
                trigger_node_id="nd_t",
                ignore_checkpoints=False,
                outcome=None,
                failed_node_id=None,
                skipped_node_ids=[],
                created_at=now,
                parent_job_id=pid,
                root_job_id=root_job.id,
            )
        )
    mark_failed(
        root_job.id,
        error_code="JOB_WORKER_LOST",
        error_summary="Worker lost: occupancy declaration stale",
    )
    settle_orphaned_subchannel_runs(root_job.id)
    q_after = get_job_store().get(queued_child.id)
    r_after = get_job_store().get(running_child.id)
    assert q_after is not None and q_after.status == "failed" and q_after.error_code == "JOB_WORKER_LOST"
    assert r_after is not None and r_after.status == "failed" and r_after.error_code == "JOB_WORKER_LOST"

    # 6. Null on default-bearing or required param is rejected (not converted to None -> CHANNEL_OUTPUT_SCHEMA_MISMATCH).
    null_sample = _validate(
        client,
        sub_id,
        _graph(
            [
                _node(
                    "nd_t",
                    "trig",
                    "trigger.subchannel",
                    "Sub Trigger",
                    {
                        "input": [
                            {"name": "req", "type": "string", "required": True},
                            {"name": "opt_def", "type": "string", "required": False, "default": "abc"},
                        ],
                        "sample_input": {"req": None, "opt_def": None},
                    },
                )
            ]
        ),
    )
    assert null_sample["valid"] is False
    assert {tuple(p["path"]) for p in null_sample["problems"]} >= {
        ("sample_input", "req"),
        ("sample_input", "opt_def"),
    }

    # 7. Timeout convergence: parent run_timeout_sec tighter than child stops child with CHANNEL_RUN_TIMEOUT.
    slow_sub = _create_channel(client, "Slow Sub")
    _save_and_publish(
        client,
        slow_sub,
        _graph(
            [
                _node("nd_t", "trig", "trigger.subchannel", "Sub Trigger", {"input": []}),
                _node("nd_c1", "s1", "transform.code", "Step 1", {"code": "return {'ok': 1}"}),
                _node("nd_c2", "s2", "transform.code", "Step 2", {"code": "return {'ok': 2}"}),
            ],
            [_edge("e1", "nd_t", "nd_c1"), _edge("e2", "nd_c1", "nd_c2")],
            settings={"run_timeout_sec": 60},
        ),
    )
    tight_parent = _create_channel(client, "Tight Parent")
    _save_and_publish(
        client,
        tight_parent,
        _graph(
            [
                _node("nd_t", "trig", "trigger.manual", "Manual"),
                _node("nd_call", "call_sub", "action.call_channel", "Call", {"channel_id": slow_sub, "inputs": {}}),
            ],
            [_edge("e1", "nd_t", "nd_call")],
            settings={"run_timeout_sec": 1},
        ),
    )
    observed_timeouts: list[float | None] = []

    def _timeout_probe(**kwargs: Any) -> Any:
        observed_timeouts.append(kwargs.get("timeout_sec"))
        kwargs["started"] = kwargs["started"] - 2.0
        return orig_exec_sub(**kwargs)

    monkeypatch.setattr(
        "backend.channel.channel_run.execute_subchannel_graph", _timeout_probe
    )
    timeout_run = client.post(
        f"/channels/{tight_parent}/runs", json={"target": "published"}
    ).json()["run"]
    assert observed_timeouts and observed_timeouts[0] is not None and observed_timeouts[0] <= 1.0
    assert timeout_run["status"] == "failed"
    assert timeout_run["error_code"] == "CHANNEL_SUBCHANNEL_FAILED"
    t_execs = client.get(
        f"/channels/{tight_parent}/runs/{timeout_run['job_id']}/executions"
    ).json()["items"]
    t_call = next(x for x in t_execs if x["node_id"] == "nd_call")
    assert t_call["error_detail"]["error_code"] == "CHANNEL_RUN_TIMEOUT"

    # 8. drop_datasets_for_due_runs drops unkept child datasets anchored to root_job_id;
    #    run list omits caller/return_value while run detail includes them.
    from datetime import timedelta
    from backend.channel.dataset_registry import DatasetRecord, drop_datasets_for_due_runs, get_dataset_store

    due_root = create_queued_job(kind="channel_run", trigger_kind="user", input={})
    mark_failed(due_root.id, error_code="CHANNEL_NODE_FAILED", error_summary="boom")
    old_time = now - timedelta(days=10)
    rstore.insert_run(
        ChannelRunRecord(
            job_id=due_root.id,
            channel_id=tight_parent,
            target="published",
            version=1,
            draft_revision=None,
            graph=None,
            trigger_node_id="nd_t",
            ignore_checkpoints=False,
            outcome=None,
            failed_node_id=None,
            skipped_node_ids=[],
            created_at=old_time,
            root_job_id=due_root.id,
        )
    )
    get_dataset_store().save(
        DatasetRecord(
            id="ds_orphan_child_due",
            job_id="job_unkept_child_gone",
            root_job_id=due_root.id,
                node_id="nd_ds",
                seq=1,
                relation='"channel_dataset"."ds_orphan_child_due"',
                columns=[],
            row_count=0,
            size_bytes=0,
            status="ready",
            created_at=old_time,
        )
    )
    drop_datasets_for_due_runs(now - timedelta(days=1))
    ds_after = get_dataset_store().get("ds_orphan_child_due")
    assert ds_after is not None and ds_after.status == "dropped"

    sub_runs_list = client.get(f"/channels/{sub_id}/runs").json()["items"]
    sub_run_item = next(
        x
        for x in sub_runs_list
        if x["trigger_kind"] == "subchannel" and x["status"] == "succeeded"
    )
    assert sub_run_item["caller"] is None
    sub_run_detail = client.get(f"/channels/{sub_id}/runs/{sub_run_item['job_id']}").json()["run"]
    assert sub_run_detail["caller"] is not None
    assert sub_run_detail["return_value"] == {"c": 12, "src": "erp", "note": None}
    # Unused import guard check: mark_cancelled stays importable for cancel tree tests
    assert callable(mark_cancelled)
