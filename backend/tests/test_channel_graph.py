"""Pure graph validation. The resolver and, where noted, the catalog are fakes."""

from __future__ import annotations

from backend.channel.graph import (
    ResolvedAttribute,
    ResolvedEntity,
    validate,
)
from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import NodeType, PortSpec


class FakeResolver:
    def __init__(
        self,
        heads: dict[str, ResolvedEntity] | None = None,
        channels: set[str] | None = None,
    ) -> None:
        self.heads = heads or {}
        self.channels = channels or set()

    def entity_head(self, entity_id: str) -> ResolvedEntity | None:
        return self.heads.get(entity_id)

    def channel_exists(self, channel_id: str) -> bool:
        return channel_id in self.channels


def _attr(
    name: str,
    *,
    unique: bool = False,
    business_key: bool = False,
    value_type: str = "string",
) -> ResolvedAttribute:
    return ResolvedAttribute(
        name=name,
        unique=unique,
        business_key=business_key,
        value_type=value_type,
    )


def _head(*attrs: ResolvedAttribute) -> ResolvedEntity:
    return ResolvedEntity(attributes=tuple(attrs))


SKU = _head(_attr("sku", unique=True, business_key=True), _attr("name"))
NO_KEY = _head(_attr("sku", unique=True), _attr("name"))


def _node(
    node_id: str,
    type_id: str,
    name: str,
    config: dict | None = None,
) -> dict:
    return {
        "id": node_id,
        "ref": node_id.removeprefix("nd_"),
        "type": type_id,
        "name": name,
        "position": {"x": 0, "y": 0},
        "config": {} if config is None else config,
        "on_error": "stop",
        "retry": None,
    }


def _edge(
    edge_id: str,
    source: str,
    target: str,
    *,
    source_port: str = "main",
    target_port: str = "main",
) -> dict:
    return {
        "id": edge_id,
        "source": {"node_id": source, "port": source_port},
        "target": {"node_id": target, "port": target_port},
    }


def _graph(
    nodes: list[dict],
    edges: list[dict] | None = None,
    *,
    error_channel_id: str | None = None,
) -> dict:
    return {
        "nodes": nodes,
        "edges": [] if edges is None else edges,
        "settings": {"run_timeout_sec": None, "error_channel_id": error_channel_id},
    }


def _read(node_id: str = "nd_read", name: str = "Read suppliers") -> dict:
    return _node(
        node_id,
        "read.entity",
        name,
        {"entity_id": "ent_src", "filters": []},
    )


def _write(node_id: str = "nd_write", **config: object) -> dict:
    body = {
        "entity_id": "ent_dst",
        "mode": "upsert",
        "match_key": None,
        "source": '[{"sku": "a"}]',
        "mapping": [{"attribute": "sku", "key": "sku"}],
        "on_incompatible_head": "fail",
    }
    body.update(config)
    return _node(node_id, "write.entity", "Write materials", body)


def _codes(graph: dict, resolver: FakeResolver | None = None, catalog=None) -> set[str]:
    problems = validate(
        graph, resolver or FakeResolver({"ent_src": SKU, "ent_dst": SKU}), catalog
    )
    return {problem.code for problem in problems}


def test_valid_manual_read_write_graph() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run manually"),
            _read(),
            _write(),
        ],
        [
            _edge("ed_1", "nd_trigger", "nd_read"),
            _edge("ed_2", "nd_read", "nd_write"),
        ],
    )
    assert _codes(graph) == set()


def test_missing_trigger_and_unreachable_node() -> None:
    assert _codes(_graph([_read()])) == {
        "CHANNEL_GRAPH_NO_TRIGGER",
        "CHANNEL_GRAPH_UNREACHABLE",
    }


def test_trigger_with_input_edge() -> None:
    graph = _graph(
        [_node("nd_trigger", "trigger.manual", "Run"), _read()],
        [_edge("ed_back", "nd_read", "nd_trigger")],
    )
    assert "CHANNEL_GRAPH_TRIGGER_INPUT" in _codes(graph)


def test_unreachable_node() -> None:
    graph = _graph(
        [_node("nd_trigger", "trigger.manual", "Run"), _read()],
    )
    problems = validate(graph, FakeResolver({"ent_src": SKU}))
    unreachable = [
        item for item in problems if item.code == "CHANNEL_GRAPH_UNREACHABLE"
    ]
    assert [item.node_id for item in unreachable] == ["nd_read"]


def test_cycle_not_through_loop() -> None:
    graph = _graph(
        [_node("nd_trigger", "trigger.manual", "Run"), _read(), _write()],
        [
            _edge("ed_1", "nd_trigger", "nd_read"),
            _edge("ed_2", "nd_read", "nd_write"),
            _edge("ed_3", "nd_write", "nd_read"),
        ],
    )
    problems = validate(graph, FakeResolver({"ent_src": SKU, "ent_dst": SKU}))
    cycles = [item for item in problems if item.code == "CHANNEL_GRAPH_CYCLE"]
    assert cycles
    assert cycles[0].edge_id == "ed_3"
    assert cycles[0].node_id == "nd_write"


def test_cycle_through_loop_back_port_is_legal() -> None:
    loop = NodeType(
        type_id="volume.loop",
        family="volume",
        label="Loop",
        summary="Repeats its loop-back branch for each incoming item.",
        description=(
            "Test-only loop type. A cycle is legal when one edge leaves its "
            "loop-back port."
        ),
        entry=False,
        inputs=(PortSpec("main", "Items to iterate."),),
        outputs=(
            PortSpec("main", "Items after the loop finishes."),
            PortSpec("loop", "Items sent back into the loop.", loop_back=True),
        ),
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {},
            "required": [],
        },
    )
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_loop", "volume.loop", "Loop"),
        ],
        [
            _edge("ed_1", "nd_trigger", "nd_loop"),
            _edge("ed_2", "nd_loop", "nd_loop", source_port="loop"),
        ],
    )
    assert validate(graph, FakeResolver(), [*list_node_types(), loop]) == []


def test_unknown_node_and_port_and_edge() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_x", "no.such", "Mystery"),
        ],
        [
            _edge("ed_port", "nd_trigger", "nd_x", target_port="missing"),
            _edge("ed_gone", "nd_trigger", "nd_missing"),
        ],
    )
    assert _codes(graph) >= {
        "CHANNEL_NODE_TYPE_UNKNOWN",
        "CHANNEL_GRAPH_EDGE_INVALID",
    }


def test_invalid_config_and_duplicate_name() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_read", "read.entity", "Read", {}),
            _read("nd_read_2", "Read"),
        ],
        [
            _edge("ed_1", "nd_trigger", "nd_read"),
            _edge("ed_2", "nd_trigger", "nd_read_2"),
        ],
    )
    assert _codes(graph) >= {"CHANNEL_NODE_CONFIG_INVALID", "CHANNEL_NODE_NAME_DUP"}


def test_dangling_entity_and_attribute() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_read",
                "read.entity",
                "Read",
                {
                    "entity_id": "ent_missing",
                    "filters": [{"attribute": "sku", "op": "eq", "value": "A"}],
                },
            ),
            _node(
                "nd_read_2",
                "read.entity",
                "Read two",
                {
                    "entity_id": "ent_src",
                    "filters": [{"attribute": "gone", "op": "eq", "value": "A"}],
                },
            ),
        ],
        [
            _edge("ed_1", "nd_trigger", "nd_read"),
            _edge("ed_2", "nd_trigger", "nd_read_2"),
        ],
    )
    problems = validate(graph, FakeResolver({"ent_src": SKU}))
    by_node = {item.node_id: item.detail for item in problems}
    assert "ent_missing" in by_node["nd_read"]
    assert "gone" in by_node["nd_read_2"]
    assert {item.code for item in problems} == {"CHANNEL_REFERENCE_UNRESOLVED"}


def test_match_key_rules() -> None:
    trigger = _node("nd_trigger", "trigger.manual", "Run")
    cases = [
        ({"match_key": None}, NO_KEY, "CHANNEL_MATCH_KEY_INVALID"),
        ({"match_key": "row_id"}, SKU, "CHANNEL_MATCH_KEY_INVALID"),
        ({"match_key": "name"}, SKU, "CHANNEL_MATCH_KEY_INVALID"),
        ({"match_key": "missing"}, SKU, "CHANNEL_MATCH_KEY_INVALID"),
        ({"match_key": "sku"}, SKU, None),
    ]
    for override, head, expected in cases:
        graph = _graph(
            [trigger, _write(**override)],
            [_edge("ed_1", "nd_trigger", "nd_write")],
        )
        codes = _codes(graph, FakeResolver({"ent_dst": head}))
        if expected is None:
            assert codes == set()
        else:
            assert expected in codes


def test_repeated_mapping_attribute() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _write(
                mapping=[
                    {"attribute": "sku", "value": "a"},
                    {"attribute": "sku", "value": "b"},
                ]
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_write")],
    )
    assert "CHANNEL_NODE_CONFIG_INVALID" in _codes(graph)


def test_static_source_that_is_not_a_list_is_rejected() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _write(source="not-json"),
        ],
        [_edge("ed_1", "nd_trigger", "nd_write")],
    )
    assert "CHANNEL_TEMPLATE_TYPE_MISMATCH" in _codes(graph)


def test_expression_source_warns_until_run_time() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _read(),
            _write(source="{{ self.read.output.rows }}"),
        ],
        [
            _edge("ed_1", "nd_trigger", "nd_read"),
            _edge("ed_2", "nd_read", "nd_write"),
        ],
    )
    problems = validate(graph, FakeResolver({"ent_src": SKU, "ent_dst": SKU}))
    assert [item.code for item in problems if item.severity == "error"] == []
    assert any(
        item.code == "CHANNEL_TEMPLATE_TYPE_UNKNOWN" and item.severity == "warning"
        for item in problems
    )


def test_expression_must_name_an_upstream_node() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _write(source="{{ self.read.output.rows }}"),
        ],
        [_edge("ed_1", "nd_trigger", "nd_write")],
    )
    assert "CHANNEL_TEMPLATE_REF_INVALID" in _codes(graph)


def test_incompatible_coarse_port_types() -> None:
    items = NodeType(
        type_id="test.items",
        family="trigger",
        label="Items",
        summary="Emits a list.",
        description="Test type. Its output is a list of items, not an object.",
        entry=True,
        inputs=(),
        outputs=(PortSpec("main", "A list of items.", coarse_type="items"),),
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {},
            "required": [],
        },
    )
    graph = _graph(
        [
            _node("nd_items", "test.items", "Items"),
            _write(),
        ],
        [_edge("ed_1", "nd_items", "nd_write")],
    )
    catalog = [*list_node_types(), items]
    assert "CHANNEL_PORT_TYPE_MISMATCH" in _codes(graph, catalog=catalog)


def test_filter_static_text_must_match_the_attribute_type() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_read",
                "read.entity",
                "Read",
                {
                    "entity_id": "ent_src",
                    "filters": [{"attribute": "qty", "op": "eq", "value": "nope"}],
                },
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_read")],
    )
    head = _head(_attr("qty", value_type="integer"))
    assert "CHANNEL_TEMPLATE_TYPE_MISMATCH" in _codes(
        graph, FakeResolver({"ent_src": head})
    )


def test_error_channel_must_resolve() -> None:
    graph = _graph(
        [_node("nd_trigger", "trigger.manual", "Run")],
        error_channel_id="chn_missing",
    )
    assert _codes(graph, FakeResolver()) == {"CHANNEL_REFERENCE_UNRESOLVED"}
    assert _codes(graph, FakeResolver(channels={"chn_missing"})) == set()
