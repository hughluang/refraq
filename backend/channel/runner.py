"""Claim a channel_run Job and execute its graph."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.admin.user_store import ensure_system_user, get_user_store
from backend.admin.system_parameters.registry import list_registered_specs
from backend.admin.system_parameters.resolver import resolve_int, resolve_str
from backend.admin.system_parameters.spec import IntConstraint
from backend.channel.engine import NodeResult, execute
from backend.channel.executors import EXECUTORS
from backend.channel.run_store import (
    get_run_store,
    output_size,
)
from backend.channel.sandbox import SandboxFailed, SandboxSession
from backend.channel.store import get_channel_store
from backend.core.time import utc_now
from backend.jobs.store import (
    claim_queued,
    get_job_store,
    mark_cancelled,
    mark_failed,
    mark_succeeded,
)

__all__ = ["run_channel_job"]


class _Hooks:
    def __init__(
        self,
        *,
        job_id: str,
        sandbox: SandboxSession,
        actor: dict[str, str],
        started_at: str,
        user: Any,
    ) -> None:
        self.job_id = job_id
        self.sandbox = sandbox
        self.actor = actor
        self.started_at = started_at
        self.user = user

    def cancelled(self) -> bool:
        record = get_job_store().get(self.job_id)
        return record is not None and record.status == "cancelled"

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


def run_channel_job(job_id: str) -> dict[str, str]:
    claimed = claim_queued(job_id)
    if claimed is None:
        record = get_job_store().get(job_id)
        return {"status": record.status if record else "missing"}
    payload = claimed.input or {}
    store = get_run_store()
    run = store.get_run(job_id)
    if run is None:
        mark_failed(job_id, error_code="CHANNEL_NODE_FAILED", error_summary="Run record is missing")
        return {"status": "failed"}
    graph, version = _resolve_graph(run)
    if graph is None:
        mark_cancelled(job_id)
        return {"status": "cancelled"}
    entry = str(payload.get("trigger_node_id") or run.trigger_node_id)
    if not any(node["id"] == entry and node["type"] == "trigger.manual" for node in graph["nodes"]):
        mark_cancelled(job_id)
        return {"status": "cancelled"}
    run.graph = graph
    run.version = version
    store.update_run(run)
    channel = get_channel_store().get(run.channel_id)
    started = utc_now()
    actor = {
        "id": claimed.trigger_ref or "usr_system",
        "name": claimed.trigger_ref or "System",
    }
    user = ensure_system_user(get_user_store())
    try:
        with SandboxSession() as sandbox:
            sandbox.set_context(
                channel=_channel_ctx(channel, run),
                run=_run_ctx(run, started, actor),
                platform=_platform_ctx(started),
            )
            hooks = _Hooks(
                job_id=job_id,
                sandbox=sandbox,
                actor=actor,
                started_at=started.isoformat().replace("+00:00", "Z"),
                user=user,
            )
            timeout = (graph.get("settings") or {}).get("run_timeout_sec")
            outcome = execute(
                graph,
                entry,
                EXECUTORS,
                hooks,
                timeout_sec=timeout,
            )
    except SandboxFailed as exc:
        mark_failed(job_id, error_code="CHANNEL_SANDBOX_FAILED", error_summary=str(exc))
        return {"status": "failed"}
    run.outcome = outcome.outcome
    run.failed_node_id = outcome.failed_node_id
    run.skipped_node_ids = list(outcome.skipped_node_ids)
    store.update_run(run)
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


def _resolve_graph(run: Any) -> tuple[dict[str, Any] | None, int | None]:
    if run.target == "draft":
        return run.graph, None
    versions, _total = get_channel_store().list_versions(run.channel_id, limit=1, offset=0)
    if not versions:
        return None, None
    latest = versions[0]
    return latest.graph, latest.number


def _channel_ctx(channel: Any, run: Any) -> dict[str, Any]:
    settings = (run.graph or {}).get("settings") or {}
    if channel is None:
        return {"id": run.channel_id, "settings": settings}
    return {
        "id": channel.id,
        "name": channel.name,
        "description": channel.description,
        "active": channel.active,
        "settings": settings,
    }


def _run_ctx(run: Any, started: datetime, actor: dict[str, str]) -> dict[str, Any]:
    return {
        "id": run.job_id,
        "target": run.target,
        "version": run.version,
        "draft_revision": run.draft_revision,
        "trigger_kind": "user",
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "triggered_by": actor,
    }


def _platform_ctx(started: datetime) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    try:
        for spec in list_registered_specs():
            if isinstance(spec.constraint, IntConstraint):
                parameters[spec.key] = resolve_int(spec.key).value
            else:
                parameters[spec.key] = resolve_str(spec.key).value
    except Exception:  # noqa: BLE001
        parameters = {}
    return {
        "site_name": "",
        "schedule_timezone": parameters.get("schedule_timezone", "UTC"),
        "now": started.isoformat().replace("+00:00", "Z"),
        "parameters": parameters,
        "variables": {},
    }
