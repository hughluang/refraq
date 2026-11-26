"""Sub-channel parameter contract, validation, and reference-graph helpers."""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA
from backend.channel.dataset_registry import dataset_belongs_to_run, get_dataset_store
from backend.channel.nodes.spec import SubchannelContract
from backend.channel.store import ChannelRecord, get_channel_store
from backend.core.time import utc_now

__all__ = [
    "MAX_SUBCHANNEL_CALL_DEPTH",
    "SUBCHANNEL_PARAM_TYPES",
    "SubchannelParam",
    "channel_referenced_by_published_callers",
    "channel_referenced_by_published_error_settings",
    "channel_referenced_for_delete",
    "direct_callees",
    "extract_subchannel_contract",
    "graph_trigger_type",
    "is_valid_param_name",
    "param_input_schema",
    "param_value_schema",
    "parse_subchannel_params",
    "published_subchannel_params",
    "validate_and_resolve_subchannel_input",
]

MAX_SUBCHANNEL_CALL_DEPTH = 8
_PARAM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

SUBCHANNEL_PARAM_TYPES: tuple[str, ...] = (
    "string",
    "integer",
    "number",
    "boolean",
    "object",
    "array",
    "dataset",
)


@dataclass(frozen=True, slots=True)
class SubchannelParam:
    name: str
    value_type: str
    required: bool
    has_default: bool = False
    default: Any = None
    description: str | None = None


def is_valid_param_name(name: str) -> bool:
    return bool(_PARAM_NAME_RE.fullmatch(name))


def param_value_schema(value_type: str) -> dict[str, Any]:
    if value_type == "dataset":
        return dict(DATASET_REFERENCE_SCHEMA)
    return {"type": value_type}


def param_input_schema(param: SubchannelParam) -> dict[str, Any]:
    base = param_value_schema(param.value_type)
    if param.required or param.has_default:
        return base
    if param.value_type == "dataset":
        return {**base, "type": ["object", "null"]}
    return {"type": [param.value_type, "null"]}


def graph_trigger_type(graph: Mapping[str, Any] | None) -> str | None:
    if not isinstance(graph, Mapping):
        return None
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return None
    triggers = [
        str(node.get("type") or "")
        for node in nodes
        if isinstance(node, Mapping) and str(node.get("type") or "").startswith("trigger.")
    ]
    if len(triggers) != 1:
        return None
    return triggers[0]


def parse_subchannel_params(config: Mapping[str, Any] | None) -> list[SubchannelParam]:
    if not isinstance(config, Mapping):
        return []
    raw_items = config.get("input")
    if not isinstance(raw_items, list):
        return []
    params: list[SubchannelParam] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        value_type = item.get("type")
        if (
            not isinstance(name, str)
            or not is_valid_param_name(name)
            or name in seen
            or not isinstance(value_type, str)
            or value_type not in SUBCHANNEL_PARAM_TYPES
        ):
            continue
        seen.add(name)
        required = bool(item.get("required", True))
        has_default = "default" in item and not required and value_type != "dataset"
        description = item.get("description")
        params.append(
            SubchannelParam(
                name=name,
                value_type=value_type,
                required=required,
                has_default=has_default,
                default=copy.deepcopy(item["default"]) if has_default else None,
                description=description if isinstance(description, str) else None,
            )
        )
    return params


def published_subchannel_params(
    graph: Mapping[str, Any] | None,
) -> list[SubchannelParam] | None:
    if not isinstance(graph, Mapping):
        return None
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return None
    triggers = [
        node
        for node in nodes
        if isinstance(node, Mapping) and str(node.get("type") or "").startswith("trigger.")
    ]
    if len(triggers) != 1 or triggers[0].get("type") != "trigger.subchannel":
        return None
    config = triggers[0].get("config")
    return parse_subchannel_params(config if isinstance(config, Mapping) else {})


def extract_subchannel_contract(
    graph: Mapping[str, Any] | None,
) -> SubchannelContract | None:
    params = published_subchannel_params(graph)
    if params is None:
        return None
    return SubchannelContract(
        inputs=tuple(params),
        callees=tuple(direct_callees(graph)),
    )


def validate_and_resolve_subchannel_input(
    params: Sequence[SubchannelParam],
    raw_input: Any,
    *,
    run_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """Validate and apply defaults to a sub-channel input mapping.

    Returns ``(resolved_mapping, [])`` on success or ``(None, details)`` where
    each detail is ``{"field": str, "code": str, "message": str}``.
    """
    if not isinstance(raw_input, Mapping):
        return (
            None,
            [
                {
                    "field": "",
                    "code": "invalid_type",
                    "message": "Sub-channel input must be an object",
                }
            ],
        )
    by_name = {param.name: param for param in params}
    details: list[dict[str, str]] = []
    for key in raw_input:
        if str(key) not in by_name:
            details.append(
                {
                    "field": str(key),
                    "code": "unknown_parameter",
                    "message": f"Unknown sub-channel input parameter: {key}",
                }
            )
    resolved: dict[str, Any] = {}
    now = utc_now()
    for param in params:
        if param.name not in raw_input:
            if param.required:
                details.append(
                    {
                        "field": param.name,
                        "code": "missing_required",
                        "message": f"Missing required sub-channel input: {param.name}",
                    }
                )
                continue
            if param.has_default:
                resolved[param.name] = copy.deepcopy(param.default)
            else:
                resolved[param.name] = None
            continue
        value = raw_input[param.name]
        if value is None and not param.required and not param.has_default:
            resolved[param.name] = None
            continue
        validator = Draft202012Validator(param_value_schema(param.value_type))
        errors = list(validator.iter_errors(value))
        if errors:
            details.append(
                {
                    "field": param.name,
                    "code": "type_mismatch",
                    "message": (
                        f"Input '{param.name}' does not match declared type {param.value_type}"
                    ),
                }
            )
            continue
        if param.value_type == "dataset":
            dataset_id = str(value["dataset_id"])
            record = get_dataset_store().get(dataset_id)
            reason: str | None = None
            if record is None or record.status != "ready":
                reason = "not_found"
            elif record.expires_at is not None and record.expires_at <= now:
                reason = "expired"
            elif not dataset_belongs_to_run(record, run_id):
                reason = "foreign_run"
            if reason is not None:
                details.append(
                    {
                        "field": param.name,
                        "code": "dataset_unavailable",
                        "reason": reason,
                        "message": (
                            f"Dataset '{dataset_id}' for input '{param.name}' is not available in this run"
                        ),
                    }
                )
                continue
        resolved[param.name] = copy.deepcopy(value)
    if details:
        return None, details
    return resolved, []


def direct_callees(graph: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(graph, Mapping):
        return []
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return []
    callees: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        if not isinstance(node, Mapping) or node.get("type") != "action.call_channel":
            continue
        config = node.get("config")
        if not isinstance(config, Mapping):
            continue
        target = config.get("channel_id")
        if isinstance(target, str) and target and target not in seen:
            seen.add(target)
            callees.append(target)
    return callees


def _iter_other_channels(target_channel_id: str) -> Iterator[ChannelRecord]:
    store = get_channel_store()
    offset = 0
    while True:
        rows, total = store.list_channels(q=None, active=None, limit=200, offset=offset)
        for row in rows:
            if row.id != target_channel_id:
                yield row
        offset += len(rows)
        if not rows or offset >= total:
            break


def _graph_references_channel(
    graph: Mapping[str, Any] | None, target_channel_id: str
) -> bool:
    if not isinstance(graph, Mapping):
        return False
    settings = graph.get("settings")
    if isinstance(settings, Mapping) and settings.get("error_channel_id") == target_channel_id:
        return True
    return target_channel_id in direct_callees(graph)


def channel_referenced_for_delete(target_channel_id: str) -> bool:
    """True when another channel's draft or published version references ``target_channel_id``."""
    store = get_channel_store()
    for row in _iter_other_channels(target_channel_id):
        if _graph_references_channel(row.draft_graph, target_channel_id):
            return True
        version_offset = 0
        while True:
            versions, version_total = store.list_versions(
                row.id, limit=200, offset=version_offset
            )
            for version in versions:
                if _graph_references_channel(version.graph, target_channel_id):
                    return True
            version_offset += len(versions)
            if not versions or version_offset >= version_total:
                break
    return False


def channel_referenced_by_published_callers(target_channel_id: str) -> bool:
    """True when another channel's latest published version calls ``target_channel_id``."""
    store = get_channel_store()
    for row in _iter_other_channels(target_channel_id):
        versions, _v_total = store.list_versions(row.id, limit=1, offset=0)
        if versions and target_channel_id in direct_callees(versions[0].graph):
            return True
    return False


def channel_referenced_by_published_error_settings(target_channel_id: str) -> bool:
    """True when another channel's latest published version uses ``target_channel_id`` as error_channel_id."""
    store = get_channel_store()
    for row in _iter_other_channels(target_channel_id):
        versions, _v_total = store.list_versions(row.id, limit=1, offset=0)
        if not versions:
            continue
        settings = (versions[0].graph or {}).get("settings")
        if isinstance(settings, Mapping) and settings.get("error_channel_id") == target_channel_id:
            return True
    return False
