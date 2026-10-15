"""Set Fields node type."""

from __future__ import annotations

import json
from typing import Any, Mapping

from backend.channel.nodes.spec import MAIN_INPUT, MAIN_OUTPUT, NodeType, object_schema

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


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del upstream, resolver
    fields = config.get("fields")
    if not isinstance(fields, list):
        return {"main": None}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get("name"), str):
            return {"main": None}
        schema = _static_schema(field.get("value"))
        if schema is None:
            return {"main": None}
        properties[field["name"]] = schema
        required.append(field["name"])
    return {
        "main": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        }
    }


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
    entry=False,
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
    refine=_refine,
)
