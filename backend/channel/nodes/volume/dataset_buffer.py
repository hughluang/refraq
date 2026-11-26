"""Dataset Buffer node type."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.exc import DBAPIError

from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA, dataset_reference
from backend.channel.dataset_registry import (
    DatasetColumnSpec,
    DatasetQuotaExceeded,
    DatasetRegistry,
    get_dataset_store,
)
from backend.channel.errors import TemporalTargetIncompatible
from backend.channel.item_limit import ITEM_LIMIT, LIST_ITEM_LIMIT_MESSAGE
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
)
from backend.channel.nodes.volume.materialize import (
    _CHUNK_ROWS,
    _NO_FIELDS,
    _ORD_COLLISION,
    _cell,
    _chunks,
    _db_message,
    _execution_seq,
    _infer,
)
from backend.channel.values import LIST_OF_OBJECTS
from backend.channel.variables import valid_name
from backend.core.time import utc_now
from backend.entity.datasets import ORD_COLUMN

__all__ = ["NODE_TYPE"]

_SOURCE_SCHEMA: dict[str, Any] = {
    "type": ["array", "object"],
    "items": LIST_OF_OBJECTS["items"],
    "additionalProperties": DATASET_REFERENCE_SCHEMA["additionalProperties"],
    "required": DATASET_REFERENCE_SCHEMA["required"],
    "properties": DATASET_REFERENCE_SCHEMA["properties"],
    "x-refraq-dataset-reference": DATASET_REFERENCE_SCHEMA["x-refraq-dataset-reference"],
}

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
    config = node["config"]
    operation = config.get("operation")
    if operation not in {"append", "get"}:
        return _failed("Buffer operation must be append or get")
    rendered, error = render_field(
        hooks, config.get("name"), {"type": "string"}, path="name"
    )
    if error is not None:
        return error
    name = str(rendered)
    if not valid_name(name):
        return _failed("Buffer name is invalid")
    store = get_dataset_store()
    registry = DatasetRegistry(store)
    node_id = str(node["id"])
    seq = _execution_seq(node, hooks)
    try:
        if operation == "get":
            record = registry.get_or_create_empty_buffer(
                job_id=hooks.run_id,
                buffer_name=name,
                node_id=node_id,
                seq=seq,
            )
            return _succeeded(record)
        source, error = render_field(hooks, config.get("source"), _SOURCE_SCHEMA, path="source")
        if error is not None:
            return error
        if isinstance(source, list):
            if len(source) > ITEM_LIMIT:
                return NodeResult(
                    status="failed",
                    error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
                    error_message=LIST_ITEM_LIMIT_MESSAGE,
                )
            if not source:
                record = registry.get_or_create_empty_buffer(
                    job_id=hooks.run_id,
                    buffer_name=name,
                    node_id=node_id,
                    seq=seq,
                )
                return _succeeded(record)
            inferred = _infer(source)
            if not inferred:
                return _failed(_NO_FIELDS)
            if any(col_name == ORD_COLUMN for col_name, _normalized in inferred):
                return _failed(_ORD_COLLISION)
            columns = [
                DatasetColumnSpec(col_name, normalized)
                for col_name, normalized in inferred
            ]
            rows = [
                tuple(
                    _cell(item.get(col_name), normalized)
                    for col_name, normalized in inferred
                )
                for item in source
            ]
            record = registry.append_buffer_chunks(
                job_id=hooks.run_id,
                buffer_name=name,
                node_id=node_id,
                seq=seq,
                columns=columns,
                chunks=_chunks(rows, _CHUNK_ROWS),
            )
            return _succeeded(record)
        dataset_id = source.get("dataset_id")
        if not isinstance(dataset_id, str) or dataset_id == "":
            return _unavailable("not_found")
        src_record = store.get(dataset_id)
        if src_record is None:
            return _unavailable("not_found")
        if src_record.job_id != hooks.run_id:
            return _unavailable("foreign_run")
        if src_record.expires_at is not None and src_record.expires_at <= utc_now():
            return _unavailable("expired")
        if src_record.status != "ready":
            return _unavailable("not_found")
        if registry.is_lost(dataset_id):
            return _unavailable("lost")
        record = registry.append_buffer_dataset(
            job_id=hooks.run_id,
            buffer_name=name,
            node_id=node_id,
            seq=seq,
            source_id=dataset_id,
        )
        return _succeeded(record)
    except DatasetQuotaExceeded:
        return NodeResult(
            status="failed",
            error_code=DatasetQuotaExceeded.code,
            error_message="Dataset storage is already at the capacity ceiling",
        )
    except TemporalTargetIncompatible as exc:
        return NodeResult(
            status="failed",
            error_code=exc.code,
            error_message=exc.message,
            error_detail=exc.extra_members(),
        )
    except DBAPIError as exc:
        return _failed(_db_message(exc))
    except ValueError as exc:
        return _failed(str(exc))
    except Exception as exc:  # noqa: BLE001
        return _failed(str(exc))


def _succeeded(record: Any) -> NodeResult:
    reference = dataset_reference(
        dataset_id=record.id,
        columns=record.columns,
        count=record.row_count,
    )
    return NodeResult(
        status="succeeded",
        output={"dataset": reference, "count": record.row_count},
    )


def _failed(message: str) -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_NODE_FAILED",
        error_message=message,
    )


def _unavailable(reason: str) -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_DATASET_UNAVAILABLE",
        error_message="Dataset is not available",
        error_detail={"reason": reason},
    )


NODE_TYPE = NodeType(
    type_id="volume.dataset_buffer",
    family="volume",
    label="Dataset Buffer",
    summary="Appends to or reads a run-scoped dataset buffer across loop rounds.",
    description=(
        "A named buffer lives for one Channel Run and stores rows in a dataset table. "
        "append adds rows from a list of objects or a dataset reference. "
        "get returns the accumulated dataset reference, or an empty dataset if nothing was appended."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT, ERROR_OUTPUT),
    config_schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["append", "get"],
                "title": "Operation",
                "description": "append adds rows to the named buffer; get returns its dataset reference.",
            },
            "name": {
                "type": "string",
                "minLength": 1,
                "title": "Name",
                "description": "Buffer name. Letters, digits, and _ . : - up to 128 characters.",
                "x-refraq-template": {"type": "string"},
            },
            "source": {
                "type": "string",
                "minLength": 1,
                "title": "Source",
                "description": (
                    "Template whose value is a list of objects or a dataset reference. "
                    "Required when operation is append."
                ),
                "x-refraq-template": _SOURCE_SCHEMA,
            },
        },
        "required": ["operation", "name"],
        "allOf": [
            {
                "if": {
                    "properties": {"operation": {"const": "append"}},
                    "required": ["operation"],
                },
                "then": {"required": ["source"]},
            }
        ],
    },
    output_view=OutputView(kind="dataset", dataset="dataset", metrics=("count",)),
    execute=_execute,
    refine=_refine,
)
