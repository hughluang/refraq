"""Synchronous editor execution. Not a Channel Run.

The request uses the same engine and executors as a run. Executors see editor
mode only through ``hooks.editor``. Nothing is written, and no Job, run record,
checkpoint, or audit event is created.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from backend.admin.user_store import UserRecord, ensure_system_user, get_user_store
from backend.channel.context import channel_context, platform_context, run_context
from backend.channel.engine import EngineHooks, Executor, NodeResult, execute
from backend.channel.errors import ChannelNotFound, ChannelRequestInvalid
from backend.channel.executors import EXECUTORS
from backend.channel.nodes import loop_ports
from backend.channel.run_store import ChannelRunRecord
from backend.channel.runs import _entry_node, refuse_invalid_closure, require_stop_closure
from backend.channel.sandbox import SandboxFailed, SandboxSession
from backend.channel.schedules import schedule_key_for
from backend.channel.service import require_draft_permissions
from backend.channel.store import get_channel_store
from backend.core.time import format_instant, utc_now
from backend.worker.schedules import get_schedule_store

__all__ = [
    "EDITOR_TIMEOUT_SEC",
    "EditorOptions",
    "editor_executors",
    "execute_editor",
]

EDITOR_TIMEOUT_SEC = 120


@dataclass(frozen=True)
class EditorOptions:
    """What an editor execution changes about the executors."""

    row_limit: int
    pinned: Mapping[str, Any]


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
    user: Any
    schedule: dict[str, Any]
    job_id: str
    _channel_id: str
    executions: list[_NodeExecution] = field(default_factory=list)

    def cancelled(self) -> bool:
        return False

    def superseded(self) -> bool:
        return False

    def evaluate(self, expression: str) -> Any:
        return self.sandbox.evaluate(expression)

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


def editor_executors(executors: Mapping[str, Executor]) -> dict[str, Executor]:
    """Run pinned nodes from their pinned output. Other nodes use ``executors``."""
    return {type_id: _pin_or_run(executor) for type_id, executor in executors.items()}


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
    entry = _entry_node(graph)
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
    options = EditorOptions(row_limit=row_limit, pinned=pinned_map)
    user = ensure_system_user(get_user_store())
    hooks: _EditorHooks | None = None
    try:
        with SandboxSession() as sandbox:
            sandbox.set_context(**context)
            hooks = _EditorHooks(
                editor=options,
                sandbox=sandbox,
                actor=actor_ctx,
                started_at=format_instant(started),
                user=user,
                schedule=_schedule(channel.id, entry_node, started),
                job_id=run_id,
                _channel_id=channel.id,
            )
            outcome = execute(
                graph,
                entry,
                editor_executors(EXECUTORS),
                hooks,
                timeout_sec=EDITOR_TIMEOUT_SEC,
                stop_at_node_id=stop_at_node_id,
                loop_ports=loop_ports(),
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
    found: dict[str, Any] = {}
    for item in pinned:
        node_id = str(item["node_id"])
        if node_id in found:
            raise ChannelRequestInvalid("Pinned node is duplicated")
        node = by_id.get(node_id)
        if node is None:
            raise ChannelRequestInvalid("Pinned node is not in the graph")
        if node.get("type") == "volume.for":
            raise ChannelRequestInvalid("A For node cannot be pinned")
        found[node_id] = item.get("output")
    return found


def _pin_or_run(executor: Executor) -> Executor:
    def run(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
        editor = getattr(hooks, "editor", None)
        if editor is not None and str(node["id"]) in editor.pinned:
            return _pinned_result(node, editor.pinned[str(node["id"])])
        return executor(node, hooks)

    return run


def _pinned_result(node: Mapping[str, Any], output: Any) -> NodeResult:
    ports = None
    if node.get("type") == "transform.if":
        if not isinstance(output, dict) or "value" not in output:
            return NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_FAILED",
                error_message="Pinned If output has no value",
            )
        ports = frozenset({"true" if bool(output["value"]) else "false"})
    return NodeResult(status="pinned", output=output, ports=ports)


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
