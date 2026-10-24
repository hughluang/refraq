"""Batch Read node type."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from sqlalchemy.exc import DBAPIError

from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA
from backend.channel.dataset_registry import get_dataset_store
from backend.channel.item_limit import ITEM_LIMIT
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    MAIN_INPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    PortSpec,
    object_schema,
)
from backend.channel.sql_read import _db_message, _jsonable
from backend.core.time import utc_now
from backend.entity.datasets import ORD_COLUMN, any_row_exists, read_keyset_page

__all__ = ["NODE_TYPE"]

_DEFAULT_BATCH_SIZE = 1000
_ROUND: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rows", "index", "count", "total"],
    "properties": {
        "rows": {"type": "array", "items": {"type": "object"}},
        "index": {"type": "integer"},
        "count": {"type": "integer"},
        "total": {"type": "integer"},
    },
}
_DONE: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["count", "total", "batch_size"],
    "properties": {
        "count": {"type": "integer"},
        "total": {"type": "integer"},
        "batch_size": {"type": "integer"},
    },
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"each": _ROUND, "done": _DONE}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    dataset, error = render_field(
        hooks, config.get("dataset"), DATASET_REFERENCE_SCHEMA, path="dataset"
    )
    if error is not None:
        return error
    batch_size = _batch_size(config.get("batch_size", _DEFAULT_BATCH_SIZE))
    if batch_size is None:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="batch_size must be an integer from 1 to 100000",
        )
    record, unavailable = _load_dataset(dataset, hooks.run_id)
    if unavailable is not None:
        return unavailable
    total = record.row_count
    count = _batch_count(total, batch_size)
    rounds: Any = []
    if count:
        rounds = _rounds(record.relation, total=total, batch_size=batch_size, count=count)
    return NodeResult(
        status="succeeded",
        output={"count": count, "total": total, "batch_size": batch_size},
        iterations=rounds,
        ports=frozenset({"done"}),
    )


def _batch_size(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 1 or value > ITEM_LIMIT:
        return None
    return value


def _batch_count(total: int, batch_size: int) -> int:
    if total <= 0:
        return 0
    return (total + batch_size - 1) // batch_size


def _load_dataset(
    dataset: Mapping[str, Any], run_id: str
) -> tuple[Any, NodeResult | None]:
    dataset_id = dataset.get("dataset_id")
    if not isinstance(dataset_id, str) or dataset_id == "":
        return None, _unavailable("not_found")
    record = get_dataset_store().get(dataset_id)
    if record is None:
        return None, _unavailable("not_found")
    if record.job_id != run_id:
        return None, _unavailable("foreign_run")
    if record.status == "dropped" or (
        record.expires_at is not None and record.expires_at <= utc_now()
    ):
        return None, _unavailable("expired")
    if record.status != "ready":
        return None, _unavailable("not_found")
    if record.row_count <= 0:
        return record, None
    try:
        present = any_row_exists(record.relation)
    except DBAPIError as exc:
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=_db_message(exc),
        )
    if not present:
        return None, _unavailable("lost")
    return record, None


def _rounds(
    relation: str,
    *,
    total: int,
    batch_size: int,
    count: int,
) -> Iterator[dict[str, Any]]:
    for index in range(count):
        page = read_keyset_page(relation, after_ord=index * batch_size, limit=batch_size)
        yield {
            "rows": [_json_row(row) for row in page],
            "index": index,
            "count": count,
            "total": total,
        }


def _json_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _jsonable(value) for key, value in row.items() if key != ORD_COLUMN
    }


def _unavailable(reason: str) -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_DATASET_UNAVAILABLE",
        error_message="Dataset is not available",
        error_detail={"reason": reason},
    )


NODE_TYPE = NodeType(
    type_id="volume.batch_read",
    family="volume",
    label="Batch Read",
    summary="Runs its body once for each batch of rows in a dataset.",
    description=(
        "The dataset template is a dataset reference and batch size defaults to 1000. "
        "Each round exposes that batch as rows, and the stored output is only count, total, and batch size."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(
        PortSpec(
            "each",
            "Starts one round for each batch. Connects only to direct children of this Batch Read.",
            coarse_type="object",
        ),
        PortSpec("done", "Taken after every batch has finished.", coarse_type="object"),
    ),
    config_schema=object_schema(
        {
            "dataset": {
                "type": "string",
                "minLength": 1,
                "title": "Dataset",
                "description": (
                    "Dataset reference template. "
                    "The rendered value is a dataset reference for this run."
                ),
                "x-refraq-template": DATASET_REFERENCE_SCHEMA,
            },
            "batch_size": {
                "type": "integer",
                "minimum": 1,
                "maximum": ITEM_LIMIT,
                "default": _DEFAULT_BATCH_SIZE,
                "title": "Batch size",
                "description": (
                    "Rows read in one round. "
                    "An integer from 1 to the shared item limit. Default 1000."
                ),
            },
        },
        ["dataset"],
    ),
    output_view=OutputView(
        kind="container", metrics=("count", "total", "batch_size")
    ),
    execute=_execute,
    refine=_refine,
)
