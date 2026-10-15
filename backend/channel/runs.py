"""Queue an on-demand Channel Run."""

from __future__ import annotations

from typing import Any, Literal

from backend.admin.audit import persist_audit_event
from backend.admin.user_store import UserRecord
from backend.channel.errors import (
    ChannelGraphInvalid,
    ChannelNotFound,
    ChannelNotPublished,
    ChannelTriggerInvalid,
)
from backend.channel.graph import ancestor_closure, validate
from backend.channel.nodes import list_node_types
from backend.channel.references import ChannelReferenceResolver
from backend.channel.tasks import run_job
from backend.channel.run_store import ChannelRunRecord, get_run_store
from backend.channel.store import get_channel_store
from backend.core.time import utc_now
from backend.jobs.store import create_queued_job

__all__ = ["refuse_invalid_closure", "require_stop_closure", "start_run"]


def start_run(
    *,
    channel_id: str,
    target: Literal["draft", "published"],
    ignore_checkpoints: bool,
    actor: UserRecord,
    actor_token_id: str | None,
    stop_at_node_id: str | None = None,
) -> Any:
    store = get_channel_store()
    channel = store.get(channel_id)
    if channel is None:
        raise ChannelNotFound()
    if target == "published":
        versions, _total = store.list_versions(channel_id, limit=1, offset=0)
        if not versions:
            raise ChannelNotPublished()
        graph = versions[0].graph
        version = versions[0].number
        draft_revision = None
    elif target == "draft":
        graph = channel.draft_graph
        version = None
        draft_revision = channel.draft_revision
    closure = require_stop_closure(graph, stop_at_node_id)
    if target == "draft" or closure is not None:
        refuse_invalid_closure(graph, channel_id=channel_id, closure=closure)
    entry = _entry_node(graph)
    job = create_queued_job(
        kind="channel_run",
        input={
            "channel_id": channel_id,
            "target": target,
            "ignore_checkpoints": ignore_checkpoints,
            "stop_at_node_id": stop_at_node_id,
        },
        trigger_kind="user",
        trigger_ref=actor.id,
        summary=f"channel_run {channel.name}",
        created_by=actor.id,
    )
    record = ChannelRunRecord(
        job_id=job.id,
        channel_id=channel_id,
        target=target,
        version=version if target == "published" else None,
        draft_revision=draft_revision,
        graph=graph if target == "draft" else None,
        trigger_node_id=entry,
        ignore_checkpoints=ignore_checkpoints,
        outcome=None,
        failed_node_id=None,
        skipped_node_ids=[],
        created_at=utc_now(),
        stop_at_node_id=stop_at_node_id,
    )
    get_run_store().insert_run(record)
    run_job.apply_async(args=[job.id], task_id=job.id)
    persist_audit_event(
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
        resource_type="channel",
        resource_id=channel_id,
        action="channel.run_enqueue",
        result="success",
        detail={"job_id": job.id, "target": target},
    )
    return job, record


def _entry_node(graph: dict[str, Any]) -> str:
    entry_types = {item.type_id for item in list_node_types() if item.entry}
    entries = [
        node for node in graph.get("nodes") or [] if node.get("type") in entry_types
    ]
    if len(entries) != 1:
        raise ChannelTriggerInvalid()
    return str(entries[0]["id"])


def require_stop_closure(graph: dict[str, Any], stop_at_node_id: str | None) -> set[str] | None:
    """Ancestor closure of the stop node, including it.

    ``None`` when the run has no stop node. A missing stop node is
    ``CHANNEL_GRAPH_INVALID`` with an empty ``problems`` list.
    """
    if stop_at_node_id is None:
        return None
    closure = ancestor_closure(graph, stop_at_node_id)
    if closure is None:
        raise ChannelGraphInvalid("Stop node is not in the graph")
    return closure


def refuse_invalid_closure(
    graph: dict[str, Any],
    *,
    channel_id: str,
    closure: set[str] | None,
) -> None:
    """Refuse errors inside the stop closure, and errors that name no node.

    ``closure`` ``None`` refuses every error, which is a draft run with no stop node.
    """
    problems = validate(graph, ChannelReferenceResolver(channel_id))
    errors = [
        problem
        for problem in problems
        if problem.severity == "error"
        and (closure is None or problem.node_id is None or problem.node_id in closure)
    ]
    if errors:
        raise ChannelGraphInvalid(errors[0].detail, problems=errors)
