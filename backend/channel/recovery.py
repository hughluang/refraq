"""After a channel run reaches a terminal status: streak, retry, error workflow."""

from __future__ import annotations

from typing import Any

from backend.admin.user_store import get_user_store
from backend.channel.channel_run import (
    SYSTEM_TRIGGER_KINDS,
    dispatch,
    mint_followup_run,
    trigger_node_id,
)
from backend.channel.checkpoints import advance_from_run
from backend.channel.dataset_registry import drop_datasets_for_jobs
from backend.channel.run_store import get_run_store
from backend.channel.store import get_channel_store
from backend.core.time import format_instant, utc_now
from backend.jobs.store import JobRecord, append_job_log, get_job_store

__all__ = [
    "PERSISTENT_FAILURE_STREAK",
    "settle_failure",
    "settle_success",
]

PERSISTENT_FAILURE_STREAK = 3
_SYSTEM = {"id": "usr_system", "name": "System"}


def settle_success(run: Any) -> None:
    """A completed run advances checkpoints. A published success ends the failure episode.

    Advance runs for a draft too: the run's writes and deliveries already happened.
    A run that stopped at one node does not advance. The checkpoint module applies
    that rule. Discarding, when a keeping setting asks for it, happens only after
    that advance has returned.
    """
    advance_from_run(run)
    if run.target == "published":
        _write_streak(run.channel_id, 0)
    _discard_job(getattr(run, "job_id", None))


def settle_failure(
    *,
    job: JobRecord,
    run: Any,
    error_code: str,
    error_message: str,
    node_id: str | None,
) -> None:
    """Remint a pinned retry, or close the episode and maybe start the error workflow.

    An error-workflow run never remints and never starts another workflow.
    Its own published failure still counts toward that channel's streak.
    """
    if job.trigger_kind == "error":
        if run.target == "published":
            _bump_streak(run.channel_id)
        _discard_job(job.id)
        return
    if (
        run.target == "published"
        and run.version is not None
        and _ancestors(job) < _limit(run)
    ):
        _queue_retry(job, run)
        return
    if run.target == "published":
        _bump_streak(run.channel_id)
    _start_error_workflow(job, run, error_code, error_message, node_id)
    _release_failed_chain(job)


def _release_failed_chain(job: JobRecord) -> None:
    """Drop failed Jobs in this retry chain whose own setting says not to keep.

    Called only after no further retry will be minted and the error workflow
    has returned. A succeeded ancestor is left in place. The error-workflow
    Job is not in this chain.
    """
    doomed: list[str] = []
    current: JobRecord | None = job
    seen: set[str] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if current.status == "failed" and _discards(current):
            doomed.append(current.id)
        parent_id = (current.input or {}).get("retry_of_job_id")
        if not isinstance(parent_id, str) or not parent_id:
            break
        parent = get_job_store().get(parent_id)
        if parent is None or parent.status != "failed":
            break
        current = parent
    if doomed:
        _discard_jobs(doomed)


def _discard_job(job_id: Any) -> None:
    if not isinstance(job_id, str) or not job_id:
        return
    job = get_job_store().get(job_id)
    if job is None or not _discards(job):
        return
    _discard_jobs([job.id])


def _discard_jobs(job_ids: list[str]) -> None:
    drop_datasets_for_jobs(job_ids)
    runs = get_run_store()
    jobs = get_job_store()
    for job_id in job_ids:
        runs.delete_run(job_id)
        jobs.delete(job_id)


def _discards(job: JobRecord) -> bool:
    """Whether this terminal Job's keeping setting says to drop it.

    Cancelled runs are always kept. An on-demand run that is not a rerun
    follows ``keep_test_runs`` for either outcome. Anything else follows the
    outcome setting. A missing key means keep.
    """
    if job.status == "cancelled":
        return False
    run = get_run_store().get_run(job.id)
    if run is None or not isinstance(run.graph, dict):
        return False
    settings = run.graph.get("settings")
    if _is_on_demand_test(job):
        return not _keep(settings, "keep_test_runs")
    if job.status == "succeeded":
        return not _keep(settings, "keep_succeeded_runs")
    if job.status == "failed":
        return not _keep(settings, "keep_failed_runs")
    return False


def _is_on_demand_test(job: JobRecord) -> bool:
    if job.trigger_kind != "user":
        return False
    return (job.input or {}).get("pin_version") is not True


def _keep(settings: Any, key: str) -> bool:
    if not isinstance(settings, dict) or key not in settings:
        return True
    return settings[key] is not False


def _limit(run: Any) -> int:
    settings = (run.graph or {}).get("settings") or {}
    raw = settings.get("run_retry_limit")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return max(0, min(raw, 10))


def _ancestors(job: JobRecord) -> int:
    count = 0
    seen: set[str] = set()
    current = job
    while True:
        parent_id = (current.input or {}).get("retry_of_job_id")
        if not isinstance(parent_id, str) or not parent_id or parent_id in seen:
            return count
        seen.add(parent_id)
        parent = get_job_store().get(parent_id)
        if parent is None:
            return count + 1
        count += 1
        current = parent


def _queue_retry(job: JobRecord, run: Any) -> None:
    channel = get_channel_store().get(run.channel_id)
    name = channel.name if channel is not None else run.channel_id
    try:
        queued, _record = mint_followup_run(
            channel_id=run.channel_id,
            channel_name=name,
            trigger_kind="retry",
            trigger_ref=job.id,
            trigger_node=run.trigger_node_id or "",
            version=run.version,
            job_input={
                "channel_id": run.channel_id,
                "target": "published",
                "ignore_checkpoints": False,
                "pin_version": True,
                "version": run.version,
                "retry_of_job_id": job.id,
            },
        )
        dispatch(queued.id)
    except Exception as exc:
        append_job_log(
            job.id,
            level="error",
            message=f"Retry run was not queued: {exc}",
        )


def _start_error_workflow(
    job: JobRecord,
    run: Any,
    error_code: str,
    error_message: str,
    node_id: str | None,
) -> None:
    settings = (run.graph or {}).get("settings") or {}
    target_id = settings.get("error_channel_id")
    if not isinstance(target_id, str) or not target_id:
        return
    reason = _error_target_problem(target_id)
    if reason is not None:
        append_job_log(job.id, level="warning", message=reason)
        return
    target = get_channel_store().get(target_id)
    versions, _total = get_channel_store().list_versions(target_id, limit=1, offset=0)
    graph = versions[0].graph
    node = trigger_node_id(graph) or ""
    source = get_channel_store().get(run.channel_id)
    try:
        queued, _record = mint_followup_run(
            channel_id=target_id,
            channel_name=target.name if target is not None else target_id,
            trigger_kind="error",
            trigger_ref=job.id,
            trigger_node=node,
            version=None,
            job_input={
                "channel_id": target_id,
                "target": "published",
                "ignore_checkpoints": False,
                "error_source": {
                    "channel_id": run.channel_id,
                    "channel_name": source.name
                    if source is not None
                    else run.channel_id,
                    "job_id": job.id,
                    "version": run.version,
                    "attempt": _ancestors(job) + 1,
                    "error": {
                        "code": error_code,
                        "message": error_message,
                        "node_id": node_id,
                    },
                    "triggered_by": _triggered_by(job),
                    "triggered_at": format_instant(utc_now()),
                },
            },
        )
        dispatch(queued.id)
    except Exception as exc:
        append_job_log(
            job.id,
            level="error",
            message=f"Error workflow was not queued: {exc}",
        )


def _error_target_problem(channel_id: str) -> str | None:
    channel = get_channel_store().get(channel_id)
    if channel is None:
        return "Error workflow was not started: channel was not found"
    if not channel.active:
        return "Error workflow was not started: channel is inactive"
    versions, _total = get_channel_store().list_versions(channel_id, limit=1, offset=0)
    if not versions:
        return "Error workflow was not started: channel has no published version"
    node_id = trigger_node_id(versions[0].graph)
    nodes = versions[0].graph.get("nodes") or []
    node = next((item for item in nodes if item.get("id") == node_id), None)
    if node is None or node.get("type") != "trigger.error":
        return "Error workflow was not started: published trigger is not trigger.error"
    return None


def _triggered_by(job: JobRecord) -> dict[str, str]:
    if job.trigger_kind in SYSTEM_TRIGGER_KINDS or not job.trigger_ref:
        return dict(_SYSTEM)
    user = get_user_store().get_by_id(job.trigger_ref)
    name = user.display_name if user is not None else job.trigger_ref
    return {"id": job.trigger_ref, "name": name}


def _bump_streak(channel_id: str) -> None:
    record = get_channel_store().get(channel_id)
    if record is None:
        return
    _write_streak(channel_id, record.failure_streak + 1)


def _write_streak(channel_id: str, value: int) -> None:
    store = get_channel_store()
    record = store.get(channel_id)
    if record is None:
        return
    if value == 0 and record.failure_streak == 0:
        return
    record.failure_streak = value
    record.updated_at = utc_now()
    store.save(record)
