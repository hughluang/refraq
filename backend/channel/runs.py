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
    ChannelRunNotFound,
    ChannelRunNotRerunnable,
    ChannelTriggerInvalid,
)
from backend.channel.graph import ancestor_closure, validate
from backend.channel.references import ChannelReferenceResolver
from backend.channel.run_store import get_run_store
from backend.channel.store import get_channel_store
from backend.jobs.store import get_job_store

__all__ = ["refuse_invalid_closure", "require_stop_closure", "rerun_failed", "start_run"]


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


def rerun_failed(
    *,
    channel_id: str,
    job_id: str,
    actor: UserRecord,
    actor_token_id: str | None,
) -> Any:
    """Queue a new published run pinned to a failed run's version."""
    store = get_channel_store()
    if store.get(channel_id) is None:
        raise ChannelNotFound()
    run = get_run_store().get_run(job_id)
    if run is None or run.channel_id != channel_id:
        raise ChannelRunNotFound()
    job = get_job_store().get(job_id)
    if (
        job is None
        or job.status != "failed"
        or run.target != "published"
        or run.version is None
        or store.get_version(channel_id, run.version) is None
    ):
        raise ChannelRunNotRerunnable()
    channel = store.get(channel_id)
    assert channel is not None
    version = store.get_version(channel_id, run.version)
    assert version is not None
    trigger = trigger_node_id(version.graph) or run.trigger_node_id
    queued, record = mint_on_demand_run(
        channel_id=channel_id,
        channel_name=channel.name,
        target="published",
        ignore_checkpoints=False,
        actor_id=actor.id,
        trigger_node_id=trigger,
        version=run.version,
        draft_revision=None,
        graph=None,
        stop_at_node_id=None,
        pin_version=True,
    )
    dispatch(queued.id)
    persist_audit_event(
        actor_user_id=actor.id,
        actor_token_id=actor_token_id,
        resource_type="channel",
        resource_id=channel_id,
        action="channel.rerun_enqueue",
        result="success",
        detail={"job_id": queued.id, "source_job_id": job_id, "version": run.version},
    )
    return queued, record


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
