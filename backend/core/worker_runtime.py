"""Publish process-local worker/beat runtime capacity."""

from __future__ import annotations

from backend.core.db import reset_db_singletons
from backend.core.runtime import get_runtime_capacity, log_capacity_warnings, set_process_role


def mark_worker_process(**_kwargs: object) -> None:
    set_process_role("worker")
    reset_db_singletons()


def init_parent_worker_runtime(**_kwargs: object) -> None:
    mark_worker_process()
    log_capacity_warnings(get_runtime_capacity())
