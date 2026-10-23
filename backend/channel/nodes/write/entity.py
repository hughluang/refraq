"""Write Entity node type."""

from __future__ import annotations

import time
from typing import Any, Iterator, Mapping

from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA
from backend.channel.dataset_registry import DatasetRegistry, get_dataset_store
from backend.channel.item_limit import ITEM_LIMIT
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    Problem,
    ReferenceResolver,
    ResolvedAttribute,
    ResolvedEntity,
    object_schema,
)
from backend.channel.values import LIST_OF_OBJECTS
from backend.channel.write_compatibility import write_reasons
from backend.core.time import utc_now
from backend.entity.datasets import iter_dataset_chunks
from backend.entity.errors import EntityRowWriteFailed
from backend.entity.rows import WRITE_CHUNK_SIZE, head_target, write_rows

__all__ = ["NODE_TYPE"]

_DEFAULT_TIMEOUT_SEC = 300

# ``items`` belongs to the list branch. The dataset-reference keywords belong to
# the object branch. A type array keeps each branch's keywords on that branch.
_SOURCE_SCHEMA: dict[str, Any] = {
    "type": ["array", "object"],
    "items": LIST_OF_OBJECTS["items"],
    "additionalProperties": DATASET_REFERENCE_SCHEMA["additionalProperties"],
    "required": DATASET_REFERENCE_SCHEMA["required"],
    "properties": DATASET_REFERENCE_SCHEMA["properties"],
    "x-refraq-dataset-reference": DATASET_REFERENCE_SCHEMA["x-refraq-dataset-reference"],
}

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
    source, error = render_field(hooks, config.get("source"), _SOURCE_SCHEMA)
    if error is not None:
        return error
    timeout_sec = config.get("statement_timeout_sec", _DEFAULT_TIMEOUT_SEC)
    mapping = config.get("mapping") or []
    prepared, error = _prepare_rows(source, mapping, hooks, int(timeout_sec))
    if error is not None:
        return error
    mode = config["mode"]
    try:
        try:
            result = write_rows(
                str(config["entity_id"]),
                mode=mode,
                match_key=config.get("match_key"),
                rows=prepared,
                user=hooks.user,
                pulse=_pulse(hooks, int(timeout_sec)),
            )
        except _SourceRejected as rejected:
            return rejected.result
    except _WriteStopped as exc:
        if exc.kind == "timeout":
            return NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_FAILED",
                error_message="Write exceeded the statement timeout",
            )
        raise
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
    finally:
        close = getattr(prepared, "close", None)
        if close is not None:
            close()
    output: dict[str, Any] = {
        "inserted": result.inserted,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "deleted": result.deleted,
        "unmatched": result.unmatched,
    }
    return NodeResult(status="succeeded", output=output)


class _SourceRejected(Exception):
    def __init__(self, result: NodeResult) -> None:
        super().__init__(result.error_message or "source rejected")
        self.result = result


def _prepare_rows(
    source: Any,
    mapping: list[dict[str, Any]],
    hooks: EngineHooks,
    timeout_sec: int,
) -> tuple[Any, NodeResult | None]:
    if isinstance(source, list):
        if len(source) > ITEM_LIMIT:
            return None, NodeResult(
                status="failed",
                error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
                error_message="Use Materialize or Dataset Query, then Batch Read.",
            )
        return _project(source, mapping)
    return _dataset_rows(source, mapping, hooks, timeout_sec)


def _dataset_rows(
    source: Mapping[str, Any],
    mapping: list[dict[str, Any]],
    hooks: EngineHooks,
    timeout_sec: int,
) -> tuple[Any, NodeResult | None]:
    dataset_id = source.get("dataset_id")
    if not isinstance(dataset_id, str) or dataset_id == "":
        return None, _unavailable("not_found")
    record = get_dataset_store().get(dataset_id)
    if record is None:
        return None, _unavailable("not_found")
    if record.job_id != hooks.run_id:
        return None, _unavailable("foreign_run")
    if record.expires_at is not None and record.expires_at <= utc_now():
        return None, _unavailable("expired")
    if record.status != "ready":
        return None, _unavailable("not_found")
    if DatasetRegistry(get_dataset_store()).is_lost(dataset_id):
        return None, _unavailable("lost")
    if record.row_count <= 0:
        return [], None
    return (
        _projected_dataset(record.relation, mapping, max(1, timeout_sec * 1000)),
        None,
    )


def _projected_dataset(
    relation: str,
    mapping: list[dict[str, Any]],
    timeout_ms: int,
) -> Iterator[list[tuple[int, dict[str, Any]]]]:
    chunks = iter_dataset_chunks(
        relation,
        chunk_size=WRITE_CHUNK_SIZE,
        timeout_ms=timeout_ms,
    )
    try:
        for chunk in chunks:
            projected: list[tuple[int, dict[str, Any]]] = []
            for ordinal, row in chunk:
                item, error = _project_one(row, ordinal, mapping)
                if error is not None:
                    raise _SourceRejected(error)
                projected.append((ordinal, item))
            if projected:
                yield projected
    finally:
        chunks.close()


def _unavailable(reason: str) -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_DATASET_UNAVAILABLE",
        error_message="Dataset is not available",
        error_detail={"reason": reason},
    )


def _project(
    source: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], NodeResult | None]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(source):
        projected, error = _project_one(item, index, mapping)
        if error is not None:
            return [], error
        rows.append(projected)
    return rows, None


def _project_one(
    item: Mapping[str, Any],
    index: int,
    mapping: list[dict[str, Any]],
) -> tuple[dict[str, Any], NodeResult | None]:
    consumed = {entry["key"] for entry in mapping}
    projected: dict[str, Any] = {
        key: value for key, value in item.items() if key not in consumed
    }
    for entry in mapping:
        key = entry["key"]
        if key not in item:
            return {}, NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_FAILED",
                error_message=(
                    f"Source object {index} has no key '{key}' "
                    f"for attribute '{entry['attribute']}'"
                ),
                error_detail={"row_index": index, "attribute": entry["attribute"]},
            )
        projected[entry["attribute"]] = item[key]
    return projected, None


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    head = resolver.entity_head(config["entity_id"])
    if head is None:
        return []
    reason = next(
        (
            item
            for item in write_reasons(
                config.get("match_key"),
                config.get("mapping") or [],
                head,
            )
            if item.subject == "match_key"
        ),
        None,
    )
    if reason is None:
        return []
    return [
        Problem(
            "CHANNEL_MATCH_KEY_INVALID",
            (
                "Target head has no Business Key"
                if reason.code == "business_key_missing"
                else "Match key does not resolve"
            ),
        )
    ]


class _WriteStopped(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _pulse(hooks: EngineHooks, timeout_sec: int):
    deadline = time.monotonic() + timeout_sec

    def pulse() -> int:
        if hooks.cancelled() or hooks.superseded():
            raise _WriteStopped("cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _WriteStopped("timeout")
        return max(1, int(remaining * 1000))

    return pulse


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
    trigger=False,
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
                    "Template whose value is a list of objects or a dataset reference. "
                    "Text with no {{ }} is static JSON. A reference is read by dataset_id."
                ),
                "x-refraq-template": _SOURCE_SCHEMA,
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
            "statement_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3600,
                "default": _DEFAULT_TIMEOUT_SEC,
                "title": "Statement timeout",
                "description": (
                    "Seconds for the whole write. Each statement uses the "
                    "remaining time. Default 300."
                ),
            },
        },
        ["entity_id", "mode", "match_key", "source", "mapping", "on_incompatible_head"],
    ),
    execute=_execute,
    refine=_refine,
    check=_check,
)
