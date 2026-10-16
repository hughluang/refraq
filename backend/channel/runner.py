"""Claim a channel_run Job and execute its graph."""

from __future__ import annotations

import time
from typing import Any

from backend.admin.user_store import get_user_store
from backend.channel.channel_run import entry_node_id, execute_channel_run, expression_context
from backend.channel.run_store import get_run_store, note_killed_run
from backend.channel.sandbox import SandboxFailed
from backend.channel.store import get_channel_store
from backend.core.time import ensure_aware_utc, format_instant, utc_now
from backend.jobs.store import (
    append_job_log,
    claim_for_execution,
    current_worker_id,
    get_job_store,
    mark_cancelled,
    mark_failed,
    mark_succeeded,
)

__all__ = ["note_killed_run", "run_channel_job"]


def run_channel_job(job_id: str) -> dict[str, str]:
    claimed = claim_for_execution(job_id, claimed_by=current_worker_id())
    if claimed is None:
        record = get_job_store().get(job_id)
        return {"status": record.status if record else "missing"}
    store = get_run_store()
    run = store.get_run(job_id)
    if run is None:
        mark_cancelled(job_id)
        return {"status": "cancelled"}
    channel = get_channel_store().get(run.channel_id)
    if channel is None:
        _cancel(job_id, run, run.trigger_node_id or None)
        return {"status": "cancelled"}
    graph, version = _resolve_graph(run)
    if graph is None:
        _cancel(job_id, run, None)
        return {"status": "cancelled"}
    entry = entry_node_id(graph)
    entry_node = next((node for node in graph["nodes"] if node["id"] == entry), None)
    if entry is None or entry_node is None:
        _cancel(job_id, run, None)
        return {"status": "cancelled"}
    if claimed.trigger_kind == "schedule" and (
        not channel.active or entry_node.get("type") != "trigger.scheduled"
    ):
        _cancel(job_id, run, entry)
        return {"status": "cancelled"}
    run.graph = graph
    run.version = version
    run.trigger_node_id = entry
    started = utc_now()
    actor = _actor(claimed)
    context = expression_context(channel, run, started, actor, claimed.trigger_kind)
    run.context = context
    store.update_run(run)
    elapsed = 0.0
    if claimed.started_at is not None:
        elapsed = max(
            0.0,
            (started - ensure_aware_utc(claimed.started_at)).total_seconds(),
        )
    timeout = (graph.get("settings") or {}).get("run_timeout_sec")
    try:
        outcome = execute_channel_run(
            graph=graph,
            entry_node_id=entry,
            entry_node=entry_node,
            run=run,
            context=context,
            actor=actor,
            started_at=format_instant(started),
            job=claimed,
            timeout_sec=timeout,
            started=time.monotonic() - elapsed,
        )
    except SandboxFailed as exc:
        mark_failed(job_id, error_code="CHANNEL_SANDBOX_FAILED", error_summary=str(exc))
        return {"status": "failed"}
    run.outcome = outcome.outcome
    run.failed_node_id = outcome.failed_node_id
    run.stopped_node_id = outcome.stopped_node_id
    run.skipped_node_ids = list(outcome.skipped_node_ids)
    get_run_store().update_run(run)
    if outcome.stopped_node_id:
        append_job_log(
            job_id,
            level="warning",
            message=f"stopped at node {outcome.stopped_node_id}",
        )
    if outcome.status == "succeeded":
        mark_succeeded(
            job_id,
            result={
                "schema": "channel_run.v1",
                "channel_id": run.channel_id,
                "version": run.version,
                "outcome": outcome.outcome,
            },
        )
        return {"status": "succeeded"}
    if outcome.status == "cancelled":
        mark_cancelled(job_id)
        return {"status": "cancelled"}
    mark_failed(
        job_id,
        error_code=outcome.error_code or "CHANNEL_NODE_FAILED",
        error_summary=outcome.error_message or "Channel run failed",
    )
    return {"status": "failed"}


def _cancel(job_id: str, run: Any, node_id: str | None) -> None:
    if node_id:
        run.stopped_node_id = node_id
        get_run_store().update_run(run)
        append_job_log(job_id, level="warning", message=f"stopped at node {node_id}")
    mark_cancelled(job_id)


def _resolve_graph(run: Any) -> tuple[dict[str, Any] | None, int | None]:
    if run.target == "draft":
        return run.graph, None
    versions, _total = get_channel_store().list_versions(run.channel_id, limit=1, offset=0)
    if not versions:
        return None, None
    latest = versions[0]
    return latest.graph, latest.number


def _actor(job: Any) -> dict[str, str]:
    if job.trigger_kind == "schedule":
        return {"id": "usr_system", "name": "System"}
    ref = job.trigger_ref or "usr_system"
    user = get_user_store().get_by_id(ref) if job.trigger_ref else None
    return {"id": ref, "name": user.display_name if user is not None else ref}
