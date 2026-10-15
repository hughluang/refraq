"""Claim a channel_run Job and execute its graph."""

from __future__ import annotations

import time
from typing import Any

from backend.admin.user_store import ensure_system_user, get_user_store
from backend.channel.context import channel_context, platform_context, run_context
from backend.channel.engine import NodeResult, execute
from backend.channel.executors import EXECUTORS
from backend.channel.nodes import list_node_types, loop_ports
from backend.channel.run_store import get_run_store, note_killed_run, output_size
from backend.channel.sandbox import SandboxFailed, SandboxSession
from backend.channel.schedules import schedule_key_for
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
from backend.worker.schedules import get_schedule_store

__all__ = ["note_killed_run", "run_channel_job"]

class _Hooks:
    def __init__(
        self,
        *,
        job_id: str,
        sandbox: SandboxSession,
        actor: dict[str, str],
        started_at: str,
        user: Any,
        schedule: dict[str, Any],
        target: str,
        channel_id: str,
        run_version: int | None,
    ) -> None:
        self.job_id = job_id
        self.sandbox = sandbox
        self.actor = actor
        self.started_at = started_at
        self.user = user
        self.schedule = schedule
        self._target = target
        self._channel_id = channel_id
        self._run_version = run_version

    def cancelled(self) -> bool:
        record = get_job_store().get(self.job_id)
        return record is not None and record.status == "cancelled"

    def superseded(self) -> bool:
        if self._target != "published" or self._run_version is None:
            return False
        versions, _total = get_channel_store().list_versions(
            self._channel_id, limit=1, offset=0
        )
        if not versions:
            return False
        return versions[0].number > self._run_version

    def evaluate(self, expression: str) -> Any:
        return self.sandbox.evaluate(expression)

    def on_start(self, node: dict[str, Any]) -> int:
        record = get_run_store().start_execution(self.job_id, str(node["id"]))
        return record.seq

    def on_finish(self, seq: int, node: dict[str, Any], result: NodeResult) -> None:
        store = get_run_store()
        record = store.get_execution(self.job_id, seq)
        if record is None:
            return
        record.status = result.status
        record.finished_at = utc_now()
        record.output = result.output
        record.output_bytes = output_size(result.output)
        record.error_code = result.error_code
        record.error_message = result.error_message
        record.error_detail = result.error_detail
        store.finish_execution(record)

    def on_output(self, node: dict[str, Any], output: Any) -> None:
        self.sandbox.put_output(
            ref=str(node.get("ref") or node["id"]),
            name=str(node.get("name") or ""),
            output=output,
        )

    def drop_outputs(self, refs: list[str]) -> None:
        self.sandbox.drop_outputs(refs)


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
    entry = _entry_id(graph)
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
    run.context = {
        "channel": channel_context(channel, run),
        "run": run_context(run, started, actor, claimed.trigger_kind),
        "platform": platform_context(started),
    }
    store.update_run(run)
    user = ensure_system_user(get_user_store())
    elapsed = 0.0
    if claimed.started_at is not None:
        elapsed = max(
            0.0,
            (started - ensure_aware_utc(claimed.started_at)).total_seconds(),
        )
    try:
        with SandboxSession() as sandbox:
            sandbox.set_context(**run.context)
            hooks = _Hooks(
                job_id=job_id,
                sandbox=sandbox,
                actor=actor,
                started_at=started.isoformat().replace("+00:00", "Z"),
                user=user,
                schedule=_schedule_ctx(claimed, channel.id, entry_node),
                target=run.target,
                channel_id=run.channel_id,
                run_version=version,
            )
            timeout = (graph.get("settings") or {}).get("run_timeout_sec")
            outcome = execute(
                graph,
                entry,
                EXECUTORS,
                hooks,
                timeout_sec=timeout,
                started=time.monotonic() - elapsed,
                stop_at_node_id=run.stop_at_node_id,
                loop_ports=loop_ports(),
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


def _entry_id(graph: dict[str, Any]) -> str | None:
    entry_types = {item.type_id for item in list_node_types() if item.entry}
    entries = [node for node in graph.get("nodes") or [] if node.get("type") in entry_types]
    if len(entries) != 1:
        return None
    return str(entries[0]["id"])


def _actor(job: Any) -> dict[str, str]:
    if job.trigger_kind == "schedule":
        return {"id": "usr_system", "name": "System"}
    ref = job.trigger_ref or "usr_system"
    user = get_user_store().get_by_id(ref) if job.trigger_ref else None
    return {"id": ref, "name": user.display_name if user is not None else ref}


def _schedule_ctx(job: Any, channel_id: str, node: dict[str, Any]) -> dict[str, Any]:
    row = get_schedule_store().get_by_key(schedule_key_for(channel_id))
    node_name = str(node.get("name") or "")
    if job.trigger_kind == "schedule":
        when = job.scheduled_for or job.created_at
        return {
            "schedule_id": job.trigger_ref,
            "name": row.name if row is not None else node_name,
            "scheduled_for": format_instant(when) if when is not None else "",
        }
    when = job.created_at
    return {
        "schedule_id": row.id if row is not None else None,
        "name": row.name if row is not None else node_name,
        "scheduled_for": format_instant(when) if when is not None else "",
    }


