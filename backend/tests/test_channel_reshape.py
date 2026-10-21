"""Execute for Set Fields, If, Filter, Merge, Deduplicate, and For."""

from __future__ import annotations

import pytest

from backend.channel.nodes import list_node_types
from backend.tests.channel_hooks_fake import FakeHooks


def _run(type_id: str):
    return next(item.execute for item in list_node_types() if item.type_id == type_id)


def Hooks(values: dict | None = None) -> FakeHooks:
    table = values or {}

    def evaluate(expression: str) -> object:
        if expression not in table:
            raise RuntimeError(expression)
        return table[expression]

    return FakeHooks(evaluate=evaluate)


def _node(type_id: str, config: dict) -> dict:
    return {"id": "n", "type": type_id, "config": config}


def test_set_fields_keeps_order_and_parses_json() -> None:
    result = _run("transform.set_fields")(
        _node(
            "transform.set_fields",
            {"fields": [{"name": "b", "value": "1"}, {"name": "a", "value": '"x"'}]},
        ),
        Hooks(),
    )
    assert result.status == "succeeded"
    assert list(result.output) == ["b", "a"]
    assert result.output == {"b": 1, "a": "x"}


def test_set_fields_evaluates_a_template() -> None:
    result = _run("transform.set_fields")(
        _node("transform.set_fields", {"fields": [{"name": "n", "value": "{{ nums }}"}]}),
        Hooks({"nums": [1, 2]}),
    )
    assert result.output == {"n": [1, 2]}


def test_if_selects_the_live_port() -> None:
    yes = _run("transform.if")(_node("transform.if", {"condition": "true"}), Hooks())
    no = _run("transform.if")(_node("transform.if", {"condition": "{{ flag }}"}), Hooks({"flag": False}))
    assert yes.output == {"value": True}
    assert yes.ports == frozenset({"true"})
    assert no.ports == frozenset({"false"})
    bad = _run("transform.if")(_node("transform.if", {"condition": "1"}), Hooks())
    assert bad.error_code == "CHANNEL_VALUE_TYPE_MISMATCH"


def test_filter_operators_bool_and_incomparable() -> None:
    rows = [{"n": True}, {"n": 1}, {"n": 2}, {"label": "Ab"}]
    kept = _run("transform.filter")(
        _node(
            "transform.filter",
            {
                "items": "{{ rows }}",
                "combinator": "all",
                "conditions": [{"key": "n", "operator": "eq", "value": "1"}],
            },
        ),
        Hooks({"rows": rows}),
    )
    assert kept.output["rows"] == [{"n": 1}]
    assert kept.output["dropped"] == 3

    nulls = _run("transform.filter")(
        _node(
            "transform.filter",
            {
                "items": "{{ rows }}",
                "conditions": [{"key": "missing", "operator": "is_null"}],
            },
        ),
        Hooks({"rows": [{"a": 1}, {"missing": None}, {"missing": 0}]}),
    )
    assert nulls.output["count"] == 2

    any_match = _run("transform.filter")(
        _node(
            "transform.filter",
            {
                "items": '[{"name": "bolt"}, {"name": "nut"}]',
                "combinator": "any",
                "conditions": [
                    {"key": "name", "operator": "starts_with", "value": '"b"'},
                    {"key": "name", "operator": "ends_with", "value": '"x"'},
                ],
            },
        ),
        Hooks(),
    )
    assert any_match.output["rows"] == [{"name": "bolt"}]

    empty = _run("transform.filter")(
        _node("transform.filter", {"items": "{{ rows }}", "conditions": []}),
        Hooks({"rows": [{"a": 1}]}),
    )
    assert empty.output["dropped"] == 0

    failed = _run("transform.filter")(
        _node(
            "transform.filter",
            {
                "items": '[{"n": "a"}, {"n": 1}]',
                "conditions": [{"key": "n", "operator": "gt", "value": "0"}],
            },
        ),
        Hooks(),
    )
    assert failed.status == "failed"
    assert failed.error_detail["row_index"] == 0

    contained = _run("transform.filter")(
        _node(
            "transform.filter",
            {
                "items": '[{"code": "ABC"}, {"code": "Z"}]',
                "conditions": [{"key": "code", "operator": "contains", "value": '"B"'}],
            },
        ),
        Hooks(),
    )
    assert contained.output["rows"] == [{"code": "ABC"}]

    member = _run("transform.filter")(
        _node(
            "transform.filter",
            {
                "items": '[{"n": 1}, {"n": true}]',
                "conditions": [{"key": "n", "operator": "in", "value": "[1, 2]"}],
            },
        ),
        Hooks(),
    )
    assert member.output["rows"] == [{"n": 1}]


def test_merge_modes_and_null_keys() -> None:
    many = _run("transform.merge")(
        _node(
            "transform.merge",
            {
                "mode": "by_key",
                "key": "code",
                "join": "inner",
                "inputs": ["{{ left }}", "{{ right }}"],
            },
        ),
        Hooks(
            {
                "left": [{"code": "a", "n": 1}, {"code": "a", "n": 2}],
                "right": [{"code": "a", "p": 10}, {"code": "a", "p": 20}],
            }
        ),
    )
    assert many.output["count"] == 4
    assert {row["n"] for row in many.output["rows"]} == {1, 2}
    assert {row["p"] for row in many.output["rows"]} == {10, 20}

    nulls = _run("transform.merge")(
        _node(
            "transform.merge",
            {
                "mode": "by_key",
                "key": "code",
                "join": "full",
                "inputs": ["{{ left }}", "{{ right }}"],
            },
        ),
        Hooks(
            {
                "left": [{"code": None, "n": 1}, {"code": "a", "n": 2}],
                "right": [{"code": None, "p": 9}, {"code": "a", "p": 3}],
            }
        ),
    )
    matched = [row for row in nulls.output["rows"] if row.get("code") == "a"]
    assert matched == [{"code": "a", "n": 2, "p": 3}]
    assert {"n": 1, "code": None} in [
        {key: row.get(key) for key in ("n", "code")} for row in nulls.output["rows"]
    ]
    assert any(row.get("p") == 9 and "n" not in row for row in nulls.output["rows"])

    left_join = _run("transform.merge")(
        _node(
            "transform.merge",
            {"mode": "by_key", "key": "code", "join": "left", "inputs": ["{{ left }}", "{{ right }}"]},
        ),
        Hooks({"left": [{"code": "a", "n": 1}, {"code": "b", "n": 2}], "right": [{"code": "a", "p": 5}]}),
    )
    assert left_join.output["rows"][1] == {"code": "b", "n": 2}

    position = _run("transform.merge")(
        _node(
            "transform.merge",
            {"mode": "by_position", "join": "full", "key": None, "inputs": ["{{ left }}", "{{ right }}"]},
        ),
        Hooks({"left": [{"a": 1}], "right": [{"b": 2}, {"b": 3}]}),
    )
    assert position.output["rows"] == [{"a": 1, "b": 2}, {"b": 3}]

    inner = _run("transform.merge")(
        _node(
            "transform.merge",
            {"mode": "by_position", "join": "inner", "inputs": ["{{ left }}", "{{ right }}"]},
        ),
        Hooks({"left": [{"a": 1}], "right": [{"b": 2}, {"b": 3}]}),
    )
    assert inner.output["rows"] == [{"a": 1, "b": 2}]

    appended = _run("transform.merge")(
        _node(
            "transform.merge",
            {"mode": "append", "join": "inner", "inputs": ["{{ left }}", "{{ right }}"]},
        ),
        Hooks({"left": [{"a": 1}], "right": [{"a": 2}]}),
    )
    assert appended.output["rows"] == [{"a": 1}, {"a": 2}]

    missing = _run("transform.merge")(
        _node(
            "transform.merge",
            {"mode": "append", "inputs": ["{{ left }}", "{{ gone }}"]},
        ),
        Hooks({"left": []}),
    )
    assert missing.status == "failed"
    assert missing.error_code == "CHANNEL_NODE_FAILED"


def test_deduplicate_keeps_the_first_row() -> None:
    result = _run("transform.deduplicate")(
        _node(
            "transform.deduplicate",
            {"items": "{{ rows }}", "keys": ["k"]},
        ),
        Hooks({"rows": [{"k": 1, "n": "a"}, {"k": 1, "n": "b"}, {"n": "c"}, {"k": None, "n": "d"}, {"k": True, "n": "e"}]}),
    )
    assert [row["n"] for row in result.output["rows"]] == ["a", "c", "e"]
    assert result.output["removed"] == 2


def test_for_exposes_iterations_and_rejects_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run("volume.for")(_node("volume.for", {"items": '["a", "b"]'}), Hooks())
    assert result.iterations == [
        {"current": "a", "index": 0, "count": 2},
        {"current": "b", "index": 1, "count": 2},
    ]
    assert result.output["current"] == "b"
    assert result.output["iterations"] == []
    assert "results" not in result.output
    assert result.ports == frozenset({"done"})
    for_type = next(item for item in list_node_types() if item.type_id == "volume.for")
    assert [port.port for port in for_type.inputs] == ["main"]
    assert [(port.port, port.loop_back) for port in for_type.outputs] == [
        ("each", False),
        ("done", False),
    ]
    empty = _run("volume.for")(_node("volume.for", {"items": "[]"}), Hooks())
    assert empty.iterations == []
    assert empty.output["current"] is None
    assert empty.output["index"] is None
    monkeypatch.setattr("backend.channel.nodes.volume.for._ITEM_LIMIT", 1)
    limited = _run("volume.for")(_node("volume.for", {"items": "[1, 2]"}), Hooks())
    assert limited.error_code == "CHANNEL_ITEM_LIMIT_EXCEEDED"
