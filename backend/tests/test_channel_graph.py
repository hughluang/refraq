"""Pure graph validation. The resolver and, where noted, the catalog are fakes."""

from __future__ import annotations

from backend.channel.graph import ancestor_closure, refine_ports, validate
from backend.channel.schemas.channels import NodeIn
from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import (
    NodeType,
    PortSpec,
    Problem,
    ResolvedAttribute,
    ResolvedEntity,
)


def _idle(node: object, hooks: object) -> object:
    raise AssertionError("not executed")


class FakeResolver:
    def __init__(
        self,
        heads: dict[str, ResolvedEntity] | None = None,
        channels: set[str] | None = None,
        sources: set[str] | None = None,
    ) -> None:
        self.heads = heads or {}
        self.channels = channels or set()
        self.sources = sources or set()
        self.triggers: dict[str, str] = {}

    def entity_head(self, entity_id: str) -> ResolvedEntity | None:
        return self.heads.get(entity_id)

    def channel_exists(self, channel_id: str) -> bool:
        return channel_id in self.channels

    def published_trigger_type(self, channel_id: str) -> str | None:
        if channel_id not in self.channels:
            return None
        return self.triggers.get(channel_id, "trigger.error")

    def source_exists(self, source_id: str) -> bool:
        return source_id in self.sources


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
    *,
    parent: str | None = None,
) -> dict:
    node = {
        "id": node_id,
        "ref": node_id.removeprefix("nd_"),
        "type": type_id,
        "name": name,
        "position": {"x": 0, "y": 0},
        "config": {} if config is None else config,
        "on_error": "stop",
        "retry": None,
    }
    if parent is not None:
        node["parent"] = parent
    return node


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
        "read.sql",
        name,
        {
            "sql": "SELECT 1",
            "statement_timeout_sec": 30,
            "source": {"kind": "entity"},
        },
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


def test_cycle_through_a_loop_back_port_is_illegal() -> None:
    loop = NodeType(
        execute=_idle,
        type_id="volume.loop",
        family="volume",
        label="Loop",
        summary="Repeats its loop-back branch for each incoming item.",
        description=(
            "Test-only loop type. A cycle that leaves its loop-back port "
            "is still a cycle."
        ),
        trigger=False,
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
    problems = validate(graph, FakeResolver(), [*list_node_types(), loop])
    cycles = [item for item in problems if item.code == "CHANNEL_GRAPH_CYCLE"]
    assert cycles
    assert cycles[0].edge_id == "ed_2"


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


def test_config_schema_errors_name_every_property() -> None:
    absent = _read()
    del absent["config"]["statement_timeout_sec"]
    ok = _graph(
        [_node("nd_trigger", "trigger.manual", "Run"), absent],
        [_edge("ed_1", "nd_trigger", "nd_read")],
    )
    assert "CHANNEL_NODE_CONFIG_INVALID" not in _codes(ok)

    invalid = _read()
    invalid["config"]["statement_timeout_sec"] = None
    invalid["config"]["sql"] = ""
    bad = _graph(
        [_node("nd_trigger", "trigger.manual", "Run"), invalid],
        [_edge("ed_1", "nd_trigger", "nd_read")],
    )
    problems = validate(bad, FakeResolver())
    config = [item for item in problems if item.code == "CHANNEL_NODE_CONFIG_INVALID"]
    assert {item.path for item in config} == {("sql",), ("statement_timeout_sec",)}


def test_missing_required_config_names_the_property() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_read", "read.sql", "Read", {"source": {"kind": "entity"}}),
        ],
        [_edge("ed_1", "nd_trigger", "nd_read")],
    )
    problems = validate(graph, FakeResolver())
    config = [item for item in problems if item.code == "CHANNEL_NODE_CONFIG_INVALID"]
    assert ("sql",) in {item.path for item in config}


def test_invalid_config_and_duplicate_name() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_read", "read.sql", "Read", {}),
            _read("nd_read_2", "Read"),
        ],
        [
            _edge("ed_1", "nd_trigger", "nd_read"),
            _edge("ed_2", "nd_trigger", "nd_read_2"),
        ],
    )
    assert _codes(graph) >= {"CHANNEL_NODE_CONFIG_INVALID", "CHANNEL_NODE_NAME_DUP"}


def test_sql_source_must_resolve_and_entity_rejects_an_id() -> None:
    missing = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_read",
                "read.sql",
                "Read",
                {
                    "sql": "SELECT 1",
                    "source": {"kind": "source", "source_id": "src_missing"},
                },
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_read")],
    )
    assert "CHANNEL_REFERENCE_UNRESOLVED" in _codes(missing)
    present = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_read",
                "read.sql",
                "Read",
                {
                    "sql": "SELECT 1",
                    "source": {"kind": "source", "source_id": "src_live"},
                },
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_read")],
    )
    assert _codes(present, FakeResolver(sources={"src_live"})) == set()
    entity_id = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_read",
                "read.sql",
                "Read",
                {
                    "sql": "SELECT 1",
                    "source": {"kind": "entity", "source_id": "src_live"},
                },
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_read")],
    )
    assert "CHANNEL_NODE_CONFIG_INVALID" in _codes(entity_id)


def test_dangling_entity_and_attribute() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _write("nd_missing", entity_id="ent_missing"),
            _write(
                "nd_attr",
                entity_id="ent_dst",
                mapping=[{"attribute": "gone", "key": "gone"}],
            ),
        ],
        [
            _edge("ed_1", "nd_trigger", "nd_missing"),
            _edge("ed_2", "nd_trigger", "nd_attr"),
        ],
    )
    problems = validate(graph, FakeResolver({"ent_dst": SKU}))
    missing = " ".join(item.detail for item in problems if item.node_id == "nd_missing")
    attr = " ".join(item.detail for item in problems if item.node_id == "nd_attr")
    assert "ent_missing" in missing
    assert "gone" in attr


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


def test_mapping_without_match_key_is_valid() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _write(match_key="sku", mapping=[]),
        ],
        [_edge("ed_1", "nd_trigger", "nd_write")],
    )
    assert _codes(graph, FakeResolver({"ent_dst": SKU})) == set()


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
    problems = validate(graph, FakeResolver({"ent_dst": SKU}))
    mismatch = [
        item for item in problems if item.code == "CHANNEL_TEMPLATE_TYPE_MISMATCH"
    ]
    assert [item.path for item in mismatch] == [("source",)]


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
    unknown = [
        item for item in problems if item.code == "CHANNEL_TEMPLATE_TYPE_UNKNOWN"
    ]
    assert [(item.severity, item.path) for item in unknown] == [("warning", ("source",))]


def test_node_in_accepts_an_optional_parent() -> None:
    bare = NodeIn(
        id="nd_step",
        ref="step",
        type="transform.set_fields",
        name="Step",
        position={"x": 0, "y": 0},
        config={},
    )
    assert bare.parent is None
    assert "parent" not in bare.model_dump()
    held = NodeIn(
        id="nd_step",
        ref="step",
        type="transform.set_fields",
        name="Step",
        position={"x": 0, "y": 0},
        config={},
        parent="nd_walk",
    )
    assert held.parent == "nd_walk"
    assert held.model_dump()["parent"] == "nd_walk"


def test_expression_must_name_an_upstream_node() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _write(source="{{ self.read.output.rows }}"),
        ],
        [_edge("ed_1", "nd_trigger", "nd_write")],
    )
    problems = validate(graph, FakeResolver({"ent_dst": SKU}))
    invalid = [item for item in problems if item.code == "CHANNEL_TEMPLATE_REF_INVALID"]
    assert [item.path for item in invalid] == [("source",)]


def test_template_problem_names_each_property() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_var",
                "state.variable",
                "Counter",
                {"operation": "set", "name": "{{", "value": "not-json"},
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_var")],
    )
    problems = validate(graph, FakeResolver())
    named = {
        item.code: item.path
        for item in problems
        if item.code
        in {"CHANNEL_EXPRESSION_INVALID", "CHANNEL_TEMPLATE_TYPE_MISMATCH"}
    }
    assert named["CHANNEL_EXPRESSION_INVALID"] == ("name",)
    assert named["CHANNEL_TEMPLATE_TYPE_MISMATCH"] == ("value",)


def test_template_problem_path_includes_a_list_index() -> None:
    nested = NodeType(
        execute=_idle,
        type_id="test.nested",
        family="trigger",
        label="Nested",
        summary="Holds a list of templates.",
        description="Test type. One template sits under a list index.",
        trigger=True,
        inputs=(),
        outputs=(PortSpec("main", "An object.", coarse_type="object"),),
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "value": {
                                "type": "string",
                                "x-refraq-template": {"type": "string"},
                            }
                        },
                    },
                }
            },
            "required": [],
        },
    )
    graph = _graph(
        [
            _node(
                "nd_nested",
                "test.nested",
                "Nested",
                {"items": [{"value": "{{"}]},
            )
        ]
    )
    problems = validate(graph, FakeResolver(), [*list_node_types(), nested])
    invalid = [item for item in problems if item.code == "CHANNEL_EXPRESSION_INVALID"]
    assert [item.path for item in invalid] == [("items", 0, "value")]


def test_incompatible_coarse_port_types() -> None:
    items = NodeType(
        execute=_idle,
        type_id="test.items",
        family="trigger",
        label="Items",
        summary="Emits a list.",
        description="Test type. Its output is a list of items, not an object.",
        trigger=True,
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


def test_scheduled_node_requires_one_cadence() -> None:
    graph = _graph(
        [_node("nd_hourly", "trigger.scheduled", "Hourly", {"cron": "0 * * * *"})]
    )
    assert _codes(graph) == set()
    both = _graph(
        [
            _node(
                "nd_hourly",
                "trigger.scheduled",
                "Hourly",
                {"cron": "0 * * * *", "interval_seconds": 60},
            )
        ]
    )
    assert "CHANNEL_NODE_CONFIG_INVALID" in _codes(both)


def test_graph_allows_only_one_trigger() -> None:
    graph = _graph(
        [
            _node("nd_manual", "trigger.manual", "Manual"),
            _node("nd_hourly", "trigger.scheduled", "Hourly", {"cron": "0 * * * *"}),
        ]
    )
    assert "CHANNEL_GRAPH_MULTIPLE_TRIGGERS" in _codes(graph)


def _without_ref(node_id: str, type_id: str, name: str) -> dict:
    node = _node(node_id, type_id, name)
    del node["ref"]
    return node


def test_stored_draft_without_ref_validates_and_refines() -> None:
    graph = _graph(
        [
            _without_ref("nd_trigger", "trigger.manual", "Run"),
            _without_ref("nd_read", "read.entity", "Read"),
            _without_ref("nd_write", "write.entity", "Write"),
        ],
        [
            _edge("ed_1", "nd_trigger", "nd_read"),
            _edge("ed_2", "nd_read", "nd_write"),
        ],
    )
    assert _codes(graph) >= {
        "CHANNEL_NODE_REF_INVALID",
        "CHANNEL_NODE_TYPE_UNKNOWN",
    }
    ports = refine_ports(graph, FakeResolver())
    assert {(port.node_id, port.port, port.direction) for port in ports} == {
        ("nd_trigger", "main", "output"),
        ("nd_write", "main", "input"),
        ("nd_write", "main", "output"),
        ("nd_write", "error", "output"),
    }


def test_refine_upstream_names_only_ancestors_with_ref() -> None:
    seen: dict[str, set[str]] = {}

    def capture(config: dict, upstream: dict, resolver: object) -> dict:
        del config, resolver
        seen["keys"] = set(upstream)
        return {}

    sink = NodeType(
        execute=_idle,
        type_id="test.sink",
        family="test",
        label="Sink",
        summary="Records the upstream map.",
        description="Test-only sink. Its refine records ancestor refs.",
        trigger=False,
        inputs=(PortSpec("main", "Items."),),
        outputs=(PortSpec("main", "Items."),),
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {},
            "required": [],
        },
        refine=capture,
    )
    named = _node("nd_named", "trigger.manual", "Named")
    bare = _without_ref("nd_bare", "write.entity", "Bare")
    graph = _graph(
        [named, bare, _node("nd_sink", "test.sink", "Sink")],
        [
            _edge("ed_named", "nd_named", "nd_sink"),
            _edge("ed_bare", "nd_bare", "nd_sink"),
        ],
    )
    refine_ports(graph, FakeResolver(), [*list_node_types(), sink])
    assert seen["keys"] == {"named"}


def test_continue_and_retry_validate() -> None:
    node = _node("nd_trigger", "trigger.manual", "Run")
    node["on_error"] = "continue"
    node["retry"] = {"max_tries": 2, "wait_sec": 0}
    assert _codes(_graph([node])) == set()


def test_error_output_requires_an_error_port() -> None:
    node = _node("nd_trigger", "trigger.manual", "Run")
    node["on_error"] = "error_output"
    assert _codes(_graph([node])) == {"CHANNEL_NODE_POLICY_UNSUPPORTED"}


def test_error_channel_must_use_the_error_trigger() -> None:
    graph = _graph(
        [_node("nd_trigger", "trigger.manual", "Run")],
        error_channel_id="chn_other",
    )
    resolver = FakeResolver(channels={"chn_other"})
    resolver.triggers["chn_other"] = "trigger.manual"
    assert _codes(graph, resolver) == {"CHANNEL_ERROR_TRIGGER_REQUIRED"}


def test_error_channel_must_resolve() -> None:
    graph = _graph(
        [_node("nd_trigger", "trigger.manual", "Run")],
        error_channel_id="chn_missing",
    )
    assert _codes(graph, FakeResolver()) == {"CHANNEL_REFERENCE_UNRESOLVED"}
    assert _codes(graph, FakeResolver(channels={"chn_missing"})) == set()


def test_manual_payload_string_is_not_an_object() -> None:
    graph = _graph(
        [
            _node(
                "nd_trigger",
                "trigger.manual",
                "Run",
                {"payload": '{"triggered_at": "2026-10-14T06:01:20Z"}'},
            )
        ]
    )
    problems = validate(graph, FakeResolver())
    invalid = [item for item in problems if item.code == "CHANNEL_NODE_CONFIG_INVALID"]
    assert [item.path for item in invalid] == [("payload",)]


def test_manual_payload_reserved_key_points_at_payload() -> None:
    graph = _graph(
        [
            _node(
                "nd_trigger",
                "trigger.manual",
                "Run",
                {"payload": {"triggered_at": "2026-10-14T06:01:20Z"}},
            )
        ]
    )
    problems = validate(graph, FakeResolver())
    reserved = [
        item for item in problems if item.detail == "Manual payload uses a reserved key"
    ]
    assert [item.path for item in reserved] == [("payload",)]


def _fields(value: str) -> dict:
    return {"fields": [{"name": "n", "value": value}]}


def _for_frame() -> dict:
    return _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_walk", "volume.for", "Walk", {"items": "[1]"}),
            _node("nd_step", "transform.set_fields", "Step", _fields("1"), parent="nd_walk"),
            _node("nd_tail", "transform.set_fields", "Tail", _fields("2"), parent="nd_walk"),
            _node("nd_after", "transform.set_fields", "After", _fields("3")),
        ],
        [
            _edge("ed_in", "nd_trigger", "nd_walk"),
            _edge("ed_each", "nd_walk", "nd_step", source_port="each"),
            _edge("ed_next", "nd_step", "nd_tail"),
            _edge("ed_done", "nd_walk", "nd_after", source_port="done"),
        ],
    )


def test_for_frame_of_direct_children_is_legal() -> None:
    assert [item for item in validate(_for_frame(), FakeResolver()) if item.severity == "error"] == []


def test_nested_for_owns_only_its_direct_children() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_outer", "volume.for", "Outer", {"items": "[1]"}),
            _node("nd_inner", "volume.for", "Inner", {"items": "[2]"}, parent="nd_outer"),
            _node("nd_leaf", "transform.set_fields", "Leaf", _fields("1"), parent="nd_inner"),
            _node("nd_side", "transform.set_fields", "Side", _fields("2"), parent="nd_outer"),
            _node("nd_after", "transform.set_fields", "After", _fields("3")),
        ],
        [
            _edge("ed_in", "nd_trigger", "nd_outer"),
            _edge("ed_outer_each", "nd_outer", "nd_inner", source_port="each"),
            _edge("ed_inner_each", "nd_inner", "nd_leaf", source_port="each"),
            _edge("ed_inner_done", "nd_inner", "nd_side", source_port="done"),
            _edge("ed_outer_done", "nd_outer", "nd_after", source_port="done"),
        ],
    )
    assert [item for item in validate(graph, FakeResolver()) if item.severity == "error"] == []


def test_parent_must_name_an_existing_for() -> None:
    missing = _for_frame()
    missing["nodes"][2]["parent"] = "nd_missing"
    missing_problems = [
        item
        for item in validate(missing, FakeResolver())
        if item.code == "CHANNEL_LOOP_BODY_INVALID" and item.edge_id is None
    ]
    assert [item.node_id for item in missing_problems] == ["nd_step"]
    assert missing_problems[0].detail == "parent does not name a container"
    assert "For" not in missing_problems[0].detail

    not_for = _for_frame()
    not_for["nodes"][2]["parent"] = "nd_trigger"
    not_for_problems = [
        item for item in validate(not_for, FakeResolver()) if item.code == "CHANNEL_LOOP_BODY_INVALID"
    ]
    assert any(
        item.node_id == "nd_step" and item.detail == "parent does not name a container"
        for item in not_for_problems
    )

    cycled = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_outer", "volume.for", "Outer", {"items": "[1]"}, parent="nd_inner"),
            _node("nd_inner", "volume.for", "Inner", {"items": "[2]"}, parent="nd_outer"),
        ],
        [_edge("ed_in", "nd_trigger", "nd_outer")],
    )
    cycle_nodes = {
        item.node_id
        for item in validate(cycled, FakeResolver())
        if item.code == "CHANNEL_LOOP_BODY_INVALID" and item.detail == "parent chain contains a cycle"
    }
    assert cycle_nodes == {"nd_outer", "nd_inner"}


def test_edge_that_crosses_a_for_frame_is_invalid() -> None:
    entered = _for_frame()
    entered["edges"].append(_edge("ed_from_trigger", "nd_trigger", "nd_step"))
    entered_problems = [
        item for item in validate(entered, FakeResolver()) if item.code == "CHANNEL_LOOP_BODY_INVALID"
    ]
    assert [item.edge_id for item in entered_problems] == ["ed_from_trigger"]
    assert entered_problems[0].detail == "Edge crosses a container frame"

    left = _for_frame()
    left["edges"].append(_edge("ed_escape", "nd_tail", "nd_after"))
    left_problems = [
        item for item in validate(left, FakeResolver()) if item.code == "CHANNEL_LOOP_BODY_INVALID"
    ]
    assert [item.edge_id for item in left_problems] == ["ed_escape"]

    returned = _for_frame()
    returned["edges"].append(_edge("ed_back", "nd_tail", "nd_walk"))
    returned_codes = {item.code for item in validate(returned, FakeResolver())}
    assert "CHANNEL_LOOP_BODY_INVALID" in returned_codes
    assert "CHANNEL_GRAPH_CYCLE" in returned_codes


def test_for_frame_is_entered_only_from_each() -> None:
    done_into = _for_frame()
    done_into["edges"] = [
        edge for edge in done_into["edges"] if edge["id"] != "ed_done"
    ]
    done_into["edges"].append(_edge("ed_done_in", "nd_walk", "nd_step", source_port="done"))
    done_problems = [
        item for item in validate(done_into, FakeResolver()) if item.code == "CHANNEL_LOOP_BODY_INVALID"
    ]
    assert [item.edge_id for item in done_problems] == ["ed_done_in"]
    assert done_problems[0].detail == "A container frame is entered only from each"

    each_out = _for_frame()
    each_out["edges"].append(_edge("ed_each_out", "nd_walk", "nd_after", source_port="each"))
    each_problems = [
        item
        for item in validate(each_out, FakeResolver())
        if item.code == "CHANNEL_LOOP_BODY_INVALID" and item.edge_id == "ed_each_out"
    ]
    assert len(each_problems) == 1
    assert each_problems[0].detail == "each connects only to a direct child of this container"


_DATASET_IN_CONTAINER = "A Dataset Query or Materialize cannot run inside a container"


def _dataset_query(node_id: str, *, parent: str | None = None) -> dict:
    return _node(
        node_id,
        "volume.dataset_query",
        "Query",
        {"source": {"kind": "entity"}, "sql": "SELECT 1"},
        parent=parent,
    )


def _materialize(node_id: str, *, parent: str | None = None) -> dict:
    return _node(
        node_id,
        "volume.materialize",
        "Load",
        {"items": "[]"},
        parent=parent,
    )


def test_dataset_producers_cannot_sit_inside_a_container() -> None:
    top = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _dataset_query("nd_query"),
            _materialize("nd_load"),
        ],
        [
            _edge("ed_query", "nd_trigger", "nd_query"),
            _edge("ed_load", "nd_query", "nd_load"),
        ],
    )
    assert [item for item in validate(top, FakeResolver()) if item.severity == "error"] == []

    inside = _for_frame()
    inside["nodes"][2] = _dataset_query("nd_step", parent="nd_walk")
    placed = [
        item
        for item in validate(inside, FakeResolver())
        if item.detail == _DATASET_IN_CONTAINER
    ]
    assert [(item.code, item.node_id) for item in placed] == [
        ("CHANNEL_LOOP_BODY_INVALID", "nd_step")
    ]

    nested = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_outer", "volume.for", "Outer", {"items": "[1]"}),
            _node("nd_inner", "volume.for", "Inner", {"items": "[2]"}, parent="nd_outer"),
            _materialize("nd_leaf", parent="nd_inner"),
            _node("nd_after", "transform.set_fields", "After", _fields("1")),
        ],
        [
            _edge("ed_in", "nd_trigger", "nd_outer"),
            _edge("ed_outer_each", "nd_outer", "nd_inner", source_port="each"),
            _edge("ed_inner_each", "nd_inner", "nd_leaf", source_port="each"),
            _edge("ed_outer_done", "nd_outer", "nd_after", source_port="done"),
        ],
    )
    nested_problems = [
        item
        for item in validate(nested, FakeResolver())
        if item.code == "CHANNEL_LOOP_BODY_INVALID"
    ]
    assert [(item.node_id, item.detail) for item in nested_problems] == [
        ("nd_leaf", _DATASET_IN_CONTAINER)
    ]


def test_dataset_producers_use_the_container_set(monkeypatch) -> None:
    from backend.channel.graph import CONTAINER_TYPES, ContainerType

    monkeypatch.setitem(
        CONTAINER_TYPES,
        "volume.batch_read",
        ContainerType(accumulate=False),
    )
    catalog = [*list_node_types(), _container_type("volume.batch_read")]
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_batch", "volume.batch_read", "Batch"),
            _dataset_query("nd_query", parent="nd_batch"),
            _node("nd_after", "transform.set_fields", "After", _fields("1")),
        ],
        [
            _edge("ed_in", "nd_trigger", "nd_batch"),
            _edge("ed_each", "nd_batch", "nd_query", source_port="each"),
            _edge("ed_done", "nd_batch", "nd_after", source_port="done"),
        ],
    )
    problems = [
        item
        for item in validate(graph, FakeResolver(), catalog)
        if item.code == "CHANNEL_LOOP_BODY_INVALID"
    ]
    assert [(item.node_id, item.detail) for item in problems] == [
        ("nd_query", _DATASET_IN_CONTAINER)
    ]


def test_batch_read_is_a_legal_parent_and_still_rejects_dataset_nodes() -> None:
    dataset = '{"dataset_id":"dset","columns":[{"name":"n","type":"integer"}],"count":1}'
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_batch", "volume.batch_read", "Batch", {"dataset": dataset, "batch_size": 2}),
            _node("nd_step", "transform.set_fields", "Step", _fields("1"), parent="nd_batch"),
            _node("nd_inner", "volume.for", "Walk", {"items": "[1]"}, parent="nd_batch"),
            _node("nd_after", "transform.set_fields", "After", _fields("2")),
        ],
        [
            _edge("ed_in", "nd_trigger", "nd_batch"),
            _edge("ed_each", "nd_batch", "nd_step", source_port="each"),
            _edge("ed_inner", "nd_step", "nd_inner"),
            _edge("ed_done", "nd_batch", "nd_after", source_port="done"),
        ],
    )
    assert [item for item in validate(graph, FakeResolver()) if item.severity == "error"] == []

    nested = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_walk", "volume.for", "Walk", {"items": "[1]"}),
            _node(
                "nd_batch",
                "volume.batch_read",
                "Batch",
                {"dataset": dataset},
                parent="nd_walk",
            ),
            _node("nd_step", "transform.set_fields", "Step", _fields("1"), parent="nd_batch"),
        ],
        [
            _edge("ed_in", "nd_trigger", "nd_walk"),
            _edge("ed_each", "nd_walk", "nd_batch", source_port="each"),
            _edge("ed_batch", "nd_batch", "nd_step", source_port="each"),
        ],
    )
    assert [item for item in validate(nested, FakeResolver()) if item.severity == "error"] == []

    blocked = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_batch", "volume.batch_read", "Batch", {"dataset": dataset}),
            _dataset_query("nd_query", parent="nd_batch"),
            _materialize("nd_load", parent="nd_batch"),
        ],
        [
            _edge("ed_in", "nd_trigger", "nd_batch"),
            _edge("ed_query", "nd_batch", "nd_query", source_port="each"),
            _edge("ed_load", "nd_query", "nd_load"),
        ],
    )
    problems = [
        (item.node_id, item.detail)
        for item in validate(blocked, FakeResolver())
        if item.code == "CHANNEL_LOOP_BODY_INVALID"
    ]
    assert problems == [
        ("nd_query", _DATASET_IN_CONTAINER),
        ("nd_load", _DATASET_IN_CONTAINER),
    ]


def test_for_and_batch_read_are_the_container_types() -> None:
    from backend.channel.graph import CONTAINER_TYPES

    assert set(CONTAINER_TYPES) == {"volume.for", "volume.batch_read"}
    assert CONTAINER_TYPES["volume.for"].accumulate is True
    assert CONTAINER_TYPES["volume.batch_read"].accumulate is False


def test_a_non_for_container_in_the_set_is_a_legal_parent(monkeypatch) -> None:
    from backend.channel.graph import CONTAINER_TYPES, ContainerType
    from backend.channel.nodes import list_node_types

    monkeypatch.setitem(
        CONTAINER_TYPES,
        "volume.batch_read",
        ContainerType(accumulate=False),
    )
    catalog = [*list_node_types(), _container_type("volume.batch_read")]
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_batch", "volume.batch_read", "Batch"),
            _node("nd_step", "transform.set_fields", "Step", _fields("1"), parent="nd_batch"),
            _node("nd_after", "transform.set_fields", "After", _fields("2")),
        ],
        [
            _edge("ed_in", "nd_trigger", "nd_batch"),
            _edge("ed_each", "nd_batch", "nd_step", source_port="each"),
            _edge("ed_done", "nd_batch", "nd_after", source_port="done"),
        ],
    )
    assert [item for item in validate(graph, FakeResolver(), catalog) if item.severity == "error"] == []

    crossed = _graph(
        graph["nodes"],
        [
            *graph["edges"],
            _edge("ed_cross", "nd_trigger", "nd_step"),
        ],
    )
    cross = [
        item
        for item in validate(crossed, FakeResolver(), catalog)
        if item.code == "CHANNEL_LOOP_BODY_INVALID"
    ]
    assert [item.edge_id for item in cross] == ["ed_cross"]
    assert cross[0].detail == "Edge crosses a container frame"

    stray = _graph(
        graph["nodes"],
        [
            *[edge for edge in graph["edges"] if edge["id"] != "ed_done"],
            _edge("ed_each_out", "nd_batch", "nd_after", source_port="each"),
        ],
    )
    each = [
        item
        for item in validate(stray, FakeResolver(), catalog)
        if item.code == "CHANNEL_LOOP_BODY_INVALID" and item.edge_id == "ed_each_out"
    ]
    assert len(each) == 1
    assert each[0].detail == "each connects only to a direct child of this container"


def _container_type(type_id: str) -> NodeType:
    return NodeType(
        type_id=type_id,
        family="volume",
        label="Batch",
        summary="Test container.",
        description="Test container used to extend the container set.",
        trigger=False,
        inputs=(PortSpec("main", "Input.", coarse_type="object"),),
        outputs=(
            PortSpec("each", "Each round.", coarse_type="object"),
            PortSpec("done", "After the rounds.", coarse_type="object"),
        ),
        config_schema={"type": "object", "additionalProperties": True},
        execute=_idle,
    )


def test_ancestor_closure_skips_edges_that_cross_a_for_frame() -> None:
    graph = _for_frame()
    graph["edges"].append(_edge("ed_back", "nd_tail", "nd_walk", target_port="loop"))
    assert ancestor_closure(graph, "nd_step") == {"nd_trigger", "nd_walk", "nd_step"}
    assert ancestor_closure(graph, "nd_tail") == {"nd_trigger", "nd_walk", "nd_step", "nd_tail"}
    after = ancestor_closure(graph, "nd_after")
    assert after is not None
    assert "nd_walk" in after
    assert "nd_step" not in after
    assert "nd_tail" not in after


def test_body_template_cannot_name_a_later_node() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_walk", "volume.for", "Walk", {"items": "[1]"}),
            _node(
                "nd_step",
                "transform.set_fields",
                "Step",
                {
                    "fields": [
                        {"name": "later", "value": "{{ self.tail.output.n }}"},
                        {"name": "loop", "value": "{{ self.walk.output.current }}"},
                        {"name": "upstream", "value": "{{ self.trigger.output }}"},
                    ]
                },
                parent="nd_walk",
            ),
            _node(
                "nd_tail",
                "transform.set_fields",
                "Tail",
                {"fields": [{"name": "n", "value": "{{ self.step.output.later }}"}]},
                parent="nd_walk",
            ),
            _node(
                "nd_after",
                "transform.set_fields",
                "After",
                {
                    "fields": [
                        {"name": "body", "value": "{{ self.step.output.later }}"},
                        {"name": "loop", "value": "{{ self.walk.output.iterations }}"},
                    ]
                },
            ),
        ],
        [
            _edge("ed_in", "nd_trigger", "nd_walk"),
            _edge("ed_each", "nd_walk", "nd_step", source_port="each"),
            _edge("ed_next", "nd_step", "nd_tail"),
            _edge("ed_back", "nd_tail", "nd_walk", target_port="loop"),
            _edge("ed_done", "nd_walk", "nd_after", source_port="done"),
        ],
    )
    invalid = [
        (item.node_id, item.path)
        for item in validate(graph, FakeResolver())
        if item.code == "CHANNEL_TEMPLATE_REF_INVALID"
    ]
    assert invalid == [
        ("nd_step", ("fields", 0, "value")),
        ("nd_after", ("fields", 0, "value")),
    ]


def test_set_fields_rejects_duplicate_names() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_shape",
                "transform.set_fields",
                "Shape",
                {"fields": [{"name": "n", "value": "1"}, {"name": "n", "value": "2"}]},
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_shape")],
    )
    problems = validate(graph, FakeResolver())
    assert any(item.detail == "Field names are not unique" for item in problems)


def test_code_syntax_error_names_the_line() -> None:
    graph = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_code",
                "transform.code",
                "Reshape",
                {"code": "return ("},
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_code")],
    )
    problems = validate(graph, FakeResolver())
    found = [item for item in problems if item.code == "CHANNEL_CODE_INVALID"]
    assert len(found) == 1
    assert found[0].node_id == "nd_code"
    assert found[0].path == ("code",)
    assert "line 1" in found[0].detail
    valid = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_code",
                "transform.code",
                "Reshape",
                {"code": "return {'ok': True}"},
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_code")],
    )
    assert "CHANNEL_CODE_INVALID" not in _codes(valid)


def test_source_query_source_must_resolve() -> None:
    missing = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_lookup",
                "read.source_query",
                "Lookup",
                {"source_id": "src_missing", "sql": "SELECT 1"},
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_lookup")],
    )
    problems = validate(missing, FakeResolver())
    found = [item for item in problems if item.code == "CHANNEL_REFERENCE_UNRESOLVED"]
    assert found
    assert found[0].node_id == "nd_lookup"
    present = _graph(
        [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node(
                "nd_lookup",
                "read.source_query",
                "Lookup",
                {"source_id": "src_ok", "sql": "SELECT 1"},
            ),
        ],
        [_edge("ed_1", "nd_trigger", "nd_lookup")],
    )
    assert "CHANNEL_REFERENCE_UNRESOLVED" not in _codes(
        present, FakeResolver(sources={"src_ok"})
    )


def _flagged(*, required: list[str], check) -> NodeType:
    return NodeType(
        execute=_idle,
        check=check,
        type_id="test.flagged",
        family="test",
        label="Flagged",
        summary="Reports a configuration problem from its own check.",
        description=(
            "Test type. Validation asks its check only after the configuration "
            "passes the JSON Schema."
        ),
        trigger=True,
        inputs=(),
        outputs=(PortSpec("main", "Output."),),
        config_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"name": {"type": "string"}},
            "required": required,
        },
    )


def test_catalog_type_check_problem_is_reported_on_the_node() -> None:
    def check(config: object, resolver: object) -> list[Problem]:
        del config, resolver
        return [Problem("CHANNEL_TEST_CHECK", "Name is reserved", path=("name",))]

    graph = _graph([_node("nd_flag", "test.flagged", "Flag", {"name": "x"})])
    assert validate(graph, FakeResolver(), [_flagged(required=[], check=check)]) == [
        Problem(
            "CHANNEL_TEST_CHECK",
            "Name is reserved",
            node_id="nd_flag",
            path=("name",),
        )
    ]


def test_catalog_type_check_does_not_run_when_schema_fails() -> None:
    def check(config: object, resolver: object) -> list[Problem]:
        raise AssertionError("check ran")

    graph = _graph([_node("nd_flag", "test.flagged", "Flag", {})])
    problems = validate(graph, FakeResolver(), [_flagged(required=["name"], check=check)])
    assert [item.path for item in problems if item.code == "CHANNEL_NODE_CONFIG_INVALID"] == [
        ("name",)
    ]
