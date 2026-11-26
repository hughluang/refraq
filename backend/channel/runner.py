"""Claim a channel_run Job and execute its graph."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import time
from collections.abc import Mapping
from typing import Any

from backend.admin.user_store import get_user_store
from backend.channel import channel_run
from backend.channel.dataset_registry import seal_dataset_expiry
from backend.channel.locks import ChannelRunLock, try_acquire_channel_run_lock
from backend.channel.nodes.spec import NodeResult
from backend.channel import recovery
from backend.channel.run_store import get_run_store
from backend.channel.sandbox import SandboxFailed
from backend.channel.store import get_channel_store
from backend.channel.subchannel import (
    MAX_SUBCHANNEL_CALL_DEPTH,
    SubchannelParam,
    parse_subchannel_params,
    validate_and_resolve_subchannel_input,
)
from backend.core.time import ensure_aware_utc, format_instant, utc_now
from backend.jobs.store import (
    TERMINAL,
    append_job_log,
    claim_for_execution,
    claim_queued,
    current_worker_id,
    get_job_store,
    mark_cancelled,
    mark_failed,
    mark_succeeded,
)

__all__ = ["run_channel_job"]


@dataclass(frozen=True, slots=True)
class _PreparedSubchannel:
    target_channel_id: str
    channel: Any
    graph: dict[str, Any]
    version_number: int
    trigger_id: str
    trigger_node: dict[str, Any]
    params: list[SubchannelParam]
def run_channel_job(job_id: str) -> dict[str, str]:
    claimed = claim_for_execution(job_id, claimed_by=current_worker_id())
    if claimed is None:
        record = get_job_store().get(job_id)
        return {"status": record.status if record else "missing"}
    store = get_run_store()
    run = store.get_run(job_id)
    if run is None:
        mark_cancelled(job_id)
        seal_dataset_expiry(job_id)
        return {"status": "cancelled"}
    channel = get_channel_store().get(run.channel_id)
    if channel is None:
        _cancel(job_id, run, run.trigger_node_id or None)
        return {"status": "cancelled"}
    graph, version = _resolve_graph(run, claimed)
    if graph is None:
        _cancel(job_id, run, None)
        return {"status": "cancelled"}
    trigger = channel_run.trigger_node_id(graph)
    trigger_node = next((node for node in graph["nodes"] if node["id"] == trigger), None)
    if trigger is None or trigger_node is None:
        _cancel(job_id, run, None)
        return {"status": "cancelled"}
    if claimed.trigger_kind == "schedule" and (
        not channel.active or trigger_node.get("type") != "trigger.scheduled"
    ):
        _cancel(job_id, run, trigger)
        return {"status": "cancelled"}
    if claimed.trigger_kind == "error" and (
        not channel.active or trigger_node.get("type") != "trigger.error"
    ):
        _note_error_source(claimed, "Error workflow was not started: channel cannot run")
        _cancel(job_id, run, trigger)
        return {"status": "cancelled"}
    run.graph = graph
    run.version = version
    run.trigger_node_id = trigger
    run_lock: ChannelRunLock | None = None
    if (graph.get("settings") or {}).get("concurrency") == "forbid":
        run_lock = try_acquire_channel_run_lock(run.channel_id)
        if run_lock is None:
            run.outcome = "skipped"
            store.update_run(run)
            append_job_log(
                job_id,
                level="info",
                message="skipped overlapping channel run (concurrency=forbid)",
            )
            result = {
                "schema": "channel_run.v1",
                "channel_id": run.channel_id,
                "version": run.version,
                "outcome": "skipped",
            }
            done = mark_succeeded(job_id, result=result)
            if done is not None and done.status == "succeeded":
                recovery.settle_success(run)
            seal_dataset_expiry(job_id)
            return {"status": done.status if done is not None else "missing"}
    try:
        started = utc_now()
        actor = _actor(claimed)
        context = channel_run.expression_context(
            channel, run, started, actor, claimed.trigger_kind
        )
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
            outcome = channel_run.execute_channel_run(
                graph=graph,
                trigger_node_id=trigger,
                trigger_node=trigger_node,
                run=run,
                context=context,
                actor=actor,
                started_at=format_instant(started),
                job=claimed,
                timeout_sec=timeout,
                started=time.monotonic() - elapsed,
                pinned=bool((claimed.input or {}).get("pin_version")),
                claimed_by=claimed.claimed_by,
                subchannel_preparer=_prepare_subchannel,
                subchannel_invoker=_run_subchannel,
            )
        except SandboxFailed as exc:
            code, message = "CHANNEL_SANDBOX_FAILED", str(exc)
            failed = mark_failed(job_id, error_code=code, error_summary=message)
            if failed is not None and failed.status == "failed":
                recovery.settle_failure(
                    job=failed,
                    run=run,
                    error_code=code,
                    error_message=message,
                    node_id=None,
                )
            seal_dataset_expiry(job_id)
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
            result = {
                "schema": "channel_run.v1",
                "channel_id": run.channel_id,
                "version": run.version,
                "outcome": outcome.outcome,
            }
            done = mark_succeeded(job_id, result=result)
            if done is not None and done.status == "succeeded":
                recovery.settle_success(run)
            seal_dataset_expiry(job_id)
            return {"status": done.status if done is not None else "missing"}
        if outcome.status == "cancelled":
            mark_cancelled(job_id)
            seal_dataset_expiry(job_id)
            return {"status": "cancelled"}
        code = outcome.error_code or "CHANNEL_NODE_FAILED"
        message = outcome.error_message or "Channel run failed"
        failed = mark_failed(job_id, error_code=code, error_summary=message)
        if failed is not None and failed.status == "failed":
            recovery.settle_failure(
                job=failed,
                run=run,
                error_code=code,
                error_message=message,
                node_id=outcome.failed_node_id or outcome.stopped_node_id,
            )
        seal_dataset_expiry(job_id)
        return {"status": "failed"}
    finally:
        if run_lock is not None:
            run_lock.release()


def _cancel(job_id: str, run: Any, node_id: str | None) -> None:
    if node_id:
        run.stopped_node_id = node_id
        get_run_store().update_run(run)
        append_job_log(job_id, level="warning", message=f"stopped at node {node_id}")
    mark_cancelled(job_id)
    seal_dataset_expiry(job_id)


def _resolve_graph(run: Any, job: Any) -> tuple[dict[str, Any] | None, int | None]:
    if run.target == "draft":
        return run.graph, None
    payload = job.input or {}
    if payload.get("pin_version"):
        number = payload.get("version")
        if isinstance(number, bool) or not isinstance(number, int):
            return None, None
        pinned = get_channel_store().get_version(run.channel_id, number)
        if pinned is None:
            return None, None
        return pinned.graph, pinned.number
    versions, _total = get_channel_store().list_versions(run.channel_id, limit=1, offset=0)
    if not versions:
        return None, None
    latest = versions[0]
    return latest.graph, latest.number


def _note_error_source(job: Any, message: str) -> None:
    source_id = job.trigger_ref
    if isinstance(source_id, str) and source_id:
        append_job_log(source_id, level="warning", message=message)


def _actor(job: Any) -> dict[str, str]:
    if job.trigger_kind in channel_run.SYSTEM_TRIGGER_KINDS:
        return {"id": "usr_system", "name": "System"}
    ref = job.trigger_ref or "usr_system"
    user = get_user_store().get_by_id(ref) if job.trigger_ref else None
    return {"id": ref, "name": user.display_name if user is not None else ref}


def _prepare_subchannel(
    *,
    parent_hooks: Any,
    target_channel_id: str,
) -> tuple[_PreparedSubchannel | None, NodeResult | None]:
    if target_channel_id in parent_hooks.active_channel_ids:
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_SUBCHANNEL_CYCLE",
            error_message=f"Sub-channel call forms a runtime cycle: {target_channel_id}",
        )
    if len(parent_hooks.active_channel_ids) > MAX_SUBCHANNEL_CALL_DEPTH:
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_SUBCHANNEL_DEPTH_EXCEEDED",
            error_message=(
                f"Sub-channel call depth exceeded maximum ({MAX_SUBCHANNEL_CALL_DEPTH})"
            ),
        )
    store = get_channel_store()
    channel = store.get(target_channel_id)
    if channel is None:
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_SUBCHANNEL_UNAVAILABLE",
            error_message=f"Sub-channel was not found: {target_channel_id}",
        )
    if not channel.active:
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_SUBCHANNEL_INACTIVE",
            error_message=f"Sub-channel is inactive: {channel.name}",
        )
    if target_channel_id in parent_hooks.resolved_subchannel_versions:
        version_record = store.get_version(
            target_channel_id,
            parent_hooks.resolved_subchannel_versions[target_channel_id],
        )
    else:
        versions, _total = store.list_versions(target_channel_id, limit=1, offset=0)
        version_record = versions[0] if versions else None
    if version_record is None:
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_SUBCHANNEL_UNAVAILABLE",
            error_message=f"Sub-channel has no published version: {channel.name}",
        )
    graph = version_record.graph
    version_number = version_record.number
    trigger_id = channel_run.trigger_node_id(graph)
    trigger_node = next(
        (node for node in graph.get("nodes") or [] if node.get("id") == trigger_id),
        None,
    )
    if (
        trigger_id is None
        or trigger_node is None
        or trigger_node.get("type") != "trigger.subchannel"
    ):
        return None, NodeResult(
            status="failed",
            error_code="CHANNEL_SUBCHANNEL_UNAVAILABLE",
            error_message=(
                f"Sub-channel published trigger is not trigger.subchannel: {channel.name}"
            ),
        )
    parent_hooks.resolved_subchannel_versions[target_channel_id] = version_number
    params = parse_subchannel_params(
        trigger_node.get("config")
        if isinstance(trigger_node.get("config"), Mapping)
        else {}
    )
    return (
        _PreparedSubchannel(
            target_channel_id=target_channel_id,
            channel=channel,
            graph=graph,
            version_number=version_number,
            trigger_id=trigger_id,
            trigger_node=trigger_node,
            params=params,
        ),
        None,
    )


def _run_subchannel(
    *,
    parent_hooks: Any,
    prepared: _PreparedSubchannel,
    inputs: Mapping[str, Any],
    caller_node_id: str,
) -> NodeResult:
    target_channel_id = prepared.target_channel_id
    channel = prepared.channel
    graph = prepared.graph
    version_number = prepared.version_number
    trigger_id = prepared.trigger_id
    trigger_node = prepared.trigger_node
    params = prepared.params
    resolved_inputs, details = validate_and_resolve_subchannel_input(
        params,
        inputs,
        run_id=parent_hooks.run_id,
    )
    if resolved_inputs is None:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_SUBCHANNEL_INPUT_INVALID",
            error_message=details[0]["message"],
            error_detail={"details": details},
        )
    child_job, child_run = channel_run.mint_subchannel_run(
        channel_id=target_channel_id,
        channel_name=channel.name,
        version=version_number,
        trigger_node_id=trigger_id,
        ignore_checkpoints=parent_hooks.ignore_checkpoints,
        parent_job_id=parent_hooks.run_id,
        root_job_id=parent_hooks.root_job_id,
        caller_channel_id=parent_hooks.channel_id,
        caller_node_id=caller_node_id,
        subchannel_input=resolved_inputs,
    )
    claimed = claim_queued(
        child_job.id,
        claimed_by=parent_hooks.claimed_by,
    )
    if claimed is None:
        if parent_hooks.cancelled() or parent_hooks.superseded():
            return NodeResult(status="cancelled")
        return NodeResult(
            status="failed",
            error_code="CHANNEL_SUBCHANNEL_FAILED",
            error_message=f"Sub-channel '{channel.name}' was cancelled",
            error_detail={
                "channel_id": target_channel_id,
                "job_id": child_job.id,
                "version": version_number,
                "failed_node_id": None,
                "reason": "cancelled",
                "error_code": "CANCELLED",
                "error_message": "Sub-channel run was cancelled",
            },
        )
    run_store = get_run_store()
    child_run.graph = graph
    child_run.version = version_number
    child_run.trigger_node_id = trigger_id
    run_lock: ChannelRunLock | None = None
    if (graph.get("settings") or {}).get("concurrency") == "forbid":
        run_lock = try_acquire_channel_run_lock(target_channel_id)
        if run_lock is None:
            child_run.outcome = "skipped"
            run_store.update_run(child_run)
            append_job_log(
                child_job.id,
                level="info",
                message="skipped overlapping channel run (concurrency=forbid)",
            )
            done = mark_succeeded(
                child_job.id,
                result={
                    "schema": "channel_run.v1",
                    "channel_id": target_channel_id,
                    "version": version_number,
                    "outcome": "skipped",
                },
            )
            if done is not None and done.status == "succeeded":
                recovery.settle_success(child_run)
            return NodeResult(
                status="succeeded",
                output={
                    "job_id": child_job.id,
                    "channel_id": target_channel_id,
                    "version": version_number,
                    "outcome": "skipped",
                    "result": None,
                },
            )
    try:
        started_dt = utc_now()
        started_mono = time.monotonic()
        context = channel_run.expression_context(
            channel, child_run, started_dt, dict(parent_hooks.actor), "subchannel"
        )
        child_run.context = context
        run_store.update_run(child_run)
        child_timeout = (graph.get("settings") or {}).get("run_timeout_sec")
        candidates: list[float] = []
        if child_timeout is not None:
            candidates.append(float(child_timeout))
        if parent_hooks.deadline is not None:
            candidates.append(max(0.0, parent_hooks.deadline - started_mono))
        effective_timeout: float | None = min(candidates) if candidates else None
        try:
            outcome = channel_run.execute_subchannel_graph(
                parent_hooks=parent_hooks,
                graph=graph,
                trigger_node_id=trigger_id,
                trigger_node=trigger_node,
                run=child_run,
                context=context,
                started_at=format_instant(started_dt),
                job=claimed,
                timeout_sec=effective_timeout,
                started=started_mono,
            )
        except SandboxFailed as exc:
            code, message = "CHANNEL_SANDBOX_FAILED", str(exc)
            failed = mark_failed(child_job.id, error_code=code, error_summary=message)
            if failed is not None and failed.status == "failed":
                recovery.settle_failure(
                    job=failed,
                    run=child_run,
                    error_code=code,
                    error_message=message,
                    node_id=None,
                )
            return NodeResult(
                status="failed",
                error_code="CHANNEL_SUBCHANNEL_FAILED",
                error_message=f"Sub-channel '{channel.name}' failed: {message}",
                error_detail={
                    "channel_id": target_channel_id,
                    "job_id": child_job.id,
                    "version": version_number,
                    "failed_node_id": None,
                    "error_code": code,
                    "error_message": message,
                },
            )
        fresh_run = run_store.get_run(child_job.id)
        assert fresh_run is not None
        return_val = copy.deepcopy(fresh_run.return_value)
        child_run.return_value = return_val
        child_run.outcome = outcome.outcome
        child_run.failed_node_id = outcome.failed_node_id
        child_run.stopped_node_id = outcome.stopped_node_id
        child_run.skipped_node_ids = list(outcome.skipped_node_ids)
        run_store.update_run(child_run)
        if outcome.stopped_node_id:
            append_job_log(
                child_job.id,
                level="warning",
                message=f"stopped at node {outcome.stopped_node_id}",
            )
        if outcome.status == "succeeded":
            done = mark_succeeded(
                child_job.id,
                result={
                    "schema": "channel_run.v1",
                    "channel_id": target_channel_id,
                    "version": version_number,
                    "outcome": outcome.outcome,
                },
            )
            if done is not None and done.status == "succeeded":
                recovery.settle_success(child_run)
            return NodeResult(
                status="succeeded",
                output={
                    "job_id": child_job.id,
                    "channel_id": target_channel_id,
                    "version": version_number,
                    "outcome": outcome.outcome,
                    "result": return_val,
                },
            )
        if outcome.status == "cancelled":
            mark_cancelled(child_job.id)
            if parent_hooks.cancelled() or parent_hooks.superseded():
                return NodeResult(status="cancelled")
            return NodeResult(
                status="failed",
                error_code="CHANNEL_SUBCHANNEL_FAILED",
                error_message=f"Sub-channel '{channel.name}' was cancelled",
                error_detail={
                    "channel_id": target_channel_id,
                    "job_id": child_job.id,
                    "version": version_number,
                    "failed_node_id": outcome.stopped_node_id,
                    "reason": "cancelled",
                    "error_code": "CANCELLED",
                    "error_message": "Sub-channel run was cancelled",
                },
            )
        code = outcome.error_code or "CHANNEL_NODE_FAILED"
        message = outcome.error_message or "Channel run failed"
        failed_node = outcome.failed_node_id or outcome.stopped_node_id
        failed = mark_failed(child_job.id, error_code=code, error_summary=message)
        if failed is not None and failed.status == "failed":
            recovery.settle_failure(
                job=failed,
                run=child_run,
                error_code=code,
                error_message=message,
                node_id=failed_node,
            )
        return NodeResult(
            status="failed",
            error_code="CHANNEL_SUBCHANNEL_FAILED",
            error_message=f"Sub-channel '{channel.name}' failed: {message}",
            error_detail={
                "channel_id": target_channel_id,
                "job_id": child_job.id,
                "version": version_number,
                "failed_node_id": failed_node,
                "error_code": code,
                "error_message": message,
            },
        )
    finally:
        if run_lock is not None:
            run_lock.release()
