"""Pure graph validation for a Data Channel draft.

`validate` reports every problem it finds. It does not read stores; callers
pass a reference resolver. A cycle is legal only when one of its edges leaves
a Loop node's loop-back port. This slice's catalog has no Loop type, so any
cycle is rejected unless a test catalog declares one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from jsonschema import Draft202012Validator

from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import NodeType

__all__ = [
    "Problem",
    "ReferenceResolver",
    "ResolvedAttribute",
    "ResolvedEntity",
    "validate",
]

_WHITE = 0
_GRAY = 1
_BLACK = 2


@dataclass(frozen=True, slots=True)
class Problem:
    code: str
    detail: str
    node_id: str | None = None
    edge_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedAttribute:
    name: str
    unique: bool
    business_key: bool


@dataclass(frozen=True, slots=True)
class ResolvedEntity:
    attributes: tuple[ResolvedAttribute, ...]


class ReferenceResolver(Protocol):
    def entity_head(self, entity_id: str) -> ResolvedEntity | None: ...

    def channel_exists(self, channel_id: str) -> bool: ...


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
    problems.extend(_type_and_config_problems(nodes, by_type))
    problems.extend(_edge_problems(edges, by_id, by_type))
    problems.extend(_trigger_problems(nodes, edges, by_id, by_type))
    problems.extend(_reachability_problems(nodes, edges, by_id, by_type))
    problems.extend(_cycle_problems(nodes, edges, by_id, by_type))
    problems.extend(_reference_problems(nodes, by_type, resolver))
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
    return problems


def _trigger_problems(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    by_type: dict[str, NodeType],
) -> list[Problem]:
    problems: list[Problem] = []
    if not any(_is_trigger(node, by_type) for node in nodes):
        problems.append(
            Problem("CHANNEL_GRAPH_NO_TRIGGER", "Graph has no trigger node")
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
        if spec is None or _config_error(spec.config_schema, node["config"]) is not None:
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
        if spec is None or _config_error(spec.config_schema, node["config"]) is not None:
            continue
        config = node["config"]
        head = resolver.entity_head(config["entity_id"])
        if head is None:
            continue
        match_key = config.get("match_key")
        if match_key is None:
            if not any(attr.business_key for attr in head.attributes):
                problems.append(
                    Problem(
                        "CHANNEL_MATCH_KEY_INVALID",
                        "Target head has no Business Key",
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
    if isinstance(ref, str) and isinstance(value, str) and ref != "match_key":
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
