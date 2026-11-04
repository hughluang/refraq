"""Changes Dataset node type."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from sqlalchemy.exc import DBAPIError

from backend.channel.change_range import (
    ChangeRange,
    ChangeRangeError,
    _range_errors,
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
from backend.entity.changes import (
    ChangeEntry,
    ChangePosition,
    purge_mark,
    read_changes,
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
    scanned: list[ChangeEntry | None] = [None]
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
            chunks=_pages(opened, hooks, sources, limit, deadline, scanned),
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
    last = scanned[0]
    if last is not None:
        propose_change_range(session, opened, (last,))
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
    scanned: list[ChangeEntry | None],
) -> Iterator[Sequence[Sequence[Any]]]:
    """Yield one page of visible rows at a time.

    Each ``read_changes`` call commits its own short transaction. The dataset
    copy stays the caller's single transaction. Only the last scanned entry is
    kept, and only after the closing purge check passes.
    """
    start = opened.after
    mark_before = purge_mark(opened.entity_id)
    after = start
    seen = 0
    last: ChangeEntry | None = None
    while seen < limit:
        _halt(hooks, deadline)
        page_limit = min(_PAGE, limit - seen)
        with _range_errors():
            page = read_changes(
                opened.entity_id,
                after=after,
                bound=opened.bound,
                limit=page_limit,
            )
        if not page.entries:
            break
        last = page.entries[-1]
        seen += len(page.entries)
        visible = tuple(_row(entry) for entry in page.entries if _kept(entry, sources))
        if visible:
            yield visible
        after = ChangePosition(xact=last.xact, seq=last.sequence)
        if not page.has_more:
            break
    _halt(hooks, deadline)
    mark_after = purge_mark(opened.entity_id)
    if _purge_moved_past_start(start, mark_before, mark_after):
        raise ChangeRangeError("CHANNEL_CHECKPOINT_INVALID", _INVALID)
    scanned[0] = last


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


def _kept(entry: ChangeEntry, sources: set[str] | None) -> bool:
    if sources is None:
        return True
    label = entry.source if entry.source is not None else "unattributed"
    return label in sources


def _row(entry: ChangeEntry) -> tuple[Any, ...]:
    return (
        entry.sequence,
        entry.operation,
        entry.occurred_at,
        entry.source,
        entry.subject,
        entry.physical_table,
        entry.row_id,
        _json_cell(entry.business_key),
        _json_cell(entry.before),
        _json_cell(entry.after),
    )


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
        "Reads the entity Change Log after this node's checkpoint and up to the "
        "commit sequence fixed for the run. Visible rows land in one dataset, and "
        "a checkpoint is proposed only after that dataset is ready. Entries a "
        "source filter hides stay out of the dataset and still count toward the limit."
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
                    "including entries the source filter hides. Default 1000000."
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
