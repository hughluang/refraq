"""Intranet Prometheus metrics for runtime capacity (API and MCP)."""

from __future__ import annotations

import anyio
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from starlette.responses import Response

from backend.core.bulkhead import get_peek_bulkhead
from backend.core.runtime import get_runtime_capacity

REGISTRY = CollectorRegistry()

HTTP_INFLIGHT = Gauge(
    "refraq_http_inflight",
    "Admitted in-flight HTTP requests (load-shed counter)",
    registry=REGISTRY,
)
HTTP_INFLIGHT_LIMIT = Gauge(
    "refraq_http_inflight_limit",
    "REFRAQ_HTTP_MAX_INFLIGHT",
    registry=REGISTRY,
)
REJECTS = Counter(
    "refraq_capacity_rejects_total",
    "Capacity rejects by Problem Code",
    ["code"],
    registry=REGISTRY,
)
THREAD_BORROWED = Gauge(
    "refraq_thread_tokens_borrowed",
    "AnyIO default limiter borrowed tokens",
    registry=REGISTRY,
)
THREAD_TOTAL = Gauge(
    "refraq_thread_tokens_total",
    "AnyIO default limiter total_tokens",
    registry=REGISTRY,
)
PEEK_OCCUPIED = Gauge(
    "refraq_admission_slots_occupied",
    "Admission pool occupancy",
    registry=REGISTRY,
)
PEEK_LIMIT = Gauge(
    "refraq_admission_slots_limit",
    "Admission pool size",
    registry=REGISTRY,
)
PEEK_SHARE_LIMIT = Gauge(
    "refraq_admission_actor_share_limit",
    "Per-actor admission share (ADMISSION_ACTOR_LIMIT_EXCEEDED threshold)",
    registry=REGISTRY,
)
POOL_CHECKED_OUT = Gauge(
    "refraq_db_pool_checked_out",
    "SQLAlchemy pool checked-out connections",
    registry=REGISTRY,
)
POOL_OVERFLOW = Gauge(
    "refraq_db_pool_overflow",
    "SQLAlchemy pool overflow connections",
    registry=REGISTRY,
)
POOL_SIZE = Gauge(
    "refraq_db_pool_size",
    "SQLAlchemy pool_size",
    registry=REGISTRY,
)
POOL_MAX_OVERFLOW = Gauge(
    "refraq_db_pool_max_overflow",
    "SQLAlchemy max_overflow",
    registry=REGISTRY,
)
CHECKOUT_WAIT = Histogram(
    "refraq_db_pool_checkout_wait_seconds",
    "Time spent in QueuePool._do_get including wait for a free slot",
    registry=REGISTRY,
)
WORK_TOKENS = Gauge(
    "refraq_runtime_work_tokens",
    "thread_tokens (platform short-read budget)",
    registry=REGISTRY,
)
POOL_BUDGET = Gauge(
    "refraq_runtime_pool_budget",
    "pool_size + max_overflow (invariant right-hand side)",
    registry=REGISTRY,
)
NEIGHBOR = Histogram(
    "refraq_catalog_neighbor_seconds",
    "Catalog Search semantic neighbor step (embed or score)",
    ["kind", "step"],
    registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
VECTOR_ERRORS = Counter(
    "refraq_catalog_search_vector_errors_total",
    "Catalog Search vector path failed (embed or neighbor); request errors",
    ["reason"],
    registry=REGISTRY,
)
HYBRID = Counter(
    "refraq_catalog_search_hybrid_total",
    "Catalog Search declared path by outcome (vector or lexical)",
    ["outcome"],
    registry=REGISTRY,
)


def observe_pool_checkout_wait(seconds: float) -> None:
    CHECKOUT_WAIT.observe(seconds)


def set_pool_gauges(*, checked_out: int, overflow: int, size: int, max_overflow: int) -> None:
    POOL_CHECKED_OUT.set(checked_out)
    POOL_OVERFLOW.set(overflow)
    POOL_SIZE.set(size)
    POOL_MAX_OVERFLOW.set(max_overflow)


def set_http_inflight(current: int, limit: int) -> None:
    HTTP_INFLIGHT.set(current)
    HTTP_INFLIGHT_LIMIT.set(limit)


def record_reject(code: str) -> None:
    REJECTS.labels(code=code).inc()


def observe_catalog_neighbor(kind: str, step: str, seconds: float) -> None:
    NEIGHBOR.labels(kind=kind, step=step).observe(seconds)


def record_catalog_search_vector_error(reason: str) -> None:
    VECTOR_ERRORS.labels(reason=reason).inc()


def record_catalog_hybrid(outcome: str) -> None:
    HYBRID.labels(outcome=outcome).inc()


def bind_capacity_gauges() -> None:
    cap = get_runtime_capacity()
    HTTP_INFLIGHT_LIMIT.set(cap.http_max_inflight)
    THREAD_TOTAL.set(cap.thread_tokens)
    PEEK_LIMIT.set(cap.admission_slots)
    PEEK_SHARE_LIMIT.set(cap.admission_actor_share)
    POOL_SIZE.set(cap.pool_size)
    POOL_MAX_OVERFLOW.set(cap.max_overflow)
    WORK_TOKENS.set(cap.thread_tokens)
    POOL_BUDGET.set(cap.pool_max_connections)


def metrics_response() -> Response:
    bind_capacity_gauges()
    limiter = anyio.to_thread.current_default_thread_limiter()
    THREAD_BORROWED.set(limiter.borrowed_tokens)
    THREAD_TOTAL.set(limiter.total_tokens)
    snap = get_peek_bulkhead().snapshot()
    PEEK_OCCUPIED.set(snap.occupied)
    PEEK_LIMIT.set(snap.limit)
    PEEK_SHARE_LIMIT.set(snap.share_limit)
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
