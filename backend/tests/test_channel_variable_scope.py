"""Variable scopes: site, channel, and one run."""

from __future__ import annotations

from jsonschema import Draft202012Validator

from backend.channel.graph import validate
from backend.channel.nodes.state.variable import NODE_TYPE, _execute
from backend.channel.variables import get_variable_store
from backend.tests.channel_hooks_fake import FakeHooks
from backend.tests.test_channel_graph import FakeResolver, _edge, _graph, _node


def _var(config: dict) -> dict:
    return {
        "id": "nd_var",
        "ref": "var",
        "type": "state.variable",
        "name": "Var",
        "config": config,
    }


def _set(name: str, value: str, **extra: object) -> dict:
    return {"operation": "set", "name": name, "value": value, **extra}


def test_omitted_scope_writes_the_site() -> None:
    hooks = FakeHooks(channel_id="chn_a")
    result = _execute(_var(_set("lease", '{"held": true}')), hooks)
    assert result.status == "succeeded"
    stored = get_variable_store().apply(operation="get", name="lease")
    assert stored.found is True
    assert stored.value == {"held": True}
    assert get_variable_store().list_live(limit=50, offset=0, channel_id="chn_a")[1] == 0


def test_null_scope_fails_without_a_write() -> None:
    hooks = FakeHooks(channel_id="chn_a")
    result = _execute(_var(_set("flag", "true", scope=None)), hooks)
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert get_variable_store().apply(operation="get", name="flag").found is False
    assert get_variable_store().list_live(limit=50, offset=0, channel_id="chn_a")[1] == 0


def test_null_scope_fails_validation() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_var",
                "state.variable",
                "Var",
                {"operation": "get", "name": "lease", "scope": None},
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_var")],
    )
    problems = validate(graph, FakeResolver())
    matched = [item for item in problems if item.code == "CHANNEL_NODE_CONFIG_INVALID"]
    assert any(item.path == ("scope",) for item in matched)


def test_unknown_scope_fails_without_a_site_write() -> None:
    hooks = FakeHooks(channel_id="chn_a")
    result = _execute(_var(_set("lease", "1", scope="workspace")), hooks)
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert get_variable_store().apply(operation="get", name="lease").found is False


def test_unknown_scope_fails_validation() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_var",
                "state.variable",
                "Var",
                {"operation": "get", "name": "lease", "scope": "workspace"},
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_var")],
    )
    problems = validate(graph, FakeResolver())
    assert any(item.code == "CHANNEL_NODE_CONFIG_INVALID" for item in problems)


def test_channel_values_are_isolated_and_shared_by_channel_id() -> None:
    left = FakeHooks(channel_id="chn_left")
    right = FakeHooks(channel_id="chn_right")
    again = FakeHooks(channel_id="chn_left")
    assert _execute(_var(_set("cursor", "1", scope="channel")), left).status == "succeeded"
    assert _execute(_var(_set("cursor", "2", scope="channel")), right).status == "succeeded"
    read = _execute(
        _var({"operation": "get", "name": "cursor", "scope": "channel"}),
        again,
    )
    assert read.output["value"] == 1
    site = get_variable_store().apply(operation="get", name="cursor")
    assert site.found is False


def test_channel_conditional_write_does_not_replace_a_live_value() -> None:
    hooks = FakeHooks(channel_id="chn_a")
    assert (
        _execute(
            _var(
                {
                    "operation": "set_if_absent",
                    "name": "once",
                    "value": "1",
                    "scope": "channel",
                }
            ),
            hooks,
        ).output["applied"]
        is True
    )
    second = _execute(
        _var(
            {
                "operation": "set_if_absent",
                "name": "once",
                "value": "2",
                "scope": "channel",
            }
        ),
        hooks,
    )
    assert second.output["applied"] is False
    assert second.output["value"] == 1


def test_a_failed_run_leaves_the_channel_value() -> None:
    hooks = FakeHooks(channel_id="chn_a")
    assert _execute(_var(_set("mark", '"kept"', scope="channel")), hooks).status == "succeeded"
    stored = get_variable_store().apply(
        operation="get", name="mark", channel_id="chn_a"
    )
    assert stored.value == "kept"


def test_run_value_stays_in_that_execution() -> None:
    first = FakeHooks(channel_id="chn_a")
    second = FakeHooks(channel_id="chn_a")
    assert _execute(_var(_set("step", "1", scope="run")), first).status == "succeeded"
    read = _execute(_var({"operation": "get", "name": "step", "scope": "run"}), first)
    assert read.output["found"] is True
    assert read.output["expires_at"] is None
    retry = _execute(_var({"operation": "get", "name": "step", "scope": "run"}), second)
    assert retry.output["found"] is False
    assert get_variable_store().apply(operation="get", name="step").found is False
    assert get_variable_store().list_live(limit=50, offset=0, channel_id="chn_a")[1] == 0


def test_run_expiry_fails_and_writes_nothing() -> None:
    hooks = FakeHooks(channel_id="chn_a")
    result = _execute(_var(_set("step", "1", scope="run", ttl_sec=5)), hooks)
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_NODE_FAILED"
    assert hooks.run_variables == {}
    errors = list(
        Draft202012Validator(NODE_TYPE.config_schema).iter_errors(
            {"operation": "set", "name": "step", "value": "1", "scope": "run", "ttl_sec": 5}
        )
    )
    assert errors


def test_container_rounds_share_the_run_value() -> None:
    hooks = FakeHooks(channel_id="chn_a")
    assert _execute(_var(_set("step", "1", scope="run")), hooks).status == "succeeded"
    read = _execute(_var({"operation": "get", "name": "step", "scope": "run"}), hooks)
    assert read.output["value"] == 1
