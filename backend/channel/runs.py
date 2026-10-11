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
from backend.channel.graph import validate
from backend.channel.references import ChannelReferenceResolver
from backend.channel.run_store import ChannelRunRecord, get_run_store
from backend.channel.store import get_channel_store
from backend.core.time import utc_now
from backend.jobs.store import create_queued_job

__all__ = ["start_run"]


def start_run(
    *,
    channel_id: str,
    target: Literal["draft", "published"],
    trigger_node_id: str | None,
    ignore_checkpoints: bool,
    actor: UserRecord,
    actor_token_id: str | None,
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
        problems = validate(graph, ChannelReferenceResolver(channel_id))
        if problems:
            raise ChannelGraphInvalid(problems[0].detail, problems=list(problems))
        version = None
        draft_revision = channel.draft_revision
    entry = _manual_node(graph, trigger_node_id)
    job = create_queued_job(
        kind="channel_run",
        input={
            "channel_id": channel_id,
            "target": target,
            "trigger_node_id": entry,
            "ignore_checkpoints": ignore_checkpoints,
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
    )
    get_run_store().insert_run(record)
    from backend.channel.tasks import run_job

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


def _manual_node(graph: dict[str, Any], trigger_node_id: str | None) -> str:
    manuals = [
        node
        for node in graph.get("nodes") or []
        if node.get("type") == "trigger.manual"
    ]
    if trigger_node_id and any(node["id"] == trigger_node_id for node in manuals):
        return trigger_node_id
    if not trigger_node_id and len(manuals) == 1:
        return str(manuals[0]["id"])
    raise ChannelTriggerInvalid()
