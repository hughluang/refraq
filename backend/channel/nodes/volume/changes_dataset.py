"""Changes Dataset node type."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

from sqlalchemy.exc import DBAPIError

from backend.channel.change_range import (
    ChangeRange,
    ChangeRangeError,
    open_change_range,
    propose_change_range,
    read_change_range,
)
from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA, dataset_reference
from backend.channel.dataset_registry import (
    DatasetColumnSpec,
    DatasetQuotaExceeded,
    DatasetRegistry,
    get_dataset_store,
)
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
from backend.entity.changes import ChangePosition, purge_mark
from backend.entity.history.service import (
    HistorySide,
    IncrementalEvent,
    IncrementalPosition,
    clear_cell,
)

__all__ = ["NODE_TYPE"]

_PAGE = 10000
_DEFAULT_LIMIT = 1000000
_MAX_LIMIT = 10000000
_DEFAULT_TIMEOUT_SEC = 300
_SOURCES = ("user", "channel_run", "unattributed")
_INVALID = "Checkpoint is behind deleted change-log entries."
_TIMEOUT_MESSAGE = "Changes Dataset exceeded the statement timeout"
_QUOTA_MESSAGE = "Dataset storage is already at the capacity ceiling"

_OUTPUT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["dataset", "count"],
    "properties": {
        "dataset": DATASET_REFERENCE_SCHEMA,
        "count": {"type": "integer", "minimum": 0},
    },
}

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


class _LoadHalted(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"main": _OUTPUT, "error": None}


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    entity_id = str(config["entity_id"])
    node_id = str(node["id"])
    limit = int(config.get("limit", _DEFAULT_LIMIT))
    timeout_sec = int(config.get("statement_timeout_sec", _DEFAULT_TIMEOUT_SEC))
    sources = _sources(config.get("sources"))
    session = hooks.checkpoints
    deadline = time.monotonic() + timeout_sec
    evaluated: list[IncrementalPosition | None] = [None]
    try:
        opened = open_change_range(
            entity_id,
            node_id,
            session,
            ignore_checkpoints=hooks.ignore_checkpoints,
        )
        record = DatasetRegistry(get_dataset_store()).create_from_chunks(
            job_id=hooks.run_id,
            node_id=node_id,
            seq=_execution_seq(node, hooks),
            columns=_COLUMNS,
            chunks=_pages(opened, hooks, sources, limit, deadline, evaluated),
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
        return _failed("CHANNEL_NODE_FAILED", _db_message(exc))
    except Exception as exc:  # noqa: BLE001
        return _failed("CHANNEL_NODE_FAILED", str(exc))
    propose_change_range(session, opened, evaluated[0])
    reference = dataset_reference(
        dataset_id=record.id,
        columns=record.columns,
        count=record.row_count,
    )
    return NodeResult(
        status="succeeded",
        output={"dataset": reference, "count": record.row_count},
    )


def _pages(
    opened: ChangeRange,
    hooks: EngineHooks,
    sources: set[str] | None,
    limit: int,
    deadline: float,
    evaluated: list[IncrementalPosition | None],
) -> Iterator[Sequence[Sequence[Any]]]:
    """Yield one page of projected rows at a time.

    Each ``read_change_range`` call authorizes the platform System Identity
    and commits its own short transaction. The dataset copy stays the caller's
    single transaction. The proposal is the last page's progress, and only
    after the closing purge check passes. A page that scans nothing does not
    replace that progress.
    """
    start = opened.after
    mark_before = purge_mark(opened.entity_id)
    cursor: IncrementalPosition | None = None
    seen = 0
    progress: IncrementalPosition | None = None
    while seen < limit:
        _halt(hooks, deadline)
        page_limit = min(_PAGE, limit - seen)
        page = read_change_range(opened, limit=page_limit, after=cursor)
        if page.progress is None:
            break
        progress = page.progress
        cursor = page.progress
        visible = tuple(_row(entry) for entry in page.events if _kept(entry, sources))
        if visible:
            yield visible
        if not page.has_more:
            break
        seen += page_limit
    _halt(hooks, deadline)
    mark_after = purge_mark(opened.entity_id)
    if _purge_moved_past_start(start, mark_before, mark_after):
        raise ChangeRangeError("CHANNEL_CHECKPOINT_INVALID", _INVALID)
    evaluated[0] = progress


def _purge_moved_past_start(
    start: ChangePosition | None,
    before: ChangePosition | None,
    after: ChangePosition | None,
) -> bool:
    """A purge that commits during the load and passes the start position.

    A mark that was already there at the start does not fail the load. That
    keeps a historical purge, and ``ignore_checkpoints``, on the Read Changes
    path. ``start`` none means the beginning: any new deletion passes it.
    """
    if after is None:
        return False
    if before is not None and (after.xact, after.seq) <= (before.xact, before.seq):
        return False
    if start is None:
        return True
    return (start.xact, start.seq) < (after.xact, after.seq)


def _halt(hooks: EngineHooks, deadline: float) -> None:
    if hooks.cancelled():
        raise _LoadHalted("cancelled")
    if hooks.superseded():
        raise _LoadHalted("superseded")
    if time.monotonic() >= deadline:
        raise _LoadHalted("timeout")


def _sources(raw: Any) -> set[str] | None:
    if not isinstance(raw, list) or not raw:
        return None
    return {str(item) for item in raw}


def _kept(entry: IncrementalEvent, sources: set[str] | None) -> bool:
    if sources is None:
        return True
    label = entry.source if entry.source is not None else "unattributed"
    return label in sources


def _row(entry: IncrementalEvent) -> tuple[Any, ...]:
    return (
        entry.sequence,
        entry.operation,
        entry.occurred_at,
        entry.source,
        entry.subject,
        entry.physical_table,
        entry.version_id,
        entry.version_number,
        _agreed(entry, "row_id", _integer_cell),
        _json_cell(_agreed(entry, entry.business_key_name, clear_cell)),
        _json_cell(_side(entry.before)),
        _json_cell(_side(entry.after)),
    )


def _side(side: HistorySide) -> dict[str, Any]:
    if side.state != "visible":
        return {"state": side.state}
    return {"state": "visible", "values": side.values}


def _integer_cell(side: HistorySide, name: str) -> int | None:
    """A clear integer on this side. A bool is not a row id."""
    value = clear_cell(side, name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _agreed(
    entry: IncrementalEvent,
    name: str | None,
    cell: Callable[[HistorySide, str], Any],
) -> Any:
    """One value when every visible side yields that same cell, or none.

    A missing name, a cell the predicate does not yield, or visible sides
    that disagree leave the dataset cell empty. None of those fail the load.
    """
    if not name:
        return None
    found: list[Any] = []
    for side in (entry.before, entry.after):
        if side.state != "visible":
            continue
        value = cell(side, name)
        if value is None:
            return None
        found.append(value)
    if not found or any(item != found[0] for item in found[1:]):
        return None
    return found[0]


def _json_cell(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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
    output_view=OutputView(kind="dataset", dataset="dataset", metrics=("count",)),
    execute=_execute,
    refine=_refine,
)
