"""Queue an on-demand Channel Run."""

from __future__ import annotations

from typing import Any, Literal

from backend.admin.audit import persist_audit_event
from backend.admin.user_store import UserRecord
from backend.channel.channel_run import dispatch, mint_on_demand_run, trigger_node_id
from backend.channel.errors import (
    ChannelGraphInvalid,
    ChannelNotFound,
    ChannelNotPublished,
    ChannelTriggerInvalid,
)
from backend.channel.graph import ancestor_closure, validate
from backend.channel.references import ChannelReferenceResolver
from backend.channel.store import get_channel_store

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
    trigger = trigger_node_id(graph)
    if trigger is None:
        raise ChannelTriggerInvalid()
    job, record = mint_on_demand_run(
        channel_id=channel_id,
        channel_name=channel.name,
        target=target,
        ignore_checkpoints=ignore_checkpoints,
        actor_id=actor.id,
        trigger_node_id=trigger,
        version=version,
        draft_revision=draft_revision,
        graph=graph,
        stop_at_node_id=stop_at_node_id,
    )
    dispatch(job.id)
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
