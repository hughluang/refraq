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
        errors = [problem for problem in problems if problem.severity == "error"]
        if errors:
            raise ChannelGraphInvalid(errors[0].detail, problems=list(problems))
        version = None
        draft_revision = channel.draft_revision
    entry = _entry_node(graph)
    job = create_queued_job(
        kind="channel_run",
        input={
            "channel_id": channel_id,
            "target": target,
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


def _entry_node(graph: dict[str, Any]) -> str:
    from backend.channel.nodes import list_node_types

    entry_types = {item.type_id for item in list_node_types() if item.entry}
    entries = [
        node for node in graph.get("nodes") or [] if node.get("type") in entry_types
    ]
    if len(entries) != 1:
        raise ChannelTriggerInvalid()
    return str(entries[0]["id"])
