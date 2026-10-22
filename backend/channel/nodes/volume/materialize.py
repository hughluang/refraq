"""Materialize node type."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from sqlalchemy.exc import DBAPIError

from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA, dataset_reference
from backend.channel.dataset_registry import (
    DatasetColumnSpec,
    DatasetQuotaExceeded,
    DatasetRegistry,
    get_dataset_store,
)
from backend.channel.item_limit import ITEM_LIMIT, LIST_ITEM_LIMIT_MESSAGE
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
)
from backend.channel.run_store import get_run_store
from backend.channel.values import LIST_OF_OBJECTS
from backend.entity.datasets import ORD_COLUMN

__all__ = ["NODE_TYPE"]

_CHUNK_ROWS = 1000
_BIGINT_MIN = -2**63
_BIGINT_MAX = 2**63 - 1
_NO_FIELDS = "Materialize list has no fields"
_ORD_COLLISION = "Column name _ord collides with the dataset order column"

_OUTPUT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["dataset", "count"],
    "properties": {
        "dataset": DATASET_REFERENCE_SCHEMA,
        "count": {"type": "integer", "minimum": 0},
    },
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"main": _OUTPUT, "error": None}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    items, error = render_field(hooks, node["config"].get("items"), LIST_OF_OBJECTS)
    if error is not None:
        return error
    if len(items) > ITEM_LIMIT:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
            error_message=LIST_ITEM_LIMIT_MESSAGE,
        )
    inferred = _infer(items)
    if not inferred:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=_NO_FIELDS,
        )
    if any(name == ORD_COLUMN for name, _normalized in inferred):
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=_ORD_COLLISION,
        )
    columns = [DatasetColumnSpec(name, normalized) for name, normalized in inferred]
    rows = [
        tuple(_cell(item.get(name), normalized) for name, normalized in inferred)
        for item in items
    ]
    try:
        record = DatasetRegistry(get_dataset_store()).create_from_chunks(
            job_id=hooks.run_id,
            node_id=str(node["id"]),
            seq=_execution_seq(node, hooks),
            columns=columns,
            chunks=_chunks(rows, _CHUNK_ROWS),
        )
    except DatasetQuotaExceeded:
        return NodeResult(
            status="failed",
            error_code=DatasetQuotaExceeded.code,
            error_message="Dataset storage is already at the capacity ceiling",
        )
    except DBAPIError as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=_db_message(exc),
        )
    except ValueError as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
        )
    reference = dataset_reference(
        dataset_id=record.id,
        columns=record.columns,
        count=record.row_count,
    )
    return NodeResult(
        status="succeeded",
        output={"dataset": reference, "count": record.row_count},
    )


def _infer(items: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    kinds: dict[str, set[str]] = {}
    order: list[str] = []
    for item in items:
        for key, value in item.items():
            if key not in kinds:
                kinds[key] = set()
                order.append(str(key))
            kinds[key].add(_kind(value))
    return [(name, _normalized(kinds[name])) for name in order]


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        if value < _BIGINT_MIN or value > _BIGINT_MAX:
            return "decimal"
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "json"


def _normalized(kinds: set[str]) -> str:
    present = kinds - {"null"}
    if not present:
        return "string"
    if present == {"boolean"}:
        return "boolean"
    if present == {"integer"}:
        return "integer"
    if present <= {"integer", "number"} and "number" in present:
        return "number"
    if present == {"string"}:
        return "string"
    if present <= {"integer", "decimal"} and "decimal" in present:
        return "decimal"
    return "json"


def _cell(value: Any, normalized: str) -> Any:
    if value is None:
        return None
    if normalized == "json":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if normalized == "number" and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value


def _chunks(
    rows: Sequence[Sequence[Any]], size: int
) -> Iterator[Sequence[Sequence[Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _execution_seq(node: Mapping[str, Any], hooks: EngineHooks) -> int:
    node_id = str(node["id"])
    running = [
        record
        for record in get_run_store().list_executions(hooks.run_id)
        if record.node_id == node_id and record.status == "running"
    ]
    if running:
        return running[-1].seq
    return hooks.on_start(node)


def _db_message(exc: DBAPIError) -> str:
    origin = exc.orig
    text_value = str(origin or exc).strip()
    return text_value or "SQL statement failed"


NODE_TYPE = NodeType(
    type_id="volume.materialize",
    family="volume",
    label="Materialize",
    summary="Turns an in-memory list of objects into a dataset reference.",
    description=(
        "The items template is a list of objects held up to the shared item limit. "
        "Column types are inferred from the whole list and copied into a dataset table. "
        "The node returns a dataset reference."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT, ERROR_OUTPUT),
    config_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "string",
                "minLength": 1,
                "title": "Items",
                "description": (
                    "Template whose value is a list of objects. "
                    "More than the shared item limit fails the node."
                ),
                "x-refraq-template": LIST_OF_OBJECTS,
            }
        },
        "required": ["items"],
    },
    execute=_execute,
    refine=_refine,
)
