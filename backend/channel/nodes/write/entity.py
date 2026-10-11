"""Write Entity node type."""

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
    type_id="write.entity",
    family="write",
    label="Write Entity",
    summary="Creates, updates, upserts, or deletes rows of a Business Entity.",
    description=(
        "Writes mapped attributes into the current head of one Business Entity. "
        "The match key is the head's Business Key unless the node names a unique "
        "attribute. When the published head no longer matches, the node fails "
        "the item or skips it."
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
                "description": "Business Entity whose current head is written.",
                "x-refraq-ref": "entity",
            },
            "mode": {
                "type": "string",
                "enum": ["upsert", "create", "update", "delete"],
                "title": "Mode",
                "description": (
                    "upsert creates or updates by the match key; create inserts; "
                    "update changes a match; delete removes a match."
                ),
            },
            "match_key": {
                "type": ["string", "null"],
                "title": "Match key",
                "description": (
                    "Null uses the head's Business Key. Otherwise the name of a "
                    "unique attribute on the head. row_id is never accepted."
                ),
                "x-refraq-ref": "match_key",
            },
            "source": {
                "type": "string",
                "minLength": 1,
                "title": "Source",
                "description": "Expression whose value is a list of objects.",
                "x-refraq-ref": "expression",
            },
            "mapping": {
                "type": "array",
                "title": "Mapping",
                "description": (
                    "Attributes to write and the source-object key for each. "
                    "Delete ignores this list. The match key attribute is included."
                ),
                "items": object_schema(
                    {
                        "attribute": {
                            "type": "string",
                            "minLength": 1,
                            "title": "Attribute",
                            "description": (
                                "Name of a head attribute. Each name appears at most once."
                            ),
                            "x-refraq-ref": "entity_attribute",
                        },
                        "key": {
                            "type": "string",
                            "minLength": 1,
                            "title": "Source key",
                            "description": "Key copied from each source object.",
                        },
                    },
                    ["attribute", "key"],
                ),
            },
            "on_incompatible_head": {
                "type": "string",
                "enum": ["fail", "skip"],
                "title": "Incompatible head",
                "description": (
                    "fail stops the item; skip leaves it unchanged when the "
                    "published head no longer matches this configuration."
                ),
            },
        },
        ["entity_id", "mode", "match_key", "source", "mapping", "on_incompatible_head"],
    ),
)
