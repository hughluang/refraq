"""Read Changes node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.change_range import (
    ChangeRange,
    ChangeRangeError,
    open_change_range,
    read_change_range,
)
from backend.channel.checkpoints import CheckpointPosition
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    CheckpointView,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    object_schema,
)
from backend.entity.history.service import (
    HistorySide,
    IncrementalEvent,
    IncrementalPosition,
)

__all__ = ["NODE_TYPE"]

_DEFAULT_LIMIT = 1000
_SOURCES = ("user", "channel_run", "unattributed")
_UNSAFE = "Net grouping has no clear projected identity."

_OUTPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entries", "count", "has_more", "last_sequence"],
    "properties": {
        "entries": {"type": "array", "items": {"type": "object"}},
        "count": {"type": "integer"},
        "has_more": {"type": "boolean"},
        "last_sequence": {"type": ["integer", "null"]},
    },
}


def _refine(
    config: Mapping[str, Any],
    upstream: Mapping[str, Any],
    resolver: Any,
) -> dict[str, Any]:
    del config, upstream, resolver
    return {"main": _OUTPUT, "error": None}


class _GroupingUnsafe(Exception):
    """Net grouping cannot keep a clear projected identity."""


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    entity_id = str(config["entity_id"])
    node_id = str(node["id"])
    limit = int(config.get("limit") or _DEFAULT_LIMIT)
    shape = str(config.get("shape") or "entries")
    sources = _sources(config.get("sources"))
    session = hooks.checkpoints
    try:
        opened = open_change_range(
            entity_id,
            node_id,
            session,
            ignore_checkpoints=hooks.ignore_checkpoints,
        )
        page = read_change_range(opened, limit=limit)
        visible = [entry for entry in page.events if _kept(entry, sources)]
        rows = (
            _net(visible) if shape == "net" else [_record(entry) for entry in visible]
        )
    except _GroupingUnsafe:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_CHANGE_LOG_GROUPING_UNSAFE",
            error_message=_UNSAFE,
        )
    except ChangeRangeError as exc:
        return NodeResult(
            status="failed",
            error_code=exc.code,
            error_message=exc.message,
        )
    except Exception as exc:  # noqa: BLE001
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
        )
    _propose(session, opened, page.progress)
    return NodeResult(
        status="succeeded",
        output={
            "entries": rows,
            "count": len(rows),
            "has_more": page.has_more,
            "last_sequence": None if page.progress is None else page.progress.seq,
        },
    )


def _sources(raw: Any) -> set[str] | None:
    if not isinstance(raw, list) or not raw:
        return None
    return {str(item) for item in raw}


def _propose(
    session: CheckpointView,
    opened: ChangeRange,
    progress: IncrementalPosition | None,
) -> None:
    """Propose the operation's evaluated position. An empty scan proposes nothing."""
    if progress is None:
        return
    session.propose(
        opened.node_id,
        opened.entity_id,
        CheckpointPosition(xact=progress.commit_seq, seq=progress.seq),
    )


def _kept(entry: IncrementalEvent, sources: set[str] | None) -> bool:
    if sources is None:
        return True
    label = entry.source if entry.source is not None else "unattributed"
    return label in sources


def _record(entry: IncrementalEvent) -> dict[str, Any]:
    return {
        "sequence": entry.sequence,
        "operation": entry.operation,
        "occurred_at": entry.occurred_at,
        "source": entry.source,
        "subject": entry.subject,
        "physical_table": entry.physical_table,
        "version_id": entry.version_id,
        "version_number": entry.version_number,
        "before": _side(entry.before),
        "after": _side(entry.after),
    }


def _side(side: HistorySide) -> dict[str, Any]:
    if side.state != "visible":
        return {"state": side.state}
    return {"state": "visible", "values": side.values}


def _net(entries: list[IncrementalEvent]) -> list[dict[str, Any]]:
    """Fold one page. A key that is inserted and later deleted in the page is dropped."""
    order: list[tuple[Any, ...]] = []
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for entry in entries:
        identity = _identity(entry)
        group = groups.get(identity)
        if group is None:
            group = {"first": entry, "last": entry}
            groups[identity] = group
            order.append(identity)
        else:
            group["last"] = entry
    rows: list[dict[str, Any]] = []
    for identity in order:
        group = groups[identity]
        first: IncrementalEvent = group["first"]
        last: IncrementalEvent = group["last"]
        if first.operation == "insert" and last.operation == "delete":
            continue
        if first.operation == "insert":
            operation = "insert"
            before = first.before
            after = last.after
        elif last.operation == "delete":
            operation = "delete"
            before = first.before
            after = last.after
        else:
            operation = "update"
            before = first.before
            after = last.after
        row = _record(last)
        del row["sequence"]
        row["operation"] = operation
        row["before"] = _side(before)
        row["after"] = _side(after)
        row["first_sequence"] = first.sequence
        row["last_sequence"] = last.sequence
        if identity[1][0] == "row_id":
            row["business_key"] = None
            row["row_id"] = identity[1][1]
        else:
            row["business_key"] = identity[1][1]
            row["row_id"] = _agreed(last, "row_id")
        rows.append(row)
    return rows


def _identity(entry: IncrementalEvent) -> tuple[Any, ...]:
    key_name = entry.business_key_name
    if not key_name:
        return (entry.physical_table, ("row_id", _required(entry, "row_id")))
    return (entry.physical_table, ("business_key", _required(entry, key_name)))


def _required(entry: IncrementalEvent, name: str) -> Any:
    found: list[Any] = []
    for side in _visible(entry):
        values = side.values or {}
        withheld = values.get("__withheld") or []
        if name in side.masked or name in withheld or name not in values:
            raise _GroupingUnsafe()
        found.append(values[name])
    if not found or any(item != found[0] for item in found[1:]):
        raise _GroupingUnsafe()
    return found[0]


def _agreed(entry: IncrementalEvent, name: str) -> Any:
    found: list[Any] = []
    for side in _visible(entry):
        values = side.values or {}
        if name not in values:
            return None
        found.append(values[name])
    if not found or any(item != found[0] for item in found[1:]):
        return None
    return found[0]


def _visible(entry: IncrementalEvent) -> list[HistorySide]:
    return [side for side in (entry.before, entry.after) if side.state == "visible"]


NODE_TYPE = NodeType(
    type_id="read.changes",
    family="read",
    label="Read Changes",
    summary="Reads new Change Log entries for one Business Entity.",
    description=(
        "Reads the entity Change Log as the platform System Identity after this "
        "node's checkpoint and up to the commit sequence fixed for the run. "
        "Returned sides are projected. The checkpoint advances only when the "
        "whole run completes. Entries the source filter hides, and events with "
        "no visible side, still count as scanned. Net grouping fails when the "
        "projected Business Key is not clear. Use Changes Dataset to read more "
        "than one page in a run."
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
                "description": "Business Entity whose Change Log is read.",
                "x-refraq-ref": "entity",
                "x-refraq-resolve": "execution",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100000,
                "default": _DEFAULT_LIMIT,
                "title": "Limit",
                "description": "Maximum change-log entries read in one execution. Default 1000.",
            },
            "shape": {
                "type": "string",
                "enum": ["entries", "net"],
                "default": "entries",
                "title": "Shape",
                "description": (
                    "entries returns each visible change. net folds one page by the "
                    "projected Business Key when that version declares one, or by "
                    "row_id when it does not. A declared key that is masked, withheld, "
                    "outside the shape, or only on an unreadable side fails the node."
                ),
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
        },
        ["entity_id"],
    ),
    output_view=OutputView(
        kind="rows",
        rows="entries",
        metrics=("count", "has_more"),
    ),
    execute=_execute,
    refine=_refine,
)
