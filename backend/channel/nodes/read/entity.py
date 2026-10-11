"""Read Entity node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    NodeType,
    object_schema,
)
from backend.channel.values import attribute_value_schema

__all__ = ["NODE_TYPE"]


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del upstream
    entity_id = config.get("entity_id") if isinstance(config, Mapping) else None
    head = resolver.entity_head(entity_id) if isinstance(entity_id, str) else None
    if head is None:
        return {"main": None, "error": None}
    properties = {
        "row_id": {"type": "integer"},
    }
    for attr in head.attributes:
        properties[attr.name] = attribute_value_schema(attr.value_type)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["rows", "count"],
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": properties,
                    "required": list(properties),
                },
            },
            "count": {"type": "integer"},
        },
    }
    return {"main": schema, "error": None}


NODE_TYPE = NodeType(
    type_id="read.entity",
    family="read",
    label="Read Entity",
    summary="Reads rows from the current head of a Business Entity.",
    description=(
        "Brings rows from one Business Entity into the workflow. Filters compare "
        "a head attribute with a template, which may use values from the "
        "incoming item. A lookup is this node followed by Merge."
    ),
    entry=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT, ERROR_OUTPUT),
    config_schema=object_schema(
        {
            "entity_id": {
                "type": "string",
                "minLength": 1,
                "title": "Entity",
                "description": "Business Entity whose current head is read.",
                "x-refraq-ref": "entity",
            },
            "filters": {
                "type": "array",
                "title": "Filters",
                "description": (
                    "Conditions that must all match. Each compares one head "
                    "attribute with a template."
                ),
                "items": object_schema(
                    {
                        "attribute": {
                            "type": "string",
                            "minLength": 1,
                            "title": "Attribute",
                            "description": "Name of an attribute on the entity's current head.",
                            "x-refraq-ref": "entity_attribute",
                        },
                        "op": {
                            "type": "string",
                            "enum": ["eq"],
                            "title": "Operator",
                            "description": "Comparison. Only equality is supported.",
                        },
                        "value": {
                            "type": "string",
                            "title": "Value",
                            "description": (
                                "Template compared with the attribute. "
                                "Its declared type is that attribute's type."
                            ),
                            "x-refraq-template": {"from": "entity_attribute"},
                        },
                    },
                    ["attribute", "op", "value"],
                ),
            },
        },
        ["entity_id", "filters"],
    ),
    refine=_refine,
)
