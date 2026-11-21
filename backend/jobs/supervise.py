"""Run a claimed Job in a child process and kill that process group on cancel."""

from __future__ import annotations

import importlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable

from backend.core.config import get_settings
from backend.jobs.store import (
    claim_queued,
    current_worker_id,
    get_job_store,
    mark_failed,
)

POLL_SEC = 0.2

RunFn = Callable[[str], dict[str, str]]


def supervise(job_id: str, target: str) -> dict[str, str]:
    """Run `module:function` for this Job.

    Memory stores stay in-process so tests share the parent store. A SQL store
    claims here, then the child adopts that claim.
    """
    if get_settings().store_backend == "memory":
        return _call(target, job_id)
    claimed = claim_queued(job_id, celery_task_id=job_id, claimed_by=current_worker_id())
    if claimed is None:
        record = get_job_store().get(job_id)
        return {"status": record.status if record else "missing"}
    proc = _spawn(job_id, target)
    watch_process(job_id, proc)
    return _finish(job_id)


def watch_process(
    job_id: str,
    proc: subprocess.Popen[bytes],
    *,
    poll_sec: float = POLL_SEC,
) -> int:
    """Kill `proc`'s process group when the Job row is `cancelled`. Return the exit code."""
    try:
        while proc.poll() is None:
            record = get_job_store().get(job_id)
            if record is not None and record.status == "cancelled":
                break
            time.sleep(poll_sec)
    finally:
        if proc.poll() is None:
            _kill_group(proc)
        proc.wait()
    return proc.returncode if proc.returncode is not None else -1


def _finish(job_id: str) -> dict[str, str]:
    record = get_job_store().get(job_id)
    if record is None:
        return {"status": "missing"}
    if record.status == "running":
        mark_failed(
            job_id,
            error_code="JOB_EXECUTION_FAILED",
            error_summary="Worker child exited before the Job finished",
        )
        return {"status": "failed"}
    return {"status": record.status}


def _spawn(job_id: str, target: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "backend.jobs.job_child", target, job_id],
        start_new_session=True,
    )


def _call(target: str, job_id: str) -> dict[str, str]:
    module_name, func_name = target.split(":")
    fn: RunFn = getattr(importlib.import_module(module_name), func_name)
    return fn(job_id)


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    if proc.pid is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
