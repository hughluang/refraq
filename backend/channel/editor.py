"""Synchronous editor execution. Not a Channel Run.

The request uses the same engine and node catalog as a run. Node types see
editor mode only through ``hooks.editor``. Nothing is written, and no Job, run
record, checkpoint, or audit event is created.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.admin.user_store import UserRecord, ensure_system_user, get_user_store
from backend.channel.channel_run import entry_node_id
from backend.channel.context import channel_context, platform_context, run_context
from backend.channel.engine import execute
from backend.channel.errors import ChannelNotFound, ChannelRequestInvalid, ChannelTriggerInvalid
from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import EditorOptions, NodeResult, PinnedOutput
from backend.channel.references import ChannelReferenceResolver
from backend.channel.run_store import ChannelRunRecord
from backend.channel.runs import refuse_invalid_closure, require_stop_closure
from backend.channel.sandbox import SandboxFailed, SandboxSession
from backend.channel.schedules import schedule_key_for
from backend.channel.service import require_draft_permissions
from backend.channel.store import get_channel_store
from backend.core.time import format_instant, utc_now
from backend.worker.schedules import get_schedule_store

__all__ = [
    "EDITOR_TIMEOUT_SEC",
    "execute_editor",
]

EDITOR_TIMEOUT_SEC = 120


@dataclass
class _NodeExecution:
    seq: int
    node_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    output: Any = None
    error_code: str | None = None
    error_message: str | None = None
    error_detail: dict[str, Any] | None = None


@dataclass
class _EditorHooks:
    editor: EditorOptions
    sandbox: SandboxSession
    actor: dict[str, str]
    started_at: str
    user: UserRecord
    schedule: dict[str, Any]
    run_id: str
    channel_id: str
    pinned: dict[str, Any]
    executions: list[_NodeExecution] = field(default_factory=list)

    def cancelled(self) -> bool:
        return False

    def superseded(self) -> bool:
        return False

    def evaluate(self, expression: str) -> Any:
        return self.sandbox.evaluate(expression)

    def run_code(self, source: str, timeout_sec: float) -> Any:
        return self.sandbox.run_code(source, timeout_sec)

    def pinned_output(self, node: Mapping[str, Any]) -> PinnedOutput | None:
        node_id = str(node["id"])
        if node_id not in self.pinned:
            return None
        return PinnedOutput(self.pinned[node_id])

    def on_start(self, node: Mapping[str, Any]) -> int:
        seq = len(self.executions) + 1
        self.executions.append(
            _NodeExecution(
                seq=seq,
                node_id=str(node["id"]),
                status="running",
                started_at=utc_now(),
            )
        )
        return seq

    def on_finish(self, seq: int, node: Mapping[str, Any], result: NodeResult) -> None:
        del node
        record = next((item for item in self.executions if item.seq == seq), None)
        if record is None:
            return
        record.status = result.status
        record.finished_at = utc_now()
        record.output = result.output
        record.error_code = result.error_code
        record.error_message = result.error_message
        record.error_detail = result.error_detail

    def on_output(self, node: Mapping[str, Any], output: Any) -> None:
        self.sandbox.put_output(
            ref=str(node.get("ref") or node["id"]),
            name=str(node.get("name") or ""),
            output=output,
        )

    def drop_outputs(self, refs: list[str]) -> None:
        self.sandbox.drop_outputs(refs)


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
    context = {
        "channel": channel_context(channel, run),
        "run": run_context(run, started, actor_ctx, "user"),
        "platform": platform_context(started),
    }
    entry_node = next(node for node in graph["nodes"] if node["id"] == entry)
    user = ensure_system_user(get_user_store())
    hooks: _EditorHooks | None = None
    try:
        with SandboxSession() as sandbox:
            sandbox.set_context(**context)
            hooks = _EditorHooks(
                editor=EditorOptions(row_limit=row_limit),
                sandbox=sandbox,
                actor=actor_ctx,
                started_at=format_instant(started),
                user=user,
                schedule=_schedule(channel.id, entry_node, started),
                run_id=run_id,
                channel_id=channel.id,
                pinned=pinned_map,
            )
            outcome = execute(
                graph,
                entry,
                list_node_types(),
                ChannelReferenceResolver(channel.id),
                hooks,
                timeout_sec=EDITOR_TIMEOUT_SEC,
                stop_at_node_id=stop_at_node_id,
            )
    except SandboxFailed as exc:
        return _response(
            status="failed",
            error_code="CHANNEL_SANDBOX_FAILED",
            error_message=str(exc),
            failed_node_id=None,
            stopped_node_id=None,
            executions=[] if hooks is None else hooks.executions,
            row_limit=row_limit,
        )
    return _response(
        status=outcome.status,
        error_code=outcome.error_code,
        error_message=outcome.error_message,
        failed_node_id=outcome.failed_node_id,
        stopped_node_id=outcome.stopped_node_id,
        executions=hooks.executions,
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


def _schedule(channel_id: str, node: Mapping[str, Any], started: datetime) -> dict[str, Any]:
    row = get_schedule_store().get_by_key(schedule_key_for(channel_id))
    node_name = str(node.get("name") or "")
    return {
        "schedule_id": row.id if row is not None else None,
        "name": row.name if row is not None else node_name,
        "scheduled_for": format_instant(started),
    }


def _response(
    *,
    status: str,
    error_code: str | None,
    error_message: str | None,
    failed_node_id: str | None,
    stopped_node_id: str | None,
    executions: list[_NodeExecution],
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
