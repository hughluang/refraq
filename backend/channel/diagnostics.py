"""Public diagnostics and stored payload policy for mirror-bearing Channel Runs."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from backend.channel.mirror_reads import MirrorDataForbidden, mirror_graph, require_run_data_access
from backend.channel.run_store import get_run_store
from backend.jobs.store import JobRecord, get_job_store

if TYPE_CHECKING:
    from backend.channel.nodes.spec import NodeResult


_MESSAGES = {
    "AUTH_FORBIDDEN": "Mirror data access is forbidden",
    "CHANNEL_CHANGE_LOG_GROUPING_UNSAFE": "Change history cannot be grouped safely",
    "CHANNEL_CHECKPOINT_INVALID": "The retained history position is invalid",
    "CHANNEL_DATASET_UNAVAILABLE": "The dataset is unavailable",
    "CHANNEL_ITEM_LIMIT_EXCEEDED": "The item limit was exceeded",
    "CHANNEL_LOOP_BODY_STOPPED": "The loop body stopped",
    "CHANNEL_NODE_CONFIG_INVALID": "The node configuration is invalid",
    "CHANNEL_NODE_FAILED": "Channel node failed",
    "CHANNEL_NODE_SKIPPED": "Channel node skipped",
    "CHANNEL_OUTPUT_SCHEMA_MISMATCH": "The output does not match the node schema",
    "CHANNEL_RUN_TIMEOUT": "The run exceeded its time limit",
    "CHANNEL_SANDBOX_FAILED": "The Channel sandbox failed",
    "CHANNEL_SQL_NOT_ONE_STATEMENT": "Exactly one SQL statement is required",
    "CHANNEL_TRIGGER_INVALID": "The Channel trigger is invalid",
    "CHANNEL_UNTIL_MAX_ITERATIONS": "The loop reached its iteration limit",
    "CHANNEL_VALUE_TYPE_MISMATCH": "The value does not match the expected type",
    "CHANNEL_VARIABLE_TOO_LARGE": "The Channel variable exceeds its size limit",
    "CHANNEL_WRITE_INCOMPATIBLE": "The write target is incompatible",
    "JOB_EXECUTION_FAILED": "Channel execution failed",
    "JOB_WORKER_EXITED": "The Channel worker exited",
    "MIRROR_HISTORY_INVALID": "The retained mirror history is invalid",
    "MIRROR_READ_UNAVAILABLE": "Mirror data is unavailable",
    "MIRROR_SETTLEMENT_FAILED": "Mirror checkpoint settlement failed",
}

DIAGNOSTICS_VERSION = 1
ERROR_SOURCE_VERIFIED = "error_source_verified"


def public_error(code: Any, *, fallback: str = "CHANNEL_NODE_FAILED") -> tuple[str, str]:
    public_code = code if isinstance(code, str) and code in _MESSAGES else fallback
    return public_code, _MESSAGES[public_code]


def safe_result(result: NodeResult) -> NodeResult:
    if result.status in {"failed", "skipped"}:
        fallback = "CHANNEL_NODE_SKIPPED" if result.status == "skipped" else "CHANNEL_NODE_FAILED"
        code, message = public_error(result.error_code, fallback=fallback)
        return replace(result, output=None, error_code=code, error_message=message, error_detail=None)
    return replace(result, error_code=None, error_message=None, error_detail=None)


def protected_run(run: Any) -> bool:
    return (getattr(run, "mirror_state", None) is not None
            or getattr(run, "mirror_execution_user_id", None) is not None
            or mirror_graph(getattr(run, "graph", None)))


def run_sources(run: Any) -> list[str] | None:
    if not protected_run(run):
        return [] if isinstance(getattr(run, "graph", None), dict) else None
    state = getattr(run, "mirror_state", None)
    sources = state.get("source_ids") if isinstance(state, dict) else None
    if not isinstance(sources, list) or not sources or any(
        not isinstance(source, str) or not source for source in sources
    ):
        return None
    return sorted(set(sources))


def has_error_lineage(job: JobRecord) -> bool:
    return job.trigger_kind == "error" or "error_source" in job.input


def error_lineage_verified(job: JobRecord, run: Any) -> bool:
    source = job.input.get("error_source")
    if job.input.get(ERROR_SOURCE_VERIFIED) is True:
        return run is not None and isinstance(source, dict)
    if not has_error_lineage(job):
        return True
    if (protected_run(run) or job.trigger_kind != "error" or not job.trigger_ref
            or not isinstance(source, dict) or source.get("job_id") != job.trigger_ref):
        return False
    parent_job = get_job_store().get(job.trigger_ref)
    parent_run = get_run_store().get_run(job.trigger_ref)
    return (parent_job is not None and parent_job.kind == "channel_run"
            and not has_error_lineage(parent_job) and run_sources(parent_run) == []
            and source.get("channel_id") == parent_run.channel_id)


def require_followup_access(job: JobRecord, run: Any, user_id: str | None) -> None:
    if not error_lineage_verified(job, run):
        raise MirrorDataForbidden()
    if protected_run(run):
        require_run_data_access(run, user_id)


def safe_diagnostics_stored(run: Any) -> bool:
    return (getattr(run, "context", None) or {}).get("diagnostics_version") == DIAGNOSTICS_VERSION


def job_diagnostics_protected(job: JobRecord, run: Any) -> bool:
    return run is None or protected_run(run) or not error_lineage_verified(job, run)


def project_job(job: JobRecord, viewer_id: str | None) -> JobRecord:
    run = get_run_store().get_run(job.id)
    payload = dict(job.input)
    payload.pop(ERROR_SOURCE_VERIFIED, None)
    payload.pop("on_demand_test", None)
    if not job_diagnostics_protected(job, run):
        return replace(job, input=payload)

    source = payload.get("error_source")
    if source is not None:
        try:
            require_followup_access(job, run, viewer_id)
        except MirrorDataForbidden:
            payload.pop("error_source")
        else:
            if job.input.get(ERROR_SOURCE_VERIFIED) is not True:
                payload.pop("error_source")
    code, message = job.error_code, job.error_summary
    if code is not None or message is not None:
        code, message = public_error(code)
    if run is None:
        payload = {}
    return replace(job, input=payload, error_code=code, error_summary=message,
                   log_body=message or "", result=job.result if safe_diagnostics_stored(run) else None)
