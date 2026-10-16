"""One home for a Channel Run's entry rule, minting, and dispatch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from backend.channel.nodes import list_node_types
from backend.channel.run_store import ChannelRunRecord, get_run_store
from backend.channel.store import get_channel_store
from backend.channel.tasks import run_job
from backend.core.time import utc_now
from backend.jobs.store import (
    JobRecord,
    UniqueScheduledForError,
    create_queued_job,
    format_job_log_line,
    get_job_store,
)

Dispatcher = Callable[[str], object]

__all__ = [
    "ScheduledMint",
    "dispatch",
    "entry_node_id",
    "mint_on_demand_run",
    "mint_scheduled_run",
    "set_dispatcher",
]


@dataclass(frozen=True)
class ScheduledMint:
    status: Literal["missing_channel", "already_minted", "queued"]
    job_id: str
    job: JobRecord | None
    mint_at: datetime | None


def entry_node_id(graph: dict[str, Any]) -> str | None:
    entry_types = {item.type_id for item in list_node_types() if item.entry}
    entries = [
        node for node in graph.get("nodes") or [] if node.get("type") in entry_types
    ]
    if len(entries) != 1:
        return None
    return str(entries[0]["id"])


def mint_on_demand_run(
    *,
    channel_id: str,
    channel_name: str,
    target: Literal["draft", "published"],
    ignore_checkpoints: bool,
    actor_id: str,
    trigger_node_id: str,
    version: int | None,
    draft_revision: int | None,
    graph: dict[str, Any] | None,
    stop_at_node_id: str | None,
) -> tuple[JobRecord, ChannelRunRecord]:
    job = create_queued_job(
        kind="channel_run",
        input={
            "channel_id": channel_id,
            "target": target,
            "ignore_checkpoints": ignore_checkpoints,
            "stop_at_node_id": stop_at_node_id,
        },
        trigger_kind="user",
        trigger_ref=actor_id,
        summary=f"channel_run {channel_name}",
        created_by=actor_id,
    )
    record = _channel_run_record(
        job_id=job.id,
        channel_id=channel_id,
        target=target,
        version=version if target == "published" else None,
        draft_revision=draft_revision,
        graph=graph if target == "draft" else None,
        trigger_node_id=trigger_node_id,
        ignore_checkpoints=ignore_checkpoints,
        created_at=utc_now(),
        stop_at_node_id=stop_at_node_id,
    )
    get_run_store().insert_run(record)
    return job, record


def mint_scheduled_run(
    *,
    schedule_id: str,
    channel_id: str | None,
    node_id: str | None,
    scheduled_for: datetime,
    now: datetime,
    session: Any,
) -> ScheduledMint:
    if not channel_id:
        return ScheduledMint("missing_channel", "", None, None)
    already = False
    try:
        job = create_queued_job(
            kind="channel_run",
            input={
                "channel_id": channel_id,
                "target": "published",
                "ignore_checkpoints": False,
            },
            created_by=None,
            summary=f"channel_run {channel_id}",
            trigger_kind="schedule",
            trigger_ref=schedule_id,
            log_body=format_job_log_line(level="info", message="queued channel run", at=now),
            scheduled_for=scheduled_for,
            running_timeout_sec=None,
            session=session,
            created_at=now,
        )
    except UniqueScheduledForError as exc:
        already = True
        found = get_job_store().get(exc.existing_job_id or "", session=session)
        if found is None:
            return ScheduledMint("already_minted", exc.existing_job_id or "", None, None)
        job = found
    if not already and get_channel_store().get(channel_id) is not None:
        get_run_store().insert_run(
            _channel_run_record(
                job_id=job.id,
                channel_id=channel_id,
                target="published",
                version=None,
                draft_revision=None,
                graph=None,
                trigger_node_id=node_id or "",
                ignore_checkpoints=False,
                created_at=now,
            )
        )
    return ScheduledMint(
        "already_minted" if already else "queued",
        job.id,
        job,
        job.created_at if already else now,
    )


def _channel_run_record(
    *,
    job_id: str,
    channel_id: str,
    target: str,
    version: int | None,
    draft_revision: int | None,
    graph: dict[str, Any] | None,
    trigger_node_id: str,
    ignore_checkpoints: bool,
    created_at: datetime,
    stop_at_node_id: str | None = None,
) -> ChannelRunRecord:
    return ChannelRunRecord(
        job_id=job_id,
        channel_id=channel_id,
        target=target,
        version=version,
        draft_revision=draft_revision,
        graph=graph,
        trigger_node_id=trigger_node_id,
        ignore_checkpoints=ignore_checkpoints,
        outcome=None,
        failed_node_id=None,
        skipped_node_ids=[],
        created_at=created_at,
        stop_at_node_id=stop_at_node_id,
    )


def _enqueue(job_id: str) -> None:
    task: Any = run_job
    task.apply_async(args=[job_id], task_id=job_id)


_dispatcher: Dispatcher = _enqueue


def set_dispatcher(dispatcher: Dispatcher) -> Dispatcher:
    global _dispatcher
    previous = _dispatcher
    _dispatcher = dispatcher
    return previous


def dispatch(job_id: str) -> None:
    _dispatcher(job_id)
