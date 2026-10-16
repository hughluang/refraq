"""Synchronous editor execution. Not a Channel Run.

The request uses the same engine and node catalog as a run. Node types see
editor mode only through ``hooks.editor``. Nothing is written, and no Job, run
record, checkpoint, or audit event is created.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Sequence

from backend.admin.user_store import UserRecord
from backend.channel.channel_run import (
    EditorExecution,
    entry_node_id,
    execute_editor_graph,
    expression_context,
)
from backend.channel.errors import ChannelNotFound, ChannelRequestInvalid, ChannelTriggerInvalid
from backend.channel.nodes import list_node_types
from backend.channel.run_store import ChannelRunRecord
from backend.channel.runs import refuse_invalid_closure, require_stop_closure
from backend.channel.sandbox import SandboxFailed
from backend.channel.service import require_draft_permissions
from backend.channel.store import get_channel_store
from backend.core.time import format_instant, utc_now

__all__ = [
    "EDITOR_TIMEOUT_SEC",
    "execute_editor",
]

EDITOR_TIMEOUT_SEC = 120


def execute_editor(
    *,
    channel_id: str,
    graph: dict[str, Any],
    stop_at_node_id: str,
    row_limit: int,
    pinned: list[dict[str, Any]],
    actor: UserRecord,
    permissions: Sequence[str],
) -> dict[str, Any]:
    channel = get_channel_store().get(channel_id)
    if channel is None:
        raise ChannelNotFound()
    require_draft_permissions(channel.draft_graph, graph, permissions)
    pinned_map = _pinned(graph, pinned)
    closure = require_stop_closure(graph, stop_at_node_id)
    refuse_invalid_closure(graph, channel_id=channel_id, closure=closure)
    entry = entry_node_id(graph)
    if entry is None:
        raise ChannelTriggerInvalid()
    started = utc_now()
    run_id = f"edx_{uuid.uuid4().hex[:12]}"
    actor_ctx = {"id": actor.id, "name": actor.display_name}
    run = ChannelRunRecord(
        job_id=run_id,
        channel_id=channel.id,
        target="draft",
        version=None,
        draft_revision=channel.draft_revision,
        graph=graph,
        trigger_node_id=entry,
        ignore_checkpoints=True,
        outcome=None,
        failed_node_id=None,
        skipped_node_ids=[],
        created_at=started,
        stop_at_node_id=stop_at_node_id,
    )
    context = expression_context(channel, run, started, actor_ctx, "user")
    entry_node = next(node for node in graph["nodes"] if node["id"] == entry)
    executions: list[EditorExecution] = []
    try:
        outcome = execute_editor_graph(
            graph=graph,
            entry_node_id=entry,
            entry_node=entry_node,
            run=run,
            context=context,
            actor=actor_ctx,
            started_at=format_instant(started),
            started=started,
            row_limit=row_limit,
            pinned=pinned_map,
            executions=executions,
            timeout_sec=EDITOR_TIMEOUT_SEC,
        )
    except SandboxFailed as exc:
        return _response(
            status="failed",
            error_code="CHANNEL_SANDBOX_FAILED",
            error_message=str(exc),
            failed_node_id=None,
            stopped_node_id=None,
            executions=executions,
            row_limit=row_limit,
        )
    return _response(
        status=outcome.status,
        error_code=outcome.error_code,
        error_message=outcome.error_message,
        failed_node_id=outcome.failed_node_id,
        stopped_node_id=outcome.stopped_node_id,
        executions=executions,
        row_limit=row_limit,
    )


def _pinned(graph: Mapping[str, Any], pinned: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {str(node["id"]): node for node in graph.get("nodes") or []}
    by_type = {item.type_id: item for item in list_node_types()}
    found: dict[str, Any] = {}
    for item in pinned:
        node_id = str(item["node_id"])
        if node_id in found:
            raise ChannelRequestInvalid("Pinned node is duplicated")
        node = by_id.get(node_id)
        if node is None:
            raise ChannelRequestInvalid("Pinned node is not in the graph")
        spec = by_type.get(str(node.get("type")))
        if spec is not None and not spec.pinnable:
            raise ChannelRequestInvalid("A For node cannot be pinned")
        found[node_id] = item.get("output")
    return found


def _response(
    *,
    status: str,
    error_code: str | None,
    error_message: str | None,
    failed_node_id: str | None,
    stopped_node_id: str | None,
    executions: list[EditorExecution],
    row_limit: int,
) -> dict[str, Any]:
    if status not in {"succeeded", "failed", "cancelled"}:
        status = "failed"
    items = []
    for record in executions:
        output, truncated = _cut(record.output, row_limit)
        items.append(
            {
                "seq": record.seq,
                "node_id": record.node_id,
                "status": record.status,
                "started_at": record.started_at,
                "finished_at": record.finished_at,
                "output": output,
                "truncated": truncated,
                "error_code": record.error_code,
                "error_message": record.error_message,
                "error_detail": record.error_detail,
            }
        )
    return {
        "status": status,
        "error_code": error_code,
        "error_message": error_message,
        "failed_node_id": failed_node_id,
        "stopped_node_id": stopped_node_id,
        "node_executions": items,
    }


def _cut(value: Any, limit: int) -> tuple[Any, bool]:
    truncated = False

    def walk(item: Any) -> Any:
        nonlocal truncated
        if isinstance(item, list):
            if len(item) > limit:
                truncated = True
            return [walk(child) for child in item[:limit]]
        if isinstance(item, dict):
            return {key: walk(child) for key, child in item.items()}
        return item

    return walk(value), truncated
