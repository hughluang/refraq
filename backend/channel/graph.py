"""Pure graph validation for a Data Channel draft.

`validate` reports every problem it finds. It does not read stores; callers
pass a reference resolver. A cycle is legal only when one of its edges leaves
a Loop node's loop-back port. This slice's catalog has no Loop type, so any
cycle is rejected unless a test catalog declares one.
"""

from __future__ import annotations

import keyword
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from jsonschema import Draft202012Validator

from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import NodeType
from backend.channel.template import (
    TemplateSyntaxError,
    TemplateTypeError,
    parse,
    static_check,
)
from backend.channel.values import attribute_value_schema
from backend.core.time import parse_instant
from backend.worker.api import validate_cadence, validate_start_at
from backend.worker.errors import ScheduleCadenceInvalid, ScheduleStartAtInvalid

__all__ = [
    "Problem",
    "ReferenceResolver",
    "RefinedPort",
    "ResolvedAttribute",
    "ResolvedEntity",
    "refine_ports",
    "validate",
]

_RESERVED_REFS = frozenset({"nodes", "channel", "run", "platform"})
_RESERVED_PAYLOAD = frozenset({"triggered_by", "triggered_at"})

_WHITE = 0
_GRAY = 1
_BLACK = 2


@dataclass(frozen=True, slots=True)
class Problem:
    code: str
    detail: str
    node_id: str | None = None
    edge_id: str | None = None
    severity: str = "error"


@dataclass(frozen=True, slots=True)
class RefinedPort:
    node_id: str
    port: str
    direction: str
    coarse_type: str
    schema: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ResolvedAttribute:
    name: str
    unique: bool
    business_key: bool
    value_type: str = "string"


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    attributes: tuple[ResolvedAttribute, ...]


class ReferenceResolver(Protocol):
    def entity_head(self, entity_id: str) -> ResolvedEntity | None: ...

    def channel_exists(self, channel_id: str) -> bool: ...

    def source_exists(self, source_id: str) -> bool: ...


def validate(
    graph: Mapping[str, Any],
    resolver: ReferenceResolver,
    catalog: Sequence[NodeType] | None = None,
) -> list[Problem]:
    types = list(catalog) if catalog is not None else list_node_types()
    by_type = {item.type_id: item for item in types}
    nodes = list(graph["nodes"])
    edges = list(graph["edges"])
    by_id = {str(node["id"]): node for node in nodes}
    problems: list[Problem] = []
    problems.extend(_name_problems(nodes))
    problems.extend(_ref_problems(nodes))
    problems.extend(_policy_problems(nodes))
    problems.extend(_type_and_config_problems(nodes, by_type))
    problems.extend(_expression_problems(nodes, edges, by_id, by_type, resolver))
    problems.extend(_payload_problems(nodes))
    problems.extend(_scheduled_problems(nodes))
    problems.extend(_edge_problems(edges, by_id, by_type))
    problems.extend(_trigger_problems(nodes, edges, by_id, by_type))
    problems.extend(_reachability_problems(nodes, edges, by_id, by_type))
    problems.extend(_cycle_problems(nodes, edges, by_id, by_type))
    problems.extend(_reference_problems(nodes, by_type, resolver))
    problems.extend(_sql_source_problems(nodes, by_type, resolver))
    problems.extend(_match_key_problems(nodes, by_type, resolver))
    problems.extend(_settings_problems(graph["settings"], resolver))
    return problems


def _name_problems(nodes: list[dict[str, Any]]) -> list[Problem]:
    seen: set[str] = set()
    problems: list[Problem] = []
    for node in nodes:
        name = str(node["name"])
        if name in seen:
            problems.append(
                Problem(
                    "CHANNEL_NODE_NAME_DUP",
                    "Node name is duplicated",
                    node_id=str(node["id"]),
                )
            )
        else:
            seen.add(name)
    return problems


def _ref_problems(nodes: list[dict[str, Any]]) -> list[Problem]:
    seen: set[str] = set()
    problems: list[Problem] = []
    for node in nodes:
        ref = node.get("ref")
        node_id = str(node["id"])
        if (
            not isinstance(ref, str)
            or not ref.isidentifier()
            or keyword.iskeyword(ref)
            or ref.startswith("_")
            or ref in _RESERVED_REFS
        ):
            problems.append(
                Problem(
                    "CHANNEL_NODE_REF_INVALID",
                    "Node ref is not a usable Python identifier",
                    node_id=node_id,
                )
            )
            continue
        if ref in seen:
            problems.append(
                Problem(
                    "CHANNEL_NODE_REF_INVALID",
                    "Node ref is duplicated",
                    node_id=node_id,
                )
            )
        else:
            seen.add(ref)
    return problems


def _policy_problems(nodes: list[dict[str, Any]]) -> list[Problem]:
    problems: list[Problem] = []
    for node in nodes:
        if node.get("on_error", "stop") != "stop" or node.get("retry") is not None:
            problems.append(
                Problem(
                    "CHANNEL_NODE_POLICY_UNSUPPORTED",
                    "Only on_error stop with no retry is supported",
                    node_id=str(node["id"]),
                )
            )
    return problems


def _expression_problems(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    by_type: dict[str, NodeType],
    resolver: ReferenceResolver,
) -> list[Problem]:
    problems: list[Problem] = []
    ancestors = _ancestors(by_id, edges)
    for node in nodes:
        spec = by_type.get(str(node["type"]))
        if spec is None or not isinstance(node.get("config"), dict):
            continue
        node_id = str(node["id"])
        upstream = ancestors.get(node_id, set())
        for text, value_schema in _template_fields(
            spec.config_schema,
            node["config"],
            None,
            resolver,
        ):
            problems.extend(
                _template_problems(text, value_schema, node_id, node, upstream, by_id)
            )
    return problems


def _template_problems(
    text: str,
    value_schema: dict[str, Any] | None,
    node_id: str,
    node: Mapping[str, Any],
    upstream: set[str],
    by_id: dict[str, dict[str, Any]],
) -> list[Problem]:
    try:
        template = parse(text)
    except TemplateSyntaxError:
        return [
            Problem(
                "CHANNEL_EXPRESSION_INVALID",
                "Template expression does not parse",
                node_id=node_id,
            )
        ]
    problems: list[Problem] = []
    by_ref = {str(item.get("ref")): str(item["id"]) for item in by_id.values()}
    by_name = {str(item.get("name")): str(item["id"]) for item in by_id.values()}
    for ref in template.refs:
        target = by_ref.get(ref)
        if target is None or target not in upstream:
            problems.append(
                Problem(
                    "CHANNEL_TEMPLATE_REF_INVALID",
                    f"Template names a node that is not upstream: {ref}",
                    node_id=node_id,
                )
            )
    for name in template.node_names:
        target = by_name.get(name)
        if target is None or target not in upstream:
            problems.append(
                Problem(
                    "CHANNEL_TEMPLATE_REF_INVALID",
                    f"Template names a node that is not upstream: {name}",
                    node_id=node_id,
                )
            )
    del node
    if value_schema is None:
        return problems
    try:
        status = static_check(template, value_schema)
    except TemplateTypeError:
        problems.append(
            Problem(
                "CHANNEL_TEMPLATE_TYPE_MISMATCH",
                "Template value does not match the declared type",
                node_id=node_id,
            )
        )
        return problems
    if status == "unknown":
        problems.append(
            Problem(
                "CHANNEL_TEMPLATE_TYPE_UNKNOWN",
                "Template result type is not known until the node runs",
                node_id=node_id,
                severity="warning",
            )
        )
    return problems


def _template_fields(
    schema: Mapping[str, Any],
    value: Any,
    entity_id: str | None,
    resolver: ReferenceResolver,
) -> list[tuple[str, dict[str, Any] | None]]:
    found: list[tuple[str, dict[str, Any] | None]] = []
    marker = schema.get("x-refraq-template")
    if isinstance(marker, dict) and isinstance(value, str):
        found.append((value, _declared_schema(marker, None, entity_id, resolver)))
    if schema.get("type") == "object" and isinstance(value, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            local_entity = entity_id
            for key, subschema in properties.items():
                if (
                    isinstance(subschema, dict)
                    and subschema.get("x-refraq-ref") == "entity"
                    and isinstance(value.get(key), str)
                ):
                    local_entity = str(value[key])
            for key, subschema in properties.items():
                if not isinstance(subschema, dict) or key not in value:
                    continue
                item = value[key]
                nested_marker = subschema.get("x-refraq-template")
                if isinstance(nested_marker, dict) and isinstance(item, str):
                    found.append(
                        (
                            item,
                            _declared_schema(
                                nested_marker, value, local_entity, resolver
                            ),
                        )
                    )
                    continue
                found.extend(_template_fields(subschema, item, local_entity, resolver))
    if schema.get("type") == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for item in value:
                found.extend(_template_fields(item_schema, item, entity_id, resolver))
    return found


def _declared_schema(
    marker: Mapping[str, Any],
    parent: Mapping[str, Any] | None,
    entity_id: str | None,
    resolver: ReferenceResolver,
) -> dict[str, Any] | None:
    if marker.get("from") != "entity_attribute":
        return dict(marker)
    if parent is None or not isinstance(parent.get("attribute"), str) or not entity_id:
        return None
    head = resolver.entity_head(entity_id)
    if head is None:
        return None
    named = next(
        (attr for attr in head.attributes if attr.name == parent["attribute"]), None
    )
    if named is None:
        return None
    return attribute_value_schema(named.value_type)


def _payload_problems(nodes: list[dict[str, Any]]) -> list[Problem]:
    problems: list[Problem] = []
    for node in nodes:
        if str(node.get("type")) != "trigger.manual":
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        payload = config.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        if _RESERVED_PAYLOAD & set(payload):
            problems.append(
                Problem(
                    "CHANNEL_NODE_CONFIG_INVALID",
                    "Manual payload uses a reserved key",
                    node_id=str(node["id"]),
                )
            )
    return problems


def _scheduled_problems(nodes: list[dict[str, Any]]) -> list[Problem]:
    problems: list[Problem] = []
    for node in nodes:
        if str(node.get("type")) != "trigger.scheduled":
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        cron = config.get("cron")
        cron_text = str(cron).strip() if isinstance(cron, str) and str(cron).strip() else None
        interval = config.get("interval_seconds")
        seconds = interval if isinstance(interval, int) else None
        start = None
        raw_start = config.get("start_at")
        try:
            if isinstance(raw_start, str) and raw_start.strip():
                start = parse_instant(raw_start)
            start = validate_start_at(start)
            validate_cadence(cron=cron_text, interval_seconds=seconds, start_at=start)
        except (ScheduleCadenceInvalid, ScheduleStartAtInvalid, ValueError) as exc:
            problems.append(
                Problem(
                    "CHANNEL_NODE_CONFIG_INVALID",
                    str(exc),
                    node_id=str(node["id"]),
                )
            )
    return problems


def _type_and_config_problems(
    nodes: list[dict[str, Any]],
    by_type: dict[str, NodeType],
) -> list[Problem]:
    problems: list[Problem] = []
    for node in nodes:
        spec = by_type.get(str(node["type"]))
        if spec is None:
            problems.append(
                Problem(
                    "CHANNEL_NODE_TYPE_UNKNOWN",
                    "Unknown node type",
                    node_id=str(node["id"]),
                )
            )
            continue
        version = node.get("type_version", 1)
        if version != spec.type_version:
            problems.append(
                Problem(
                    "CHANNEL_NODE_TYPE_VERSION",
                    "Node type version is not the current version",
                    node_id=str(node["id"]),
                )
            )
        message = _config_error(spec.config_schema, node["config"])
        if message is not None:
            problems.append(
                Problem(
                    "CHANNEL_NODE_CONFIG_INVALID",
                    message,
                    node_id=str(node["id"]),
                )
            )
            continue
        repeated = _repeated_mapping(node["config"])
        if repeated is not None:
            problems.append(
                Problem(
                    "CHANNEL_NODE_CONFIG_INVALID",
                    repeated,
                    node_id=str(node["id"]),
                )
            )
    return problems


def _config_error(schema: dict[str, Any], config: Any) -> str | None:
    if not isinstance(config, dict):
        return "Node configuration must be an object"
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(config), key=lambda item: list(item.path))
    if not errors:
        return None
    return errors[0].message


def _repeated_mapping(config: Any) -> str | None:
    mapping = config.get("mapping")
    if not isinstance(mapping, list):
        return None
    names = [
        item["attribute"]
        for item in mapping
        if isinstance(item, dict) and isinstance(item.get("attribute"), str)
    ]
    if len(names) != len(set(names)):
        return "Mapping names an attribute more than once"
    return None


def _edge_problems(
    edges: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    by_type: dict[str, NodeType],
) -> list[Problem]:
    problems: list[Problem] = []
    for edge in edges:
        source_id = str(edge["source"]["node_id"])
        target_id = str(edge["target"]["node_id"])
        source = by_id.get(source_id)
        target = by_id.get(target_id)
        if source is None or target is None:
            problems.append(
                Problem(
                    "CHANNEL_GRAPH_EDGE_INVALID",
                    "Edge names an unknown node or port",
                    node_id=source_id if source is None else target_id,
                    edge_id=str(edge["id"]),
                )
            )
            continue
        source_type = by_type.get(str(source["type"]))
        target_type = by_type.get(str(target["type"]))
        source_port = str(edge["source"]["port"])
        target_port = str(edge["target"]["port"])
        bad_source = source_type is not None and not any(
            port.port == source_port for port in source_type.outputs
        )
        bad_target = target_type is not None and not any(
            port.port == target_port for port in target_type.inputs
        )
        if bad_source or bad_target:
            problems.append(
                Problem(
                    "CHANNEL_GRAPH_EDGE_INVALID",
                    "Edge names an unknown node or port",
                    node_id=source_id if bad_source else target_id,
                    edge_id=str(edge["id"]),
                )
            )
            continue
        if source_type is None or target_type is None:
            continue
        source_coarse = _coarse(source_type.outputs, source_port)
        target_coarse = _coarse(target_type.inputs, target_port)
        verdict = _port_verdict(source_coarse, target_coarse)
        if verdict == "error":
            problems.append(
                Problem(
                    "CHANNEL_PORT_TYPE_MISMATCH",
                    "Ports have incompatible types",
                    node_id=target_id,
                    edge_id=str(edge["id"]),
                )
            )
        elif verdict == "warning":
            problems.append(
                Problem(
                    "CHANNEL_PORT_TYPE_UNKNOWN",
                    "Upstream port type is not known yet",
                    node_id=target_id,
                    edge_id=str(edge["id"]),
                    severity="warning",
                )
            )
    return problems


def _trigger_problems(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    by_type: dict[str, NodeType],
) -> list[Problem]:
    problems: list[Problem] = []
    triggers = [node for node in nodes if _is_trigger(node, by_type)]
    if not triggers:
        problems.append(
            Problem("CHANNEL_GRAPH_NO_TRIGGER", "Graph has no trigger node")
        )
    elif len(triggers) > 1:
        for node in triggers:
            problems.append(
                Problem(
                    "CHANNEL_GRAPH_MULTIPLE_TRIGGERS",
                    "Graph has more than one trigger node",
                    node_id=str(node["id"]),
                )
            )
    for edge in edges:
        target = by_id.get(str(edge["target"]["node_id"]))
        if target is not None and _is_trigger(target, by_type):
            problems.append(
                Problem(
                    "CHANNEL_GRAPH_TRIGGER_INPUT",
                    "Trigger node has an inbound edge",
                    node_id=str(target["id"]),
                    edge_id=str(edge["id"]),
                )
            )
    return problems


def _reachability_problems(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    by_type: dict[str, NodeType],
) -> list[Problem]:
    outgoing = _outgoing(edges, by_id)
    seen: set[str] = set()
    stack = [str(node["id"]) for node in nodes if _is_trigger(node, by_type)]
    while stack:
        node_id = stack.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        for edge in outgoing.get(node_id, []):
            target_id = str(edge["target"]["node_id"])
            if target_id in by_id:
                stack.append(target_id)
    return [
        Problem(
            "CHANNEL_GRAPH_UNREACHABLE",
            "Node is not reachable from a trigger",
            node_id=str(node["id"]),
        )
        for node in nodes
        if str(node["id"]) not in seen
    ]


def _cycle_problems(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    by_type: dict[str, NodeType],
) -> list[Problem]:
    outgoing = _outgoing(edges, by_id)
    color = {node_id: _WHITE for node_id in by_id}
    stack_nodes: list[str] = []
    stack_edges: list[dict[str, Any] | None] = []
    problems: list[Problem] = []

    def dfs(node_id: str, via: dict[str, Any] | None) -> None:
        color[node_id] = _GRAY
        stack_nodes.append(node_id)
        stack_edges.append(via)
        for edge in outgoing.get(node_id, []):
            target_id = str(edge["target"]["node_id"])
            if target_id not in by_id:
                continue
            if color[target_id] == _GRAY:
                start = stack_nodes.index(target_id)
                cycle_edges = [
                    item for item in stack_edges[start + 1 :] if item is not None
                ]
                cycle_edges.append(edge)
                if not any(_is_loop_back(item, by_id, by_type) for item in cycle_edges):
                    problems.append(
                        Problem(
                            "CHANNEL_GRAPH_CYCLE",
                            "Cycle does not pass through a Loop node",
                            node_id=str(edge["source"]["node_id"]),
                            edge_id=str(edge["id"]),
                        )
                    )
            elif color[target_id] == _WHITE:
                dfs(target_id, edge)
        stack_nodes.pop()
        stack_edges.pop()
        color[node_id] = _BLACK

    for node in nodes:
        node_id = str(node["id"])
        if color[node_id] == _WHITE:
            dfs(node_id, None)
    return problems


def _reference_problems(
    nodes: list[dict[str, Any]],
    by_type: dict[str, NodeType],
    resolver: ReferenceResolver,
) -> list[Problem]:
    problems: list[Problem] = []
    for node in nodes:
        spec = by_type.get(str(node["type"]))
        if (
            spec is None
            or _config_error(spec.config_schema, node["config"]) is not None
        ):
            continue
        for kind, value, entity_id in _refs(spec.config_schema, node["config"], None):
            if kind == "entity":
                if resolver.entity_head(value) is None:
                    problems.append(
                        Problem(
                            "CHANNEL_REFERENCE_UNRESOLVED",
                            f"Entity does not resolve: {value}",
                            node_id=str(node["id"]),
                        )
                    )
                continue
            head = resolver.entity_head(entity_id) if entity_id else None
            if head is None:
                continue
            if not any(attr.name == value for attr in head.attributes):
                problems.append(
                    Problem(
                        "CHANNEL_REFERENCE_UNRESOLVED",
                        f"Attribute does not resolve: {value}",
                        node_id=str(node["id"]),
                    )
                )
    return problems


def _sql_source_problems(
    nodes: list[dict[str, Any]],
    by_type: dict[str, NodeType],
    resolver: ReferenceResolver,
) -> list[Problem]:
    problems: list[Problem] = []
    for node in nodes:
        if str(node["type"]) != "read.sql":
            continue
        spec = by_type.get("read.sql")
        if spec is None or _config_error(spec.config_schema, node["config"]) is not None:
            continue
        source = node["config"].get("source")
        if not isinstance(source, dict) or source.get("kind") != "source":
            continue
        source_id = source["source_id"]
        if not resolver.source_exists(source_id):
            problems.append(
                Problem(
                    "CHANNEL_REFERENCE_UNRESOLVED",
                    f"Source does not resolve: {source_id}",
                    node_id=str(node["id"]),
                )
            )
    return problems


def _match_key_problems(
    nodes: list[dict[str, Any]],
    by_type: dict[str, NodeType],
    resolver: ReferenceResolver,
) -> list[Problem]:
    problems: list[Problem] = []
    for node in nodes:
        if str(node["type"]) != "write.entity":
            continue
        spec = by_type.get("write.entity")
        if (
            spec is None
            or _config_error(spec.config_schema, node["config"]) is not None
        ):
            continue
        config = node["config"]
        head = resolver.entity_head(config["entity_id"])
        if head is None:
            continue
        match_key = config.get("match_key")
        mapped = {
            item.get("attribute")
            for item in config.get("mapping") or []
            if isinstance(item, dict)
        }
        if match_key is None:
            marked = next((attr for attr in head.attributes if attr.business_key), None)
            if marked is None:
                problems.append(
                    Problem(
                        "CHANNEL_MATCH_KEY_INVALID",
                        "Target head has no Business Key",
                        node_id=str(node["id"]),
                    )
                )
                continue
            if config.get("mode") != "delete" and marked.name not in mapped:
                problems.append(
                    Problem(
                        "CHANNEL_MATCH_KEY_INVALID",
                        "Mapping does not include the match key",
                        node_id=str(node["id"]),
                    )
                )
            continue
        if match_key == "row_id":
            problems.append(
                Problem(
                    "CHANNEL_MATCH_KEY_INVALID",
                    "Match key does not resolve",
                    node_id=str(node["id"]),
                )
            )
            continue
        named = next((attr for attr in head.attributes if attr.name == match_key), None)
        if named is None or not named.unique:
            problems.append(
                Problem(
                    "CHANNEL_MATCH_KEY_INVALID",
                    "Match key does not resolve",
                    node_id=str(node["id"]),
                )
            )
            continue
        if config.get("mode") != "delete" and match_key not in mapped:
            problems.append(
                Problem(
                    "CHANNEL_MATCH_KEY_INVALID",
                    "Mapping does not include the match key",
                    node_id=str(node["id"]),
                )
            )
    return problems


def _settings_problems(
    settings: Mapping[str, Any],
    resolver: ReferenceResolver,
) -> list[Problem]:
    channel_id = settings.get("error_channel_id")
    if not isinstance(channel_id, str):
        return []
    if resolver.channel_exists(channel_id):
        return []
    return [
        Problem(
            "CHANNEL_REFERENCE_UNRESOLVED",
            f"Data Channel does not resolve: {channel_id}",
        )
    ]


def _refs(
    schema: Mapping[str, Any],
    value: Any,
    entity_id: str | None,
) -> list[tuple[str, str, str | None]]:
    found: list[tuple[str, str, str | None]] = []
    ref = schema.get("x-refraq-ref")
    if (
        isinstance(ref, str)
        and isinstance(value, str)
        and ref not in {"match_key", "expression", "json"}
    ):
        found.append((ref, value, entity_id))
    if schema.get("type") == "object" and isinstance(value, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            local_entity = entity_id
            for key, subschema in properties.items():
                if (
                    isinstance(subschema, dict)
                    and subschema.get("x-refraq-ref") == "entity"
                    and isinstance(value.get(key), str)
                ):
                    local_entity = str(value[key])
            for key, subschema in properties.items():
                if isinstance(subschema, dict) and key in value:
                    found.extend(_refs(subschema, value[key], local_entity))
    if schema.get("type") == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for item in value:
                found.extend(_refs(item_schema, item, entity_id))
    return found


def _outgoing(
    edges: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source_id = str(edge["source"]["node_id"])
        target_id = str(edge["target"]["node_id"])
        if source_id in by_id and target_id in by_id:
            outgoing.setdefault(source_id, []).append(edge)
    return outgoing


def _is_trigger(node: Mapping[str, Any], by_type: dict[str, NodeType]) -> bool:
    spec = by_type.get(str(node["type"]))
    return spec is not None and spec.entry


def _is_loop_back(
    edge: Mapping[str, Any],
    by_id: dict[str, dict[str, Any]],
    by_type: dict[str, NodeType],
) -> bool:
    source = by_id.get(str(edge["source"]["node_id"]))
    if source is None:
        return False
    spec = by_type.get(str(source["type"]))
    if spec is None:
        return False
    port = str(edge["source"]["port"])
    return any(item.port == port and item.loop_back for item in spec.outputs)


def refine_ports(
    graph: Mapping[str, Any],
    resolver: ReferenceResolver,
    catalog: Sequence[NodeType] | None = None,
) -> list[RefinedPort]:
    """Coarse type and refined schema for every declared port."""
    types = list(catalog) if catalog is not None else list_node_types()
    by_type = {item.type_id: item for item in types}
    nodes = list(graph["nodes"])
    edges = list(graph["edges"])
    by_id = {str(node["id"]): node for node in nodes}
    ancestors = _ancestors(by_id, edges)
    outputs: dict[str, dict[str, Any]] = {}
    for node in _topo(nodes, edges, by_id):
        node_id = str(node["id"])
        spec = by_type.get(str(node["type"]))
        produced: dict[str, Any] = {}
        if (
            spec is not None
            and spec.refine is not None
            and isinstance(node.get("config"), dict)
        ):
            upstream = {}
            for anc in ancestors.get(node_id, ()):
                if anc not in by_id:
                    continue
                ref = by_id[anc].get("ref")
                if isinstance(ref, str):
                    upstream[ref] = outputs.get(anc, {})
            produced = spec.refine(node["config"], upstream, resolver)
        outputs[node_id] = produced if isinstance(produced, dict) else {}
    refined: list[RefinedPort] = []
    for node in nodes:
        spec = by_type.get(str(node["type"]))
        if spec is None:
            continue
        node_id = str(node["id"])
        produced = outputs.get(node_id, {})
        for port in spec.outputs:
            schema = produced.get(port.port)
            refined.append(
                RefinedPort(
                    node_id=node_id,
                    port=port.port,
                    direction="output",
                    coarse_type=port.coarse_type,
                    schema=schema if isinstance(schema, dict) else None,
                )
            )
        for port in spec.inputs:
            refined.append(
                RefinedPort(
                    node_id=node_id,
                    port=port.port,
                    direction="input",
                    coarse_type=port.coarse_type,
                    schema=_input_schema(node_id, port.port, edges, outputs),
                )
            )
    return refined


def _ancestors(
    by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, set[str]]:
    incoming: dict[str, set[str]] = {node_id: set() for node_id in by_id}
    for edge in edges:
        source_id = str(edge["source"]["node_id"])
        target_id = str(edge["target"]["node_id"])
        if source_id in by_id and target_id in by_id:
            incoming[target_id].add(source_id)
    found: dict[str, set[str]] = {}
    for node_id in by_id:
        seen: set[str] = set()
        stack = list(incoming[node_id])
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(incoming.get(current, ()))
        found[node_id] = seen
    return found


def _topo(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    incoming = {node_id: 0 for node_id in by_id}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    for edge in edges:
        source_id = str(edge["source"]["node_id"])
        target_id = str(edge["target"]["node_id"])
        if source_id in by_id and target_id in by_id:
            outgoing[source_id].append(target_id)
            incoming[target_id] += 1
    ready = [node_id for node_id, count in incoming.items() if count == 0]
    ordered: list[str] = []
    while ready:
        node_id = ready.pop()
        ordered.append(node_id)
        for child in outgoing[node_id]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    seen = set(ordered)
    ordered.extend(node_id for node_id in by_id if node_id not in seen)
    return [by_id[node_id] for node_id in ordered]


def _input_schema(
    node_id: str,
    port: str,
    edges: list[dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    schemas: list[dict[str, Any] | None] = []
    for edge in edges:
        if str(edge["target"]["node_id"]) != node_id:
            continue
        if str(edge["target"]["port"]) != port:
            continue
        source_id = str(edge["source"]["node_id"])
        source_port = str(edge["source"]["port"])
        schema = outputs.get(source_id, {}).get(source_port)
        schemas.append(schema if isinstance(schema, dict) else None)
    if len(schemas) != 1:
        return None
    return schemas[0]


def _coarse(ports: tuple[Any, ...], name: str) -> str:
    for port in ports:
        if port.port == name:
            return str(port.coarse_type)
    return "unknown"


def _port_verdict(source: str, target: str) -> str:
    if source == target:
        return "ok"
    if source == "unknown" and target != "unknown":
        return "warning"
    if source == "unknown" or target == "unknown":
        return "ok"
    return "error"
