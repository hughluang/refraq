"""Read Changes node type."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.checkpoints import CheckpointPosition
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
from backend.entity.changes import (
    ChangeEntry,
    ChangeLogOff,
    ChangePosition,
    purge_mark,
    read_changes,
    recording_enabled,
)
from backend.entity.errors import EntityNotFound

__all__ = ["NODE_TYPE"]

_DEFAULT_LIMIT = 1000
_SOURCES = ("user", "channel_run", "unattributed")

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


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    entity_id = str(config["entity_id"])
    node_id = str(node["id"])
    limit = int(config.get("limit") or _DEFAULT_LIMIT)
    shape = str(config.get("shape") or "entries")
    sources = _sources(config.get("sources"))
    try:
        if not recording_enabled(entity_id):
            return _off()
        session = hooks.checkpoints
        if not hooks.ignore_checkpoints:
            durable = session.durable(node_id, entity_id)
            mark = purge_mark(entity_id)
            if (
                durable is not None
                and mark is not None
                and (durable.xact, durable.seq) < (mark.xact, mark.seq)
            ):
                return NodeResult(
                    status="failed",
                    error_code="CHANNEL_CHECKPOINT_INVALID",
                    error_message="Checkpoint is behind deleted change-log entries.",
                )
        after = (
            session.proposed(node_id, entity_id)
            if hooks.ignore_checkpoints
            else session.stored(node_id, entity_id)
        )
        bound = session.bound(node_id, entity_id)
        page = read_changes(
            entity_id,
            after=_change_position(after),
            bound=bound,
            limit=limit,
        )
    except ChangeLogOff:
        return _off()
    except EntityNotFound:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Entity does not resolve",
        )
    except Exception as exc:  # noqa: BLE001
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
        )
    if page.entries:
        last = page.entries[-1]
        session.propose(
            node_id,
            entity_id,
            CheckpointPosition(xact=last.xact, seq=last.sequence),
        )
    visible = [entry for entry in page.entries if _kept(entry, sources)]
    rows = _net(visible) if shape == "net" else [_record(entry) for entry in visible]
    return NodeResult(
        status="succeeded",
        output={
            "entries": rows,
            "count": len(rows),
            "has_more": page.has_more,
            "last_sequence": page.entries[-1].sequence if page.entries else None,
        },
    )


def _off() -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_CHANGE_LOG_OFF",
        error_message="Change recording is off for this entity.",
    )


def _sources(raw: Any) -> set[str] | None:
    if not isinstance(raw, list) or not raw:
        return None
    return {str(item) for item in raw}


def _kept(entry: ChangeEntry, sources: set[str] | None) -> bool:
    if sources is None:
        return True
    label = entry.source if entry.source is not None else "unattributed"
    return label in sources


def _change_position(position: CheckpointPosition | None) -> ChangePosition | None:
    if position is None:
        return None
    return ChangePosition(xact=position.xact, seq=position.seq)


def _record(entry: ChangeEntry) -> dict[str, Any]:
    return {
        "sequence": entry.sequence,
        "operation": entry.operation,
        "occurred_at": entry.occurred_at,
        "source": entry.source,
        "subject": entry.subject,
        "physical_table": entry.physical_table,
        "row_id": entry.row_id,
        "business_key": entry.business_key,
        "before": entry.before,
        "after": entry.after,
    }


def _net(entries: list[ChangeEntry]) -> list[dict[str, Any]]:
    """Fold one page. A key that is inserted and later deleted in the page is dropped."""
    order: list[tuple[Any, ...]] = []
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for entry in entries:
        identity: tuple[Any, ...] = (
            entry.physical_table,
            ("business_key", entry.business_key)
            if entry.has_business_key
            else ("row_id", entry.row_id),
        )
        group = groups.get(identity)
        if group is None:
            group = {
                "first": entry,
                "last": entry,
            }
            groups[identity] = group
            order.append(identity)
        else:
            group["last"] = entry
    rows: list[dict[str, Any]] = []
    for identity in order:
        group = groups[identity]
        first: ChangeEntry = group["first"]
        last: ChangeEntry = group["last"]
        if first.operation == "insert" and last.operation == "delete":
            continue
        if first.operation == "insert":
            operation = "insert"
            before = None
            after = last.after
        elif last.operation == "delete":
            operation = "delete"
            before = first.before
            after = None
        else:
            operation = "update"
            before = first.before
            after = last.after
        rows.append(
            {
                "operation": operation,
                "occurred_at": last.occurred_at,
                "source": last.source,
                "subject": last.subject,
                "physical_table": last.physical_table,
                "row_id": last.row_id,
                "business_key": last.business_key,
                "before": before,
                "after": after,
                "first_sequence": first.sequence,
                "last_sequence": last.sequence,
            }
        )
    return rows


NODE_TYPE = NodeType(
    type_id="read.changes",
    family="read",
    label="Read Changes",
    summary="Reads new Change Log entries for one Business Entity.",
    description=(
        "Reads the entity Change Log after this node's checkpoint and below a "
        "snapshot bound fixed for the run. The checkpoint advances only when "
        "the whole run completes. Entries the source filter hides still count."
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
                    "entries returns each change. net folds one page by Business Key, "
                    "or by row_id when the version has no Business Key."
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
