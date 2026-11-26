"""Sub-channel trigger node type."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator

from backend.channel.nodes.spec import (
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    Problem,
    ReferenceResolver,
    object_schema,
)
from backend.channel.subchannel import (
    SUBCHANNEL_PARAM_TYPES,
    is_valid_param_name,
    param_input_schema,
    param_value_schema,
    parse_subchannel_params,
    validate_and_resolve_subchannel_input,
)
from backend.jobs.store import get_job_store

__all__ = ["NODE_TYPE"]


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del upstream, resolver
    params = parse_subchannel_params(config)
    properties = {param.name: param_input_schema(param) for param in params}
    required = [
        param.name for param in params if param.required or param.has_default
    ]
    return {
        "main": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        }
    }


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    del resolver
    problems: list[Problem] = []
    raw_items = config.get("input")
    seen: dict[str, str] = {}
    if isinstance(raw_items, list):
        for index, item in enumerate(raw_items):
            name = item.get("name")
            value_type = str(item["type"])
            required = bool(item.get("required", True))
            if not is_valid_param_name(name):
                problems.append(
                    Problem(
                        "CHANNEL_NODE_CONFIG_INVALID",
                        "Parameter name must match ^[A-Za-z_][A-Za-z0-9_]*$ (1 to 64 characters)",
                        path=("input", index, "name"),
                    )
                )
            elif name in seen:
                problems.append(
                    Problem(
                        "CHANNEL_NODE_CONFIG_INVALID",
                        f"Duplicate sub-channel parameter name: {name}",
                        path=("input", index, "name"),
                    )
                )
            else:
                seen[name] = value_type
            if "default" in item:
                if required:
                    problems.append(
                        Problem(
                            "CHANNEL_NODE_CONFIG_INVALID",
                            "Required parameter may not declare a default value",
                            path=("input", index, "default"),
                        )
                    )
                elif value_type == "dataset":
                    problems.append(
                        Problem(
                            "CHANNEL_NODE_CONFIG_INVALID",
                            "Dataset parameter may not declare a default value",
                            path=("input", index, "default"),
                        )
                    )
                else:
                    validator = Draft202012Validator(param_value_schema(value_type))
                    if list(validator.iter_errors(item["default"])):
                        problems.append(
                            Problem(
                                "CHANNEL_NODE_CONFIG_INVALID",
                                f"Default value for '{name}' does not match type {value_type}",
                                path=("input", index, "default"),
                            )
                        )
    sample = config.get("sample_input")
    if isinstance(sample, Mapping):
        for key, value in sample.items():
            param_name = str(key)
            if param_name not in seen:
                problems.append(
                    Problem(
                        "CHANNEL_NODE_CONFIG_INVALID",
                        f"sample_input names an undeclared parameter: {param_name}",
                        path=("sample_input", param_name),
                    )
                )
                continue
            declared_type = seen[param_name]
            param_decl = next(
                p for p in parse_subchannel_params(config) if p.name == param_name
            )
            if value is None and not param_decl.required and not param_decl.has_default:
                continue
            validator = Draft202012Validator(param_value_schema(declared_type))
            if list(validator.iter_errors(value)):
                problems.append(
                    Problem(
                        "CHANNEL_NODE_CONFIG_INVALID",
                        f"sample_input.{param_name} does not match declared type {declared_type}",
                        path=("sample_input", param_name),
                    )
                )
    return problems


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node.get("config") if isinstance(node.get("config"), Mapping) else {}
    params = parse_subchannel_params(config)
    job = get_job_store().get(hooks.run_id)
    assert job is not None
    job_input = job.input if isinstance(job.input, Mapping) else {}
    if "subchannel_input" in job_input:
        raw_input = job_input["subchannel_input"]
    else:
        raw_input = config.get("sample_input") if isinstance(config.get("sample_input"), Mapping) else {}
    resolved, details = validate_and_resolve_subchannel_input(
        params,
        raw_input,
        run_id=hooks.run_id,
    )
    if resolved is None:
        if job.trigger_kind != "subchannel":
            ds_detail = next(
                (
                    d
                    for d in details
                    if d.get("code") == "dataset_unavailable"
                    and d.get("reason") in {"not_found", "expired"}
                ),
                None,
            )
            if ds_detail is not None:
                return NodeResult(
                    status="failed",
                    error_code="CHANNEL_DATASET_UNAVAILABLE",
                    error_message=ds_detail["message"],
                    error_detail={"reason": ds_detail["reason"]},
                )
        return NodeResult(
            status="failed",
            error_code="CHANNEL_SUBCHANNEL_INPUT_INVALID",
            error_message=details[0]["message"],
            error_detail={"details": details},
        )
    return NodeResult(status="succeeded", output=resolved)


_PARAM_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "type"],
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "title": "Name",
            "description": "Parameter identifier exposed on self.<trigger>.output.<name>.",
        },
        "type": {
            "type": "string",
            "enum": list(SUBCHANNEL_PARAM_TYPES),
            "title": "Type",
            "description": "Declared value type or Dataset Reference.",
        },
        "required": {
            "type": "boolean",
            "default": True,
            "title": "Required",
            "description": "Whether callers must pass this parameter.",
        },
        "default": {
            "title": "Default",
            "description": "Fallback JSON value when required is false (not supported for dataset).",
            "type": ["object", "array", "string", "number", "boolean", "null"],
        },
        "description": {
            "type": "string",
            "maxLength": 500,
            "title": "Description",
            "description": "Short guidance shown on Call Sub-channel nodes.",
        },
    },
}


NODE_TYPE = NodeType(
    type_id="trigger.subchannel",
    family="trigger",
    label="Sub-channel trigger",
    summary="Starts a reusable sub-channel run with typed input parameters.",
    description=(
        "Entry trigger of a Sub Data Channel invoked synchronously by "
        "Call Sub-channel nodes in other Data Channels. Standalone editor test "
        "runs read sample_input against the same parameter contract."
    ),
    trigger=True,
    inputs=(),
    outputs=(MAIN_OUTPUT,),
    config_schema=object_schema(
        {
            "input": {
                "type": "array",
                "default": [],
                "maxItems": 100,
                "title": "Input parameters",
                "description": "Typed parameter contract required from callers.",
                "items": _PARAM_ITEM_SCHEMA,
            },
            "sample_input": {
                "type": "object",
                "default": {},
                "title": "Sample input",
                "description": "Input values used when running this sub-channel directly as a test run.",
                "x-refraq-ref": "json",
            },
        },
        [],
    ),
    output_view=OutputView(kind="record"),
    execute=_execute,
    refine=_refine,
    check=_check,
)
