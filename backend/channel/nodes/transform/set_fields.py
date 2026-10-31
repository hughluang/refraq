"""Set Fields node type."""

from __future__ import annotations

import json
from typing import Any, Mapping

from backend.channel.node_support import output_schema, render_field
from backend.channel.nodes.spec import (
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    object_schema,
)
from backend.channel.template import schema_at_path

__all__ = ["NODE_TYPE"]

_ANY: dict[str, Any] = {
    "type": ["object", "array", "string", "number", "boolean", "null"],
}


def _json_schema(value: Any) -> dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        return {"type": "array"}
    if isinstance(value, dict):
        properties = {key: _json_schema(item) for key, item in value.items()}
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": list(properties),
        }
    return {"type": "string"}


def _static_schema(text: Any) -> dict[str, Any] | None:
    if not isinstance(text, str) or "{{" in text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return _json_schema(value)


def _field_schema(value: Any, upstream: Mapping[str, Any]) -> dict[str, Any]:
    static = _static_schema(value)
    if static is not None:
        return static
    if isinstance(value, str):
        found = schema_at_path(value, upstream)
        if isinstance(found, dict):
            return found
    return {}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del resolver
    fields = config.get("fields")
    if not isinstance(fields, list):
        return {"main": None}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get("name"), str):
            return {"main": None}
        properties[field["name"]] = _field_schema(field.get("value"), upstream)
        required.append(field["name"])
    return {
        "main": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        }
    }


def _runtime_field_schema(name: str) -> dict[str, Any]:
    schema = output_schema.get()
    found: dict[str, Any] = _ANY
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get(name), dict):
            found = properties[name]
    return {**found, "x-refraq-json-template": True}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    output: dict[str, Any] = {}
    for index, field in enumerate(node["config"]["fields"]):
        value, error = render_field(
            hooks,
            field.get("value"),
            _runtime_field_schema(str(field.get("name"))),
            path=f"fields.{index}.value",
        )
        if error is not None:
            return error
        output[str(field["name"])] = value
    return NodeResult(status="succeeded", output=output)


NODE_TYPE = NodeType(
    type_id="transform.set_fields",
    family="transform",
    label="Set fields",
    summary="Builds an object by evaluating one template per field.",
    description=(
        "Each field names a key and a JSON template. "
        "The node writes those keys in list order. "
        "Downstream nodes read the object by this node's ref."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT,),
    config_schema=object_schema(
        {
            "fields": {
                "type": "array",
                "title": "Fields",
                "description": "Keys written into the output, in order. Names are unique.",
                "items": object_schema(
                    {
                        "name": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                            "title": "Name",
                            "description": "Output key. One to 128 characters, unique in this node.",
                        },
                        "value": {
                            "type": "string",
                            "title": "Value",
                            "description": (
                                "JSON template for this key. "
                                "Text with no {{ }} is parsed once as JSON."
                            ),
                            "x-refraq-template": _ANY,
                        },
                    },
                    ["name", "value"],
                ),
            }
        },
        ["fields"],
    ),
    output_view=OutputView(kind="record"),
    execute=_execute,
    refine=_refine,
)
