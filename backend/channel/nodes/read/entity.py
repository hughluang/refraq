"""Read Entity node type."""

from __future__ import annotations

from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    NodeType,
    object_schema,
)

__all__ = ["NODE_TYPE"]

NODE_TYPE = NodeType(
    type_id="read.entity",
    family="read",
    label="Read Entity",
    summary="Reads rows from the current head of a Business Entity.",
    description=(
        "Brings rows from one Business Entity into the workflow. Filters compare "
        "a head attribute with an expression, which may use values from the "
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
                    "attribute with an expression."
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
                            "description": "Literal or one expression, evaluated once.",
                            "x-refraq-ref": "expression",
                        },
                    },
                    ["attribute", "op", "value"],
                ),
            },
        },
        ["entity_id", "filters"],
    ),
)
