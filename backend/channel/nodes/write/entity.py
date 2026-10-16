"""Write Entity node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    ResolvedAttribute,
    ResolvedEntity,
    object_schema,
)
from backend.channel.values import LIST_OF_OBJECTS
from backend.channel.write_compatibility import write_reasons
from backend.entity.errors import EntityRowWriteFailed
from backend.entity.rows import head_target, write_rows

__all__ = ["NODE_TYPE"]

STATEMENT_TIMEOUT_MS = 30_000

_COUNT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["inserted", "updated", "unchanged", "deleted", "unmatched"],
        "properties": {
            "inserted": {"type": "integer"},
            "updated": {"type": "integer"},
            "unchanged": {"type": "integer"},
            "deleted": {"type": "integer"},
            "unmatched": {"type": "integer"},
            "dry_run": {"type": "boolean"},
        },
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"main": _COUNT_SCHEMA, "error": None}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    target = head_target(str(config["entity_id"]))
    if target is None:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Target entity has no head",
        )
    reasons = list(
        dict.fromkeys(
            reason.code
            for reason in write_reasons(
                config.get("match_key"),
                config.get("mapping") or [],
                _resolved_head(target),
            )
        )
    )
    if reasons:
        if config.get("on_incompatible_head") == "skip":
            return NodeResult(
                status="skipped",
                output={"skipped": True, "reasons": reasons},
                error_message="incompatible head",
            )
        return NodeResult(
            status="failed",
            error_code="CHANNEL_WRITE_INCOMPATIBLE",
            error_message="Write mapping is incompatible with the current head",
            error_detail={"reasons": reasons},
        )
    source, error = render_field(hooks, config.get("source"), LIST_OF_OBJECTS)
    if error is not None:
        return error
    mode = config["mode"]
    projected, error = _project(source, config.get("mapping") or [])
    if error is not None:
        return error
    try:
        dry_run = hooks.editor is not None
        result = write_rows(
            str(config["entity_id"]),
            mode=mode,
            match_key=config.get("match_key"),
            rows=projected,
            user=hooks.user,
            statement_timeout_ms=STATEMENT_TIMEOUT_MS,
            dry_run=dry_run,
        )
    except EntityRowWriteFailed as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=(
                exc.message
                if exc.row_index is None
                else f"Source object {exc.row_index}: {exc.message}"
            ),
            error_detail={
                "row_index": exc.row_index,
                "attribute": exc.attribute,
                "value": exc.value,
                "reason": exc.reason,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
        )
    output: dict[str, Any] = {
        "inserted": result.inserted,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "deleted": result.deleted,
        "unmatched": result.unmatched,
    }
    if hooks.editor is not None:
        output["dry_run"] = True
    return NodeResult(status="succeeded", output=output)


def _project(
    source: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], NodeResult | None]:
    consumed = {entry["key"] for entry in mapping}
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(source):
        projected: dict[str, Any] = {
            key: value for key, value in item.items() if key not in consumed
        }
        for entry in mapping:
            key = entry["key"]
            if key not in item:
                return [], NodeResult(
                    status="failed",
                    error_code="CHANNEL_NODE_FAILED",
                    error_message=(
                        f"Source object {index} has no key '{key}' "
                        f"for attribute '{entry['attribute']}'"
                    ),
                    error_detail={"row_index": index, "attribute": entry["attribute"]},
                )
            projected[entry["attribute"]] = item[key]
        rows.append(projected)
    return rows, None


def _resolved_head(target: Any) -> ResolvedEntity:
    return ResolvedEntity(
        attributes=tuple(
            ResolvedAttribute(
                name=attr.name,
                unique=bool(attr.unique),
                business_key=bool(attr.business_key),
            )
            for attr in target.attributes
        )
    )


NODE_TYPE = NodeType(
    type_id="write.entity",
    family="write",
    label="Write Entity",
    summary="Creates, updates, upserts, or deletes rows of a Business Entity.",
    description=(
        "Writes source-object keys as attributes into the current head of one Business Entity. "
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
                "description": (
                    "Template whose value is a list of objects. "
                    "Text with no {{ }} is static JSON."
                ),
                "x-refraq-template": LIST_OF_OBJECTS,
            },
            "mapping": {
                "type": "array",
                "title": "Mapping",
                "description": (
                    "Renames a source-object key to an attribute. Keys without an "
                    "entry are written under their own name."
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
    execute=_execute,
    refine=_refine,
)
