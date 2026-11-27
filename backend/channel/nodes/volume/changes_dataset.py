"""Changes Dataset node type."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy.exc import DBAPIError

from backend.channel.change_range import (
    ChangeRangeError,
    land_change_range,
    open_change_range,
    propose_change_range,
)
from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA, dataset_reference
from backend.channel.dataset_registry import (
    DatasetColumnSpec,
    DatasetQuotaExceeded,
    DatasetRegistry,
    get_dataset_store,
)
from backend.channel.node_support import resolve_execution_entity_id
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    object_schema,
)
from backend.channel.run_store import get_run_store
from backend.entity.history.service import (
    CHANGES_DATASET_COLUMNS,
    IncrementalDatasetResult,
    normalize_dataset_columns,
)

__all__ = ["NODE_TYPE"]

_PAGE = 10000
_DEFAULT_LIMIT = 1000000
_MAX_LIMIT = 10000000
_DEFAULT_TIMEOUT_SEC = 300
_SOURCES = ("user", "channel_run", "unattributed")
_TIMEOUT_MESSAGE = "Changes Dataset exceeded the statement timeout"
_QUOTA_MESSAGE = "Dataset storage is already at the capacity ceiling"

_COLUMNS: tuple[DatasetColumnSpec, ...] = (
    DatasetColumnSpec("sequence", "integer", nullable=False),
    DatasetColumnSpec("operation", "string", nullable=False),
    DatasetColumnSpec("occurred_at", "string", nullable=False),
    DatasetColumnSpec("source", "string", nullable=True),
    DatasetColumnSpec("subject", "string", nullable=True),
    DatasetColumnSpec("physical_table", "string", nullable=False),
    DatasetColumnSpec("version_id", "string", nullable=False),
    DatasetColumnSpec("version_number", "integer", nullable=False),
    DatasetColumnSpec("row_id", "integer", nullable=True),
    DatasetColumnSpec("business_key", "json", nullable=True),
    DatasetColumnSpec("before", "json", nullable=True),
    DatasetColumnSpec("after", "json", nullable=True),
)
_SPEC_BY_NAME: dict[str, DatasetColumnSpec] = {
    spec.name: spec for spec in _COLUMNS
}


class _LoadHalted(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _selected_specs(
    raw: Any, *, fallback_on_invalid: bool = False
) -> tuple[DatasetColumnSpec, ...]:
    if not isinstance(raw, list) or not raw:
        return _COLUMNS
    try:
        names = normalize_dataset_columns([str(item) for item in raw])
    except ValueError:
        if fallback_on_invalid:
            return _COLUMNS
        raise
    return tuple(_SPEC_BY_NAME[name] for name in names)


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del upstream, resolver
    specs = _selected_specs(config.get("columns"), fallback_on_invalid=True)
    const_columns = [
        {
            "name": spec.name,
            "type": spec.normalized_type,
            "temporal_kind": None,
            "precision": None,
            "nullable": spec.nullable,
        }
        for spec in specs
    ]
    dataset_schema: dict[str, Any] = {
        **DATASET_REFERENCE_SCHEMA,
        "properties": {
            **DATASET_REFERENCE_SCHEMA["properties"],
            "columns": {
                **DATASET_REFERENCE_SCHEMA["properties"]["columns"],
                "const": const_columns,
            },
        },
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["dataset", "count", "has_more"],
        "properties": {
            "dataset": dataset_schema,
            "count": {"type": "integer", "minimum": 0},
            "has_more": {"type": "boolean"},
        },
    }
    return {"main": output_schema, "error": None}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    entity_id, entity_failure = resolve_execution_entity_id(
        str(config["entity_id"]), hooks
    )
    if entity_failure is not None:
        return entity_failure
    assert entity_id is not None
    node_id = str(node["id"])
    limit = int(config.get("limit", _DEFAULT_LIMIT))
    timeout_sec = int(config.get("statement_timeout_sec", _DEFAULT_TIMEOUT_SEC))
    sources = _sources(config.get("sources"))
    specs = _selected_specs(config.get("columns"))
    selected_names = tuple(spec.name for spec in specs)
    session = hooks.checkpoints
    deadline = time.monotonic() + timeout_sec
    outcomes: list[IncrementalDatasetResult] = []

    def before_page() -> int:
        if hooks.cancelled():
            raise _LoadHalted("cancelled")
        if hooks.superseded():
            raise _LoadHalted("superseded")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _LoadHalted("timeout")
        return max(1, math.ceil(remaining * 1000))

    try:
        opened = open_change_range(
            entity_id,
            node_id,
            session,
            ignore_checkpoints=hooks.ignore_checkpoints,
        )

        def load(
            relation: str, on_size: Callable[[int], None]
        ) -> tuple[int, int]:
            landed = land_change_range(
                opened,
                relation,
                limit=limit,
                columns=selected_names,
                sources=sources,
                page_size=_PAGE,
                before_page=before_page,
                on_page_size=on_size,
            )
            outcomes.append(landed)
            return landed.row_count, landed.size_bytes

        record = DatasetRegistry(get_dataset_store()).create_with_loader(
            job_id=hooks.run_id,
            node_id=node_id,
            seq=_execution_seq(node, hooks),
            columns=specs,
            load=load,
        )
    except _LoadHalted as halted:
        if halted.kind == "timeout":
            return _failed("CHANNEL_NODE_FAILED", _TIMEOUT_MESSAGE)
        raise
    except ChangeRangeError as exc:
        return _failed(exc.code, exc.message)
    except DatasetQuotaExceeded:
        return _failed(DatasetQuotaExceeded.code, _QUOTA_MESSAGE)
    except DBAPIError as exc:
        if _is_query_canceled(exc):
            return _failed("CHANNEL_NODE_FAILED", _TIMEOUT_MESSAGE)
        return _failed("CHANNEL_NODE_FAILED", _db_message(exc))
    except Exception as exc:  # noqa: BLE001
        return _failed("CHANNEL_NODE_FAILED", str(exc))

    outcome = outcomes[0]
    propose_change_range(session, opened, outcome.progress)
    reference = dataset_reference(
        dataset_id=record.id,
        columns=record.columns,
        count=record.row_count,
    )
    return NodeResult(
        status="succeeded",
        output={
            "dataset": reference,
            "count": record.row_count,
            "has_more": outcome.has_more,
        },
    )


def _sources(raw: Any) -> set[str] | None:
    if not isinstance(raw, list) or not raw:
        return None
    return {str(item) for item in raw}


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


def _failed(code: str, message: str) -> NodeResult:
    return NodeResult(status="failed", error_code=code, error_message=message)


def _is_query_canceled(exc: DBAPIError) -> bool:
    orig = exc.orig
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code == "57014"


def _db_message(exc: DBAPIError) -> str:
    origin = exc.orig
    text_value = str(origin or exc).strip()
    return text_value or "SQL statement failed"


NODE_TYPE = NodeType(
    type_id="volume.changes_dataset",
    family="volume",
    label="Changes Dataset",
    summary="Lands one bounded Change Log range for a Business Entity as a dataset.",
    description=(
        "Reads the entity Change Log as the platform System Identity after this "
        "node's checkpoint and up to the commit sequence fixed for the run. "
        "Projected rows land in one dataset. The checkpoint is proposed only "
        "after that dataset is ready, at the operation's evaluated position. "
        "Entries a source filter hides, and events with no visible side, stay "
        "out of the dataset and still count toward the limit."
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
                "description": "Business Entity whose Change Log is loaded.",
                "x-refraq-ref": "entity",
                "x-refraq-resolve": "execution",
            },
            "columns": {
                "type": "array",
                "title": "Columns",
                "description": (
                    "Optional subset of dataset columns. Absent or empty writes "
                    "all 12 columns. Omitting before and after skips full "
                    "row-image projection."
                ),
                "items": {
                    "type": "string",
                    "enum": list(CHANGES_DATASET_COLUMNS),
                },
                "uniqueItems": True,
            },
            "sources": {
                "type": "array",
                "title": "Sources",
                "description": (
                    "Optional subset of user, channel_run, and unattributed. "
                    "Absent or empty returns every source. Hidden entries still advance the cursor."
                ),
                "items": {
                    "type": "string",
                    "enum": list(_SOURCES),
                },
                "uniqueItems": True,
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_LIMIT,
                "default": _DEFAULT_LIMIT,
                "title": "Limit",
                "description": (
                    "Maximum change-log entries scanned in one execution, "
                    "including entries the source filter hides and events with "
                    "no visible side. Default 1000000."
                ),
            },
            "statement_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3600,
                "default": _DEFAULT_TIMEOUT_SEC,
                "title": "Statement timeout",
                "description": (
                    "Wall-clock seconds for the whole load. "
                    "The load stops when this deadline passes. Default 300."
                ),
            },
        },
        ["entity_id"],
    ),
    output_view=OutputView(
        kind="dataset",
        dataset="dataset",
        metrics=("count", "has_more"),
    ),
    execute=_execute,
    refine=_refine,
)
