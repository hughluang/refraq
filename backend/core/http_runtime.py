"""Apply process-local HTTP runtime capacity (limiter, admission, metrics)."""

from __future__ import annotations

import anyio

from backend.core.bulkhead import get_peek_bulkhead
from backend.core.metrics import bind_capacity_gauges
from backend.core.runtime import get_runtime_capacity, log_capacity_warnings


def apply_http_runtime() -> None:
    cap = get_runtime_capacity()
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = cap.thread_tokens
    log_capacity_warnings(cap)
    bind_capacity_gauges()
    get_peek_bulkhead()
