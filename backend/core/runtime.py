"""Process-role runtime capacity: pools, thread tokens, admission, inflight."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

ProcessRole = Literal["api", "mcp", "worker"]

_ROLE_ENV = "REFRAQ_PROCESS_ROLE"
_role: ProcessRole = "api"

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return int(raw)


def _admission_share(slots: int, configured: int) -> int:
    if slots <= 0:
        return 0
    return max(1, min(slots, configured))


def set_process_role(role: ProcessRole) -> None:
    global _role
    _role = role
    get_runtime_capacity.cache_clear()


def current_process_role() -> ProcessRole:
    env_role = os.environ.get(_ROLE_ENV, "").strip()
    if env_role in ("api", "mcp", "worker"):
        return env_role  # type: ignore[return-value]
    return _role


@dataclass(frozen=True)
class RuntimeCapacity:
    role: ProcessRole
    pool_size: int
    max_overflow: int
    pool_timeout_sec: float
    pool_recycle_sec: int
    statement_timeout_ms: int | None
    http_max_inflight: int
    thread_tokens: int
    admission_slots: int
    admission_actor_share: int
    uvicorn_limit_concurrency: int | None
    timeout_keep_alive: int

    @property
    def pool_max_connections(self) -> int:
        return self.pool_size + self.max_overflow


def _defaults_for(role: ProcessRole) -> dict[str, int]:
    if role == "mcp":
        return {
            "pool_size": 5,
            "max_overflow": 3,
            "thread_tokens": 4,
            "admission_slots": 16,
            "admission_actor_share": 8,
            "http_max_inflight": 16,
        }
    if role == "worker":
        return {
            "pool_size": 5,
            "max_overflow": 5,
            "thread_tokens": 0,
            "admission_slots": 0,
            "admission_actor_share": 0,
            "http_max_inflight": 0,
        }
    return {
        "pool_size": 8,
        "max_overflow": 4,
        "thread_tokens": 8,
        "admission_slots": 32,
        "admission_actor_share": 8,
        "http_max_inflight": 32,
    }


def _from_env(role: ProcessRole) -> RuntimeCapacity:
    d = _defaults_for(role)
    pool_size = max(1, _env_int("REFRAQ_DB_POOL_SIZE", d["pool_size"]))
    max_overflow = max(0, _env_int("REFRAQ_DB_MAX_OVERFLOW", d["max_overflow"]))
    pool_timeout_sec = float(_env_int("REFRAQ_DB_POOL_TIMEOUT_SEC", 5))
    pool_recycle_sec = max(0, _env_int("REFRAQ_DB_POOL_RECYCLE_SEC", 1800))
    if role == "worker":
        return RuntimeCapacity(
            role=role,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout_sec=pool_timeout_sec,
            pool_recycle_sec=pool_recycle_sec,
            statement_timeout_ms=None,
            http_max_inflight=0,
            thread_tokens=0,
            admission_slots=0,
            admission_actor_share=0,
            uvicorn_limit_concurrency=None,
            timeout_keep_alive=5,
        )
    http_max_inflight = max(1, _env_int("REFRAQ_HTTP_MAX_INFLIGHT", d["http_max_inflight"]))
    thread_tokens = max(1, _env_int("REFRAQ_THREAD_TOKENS", d["thread_tokens"]))
    admission_slots = max(0, _env_int("REFRAQ_ADMISSION_SLOTS", d["admission_slots"]))
    admission_actor_share = _admission_share(
        admission_slots,
        max(0, _env_int("REFRAQ_ADMISSION_ACTOR_SHARE", d["admission_actor_share"])),
    )
    statement_timeout_ms = max(0, _env_int("REFRAQ_DB_STATEMENT_TIMEOUT_MS", 30_000))
    if statement_timeout_ms == 0:
        statement_timeout_ms = None
    return RuntimeCapacity(
        role=role,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout_sec=pool_timeout_sec,
        pool_recycle_sec=pool_recycle_sec,
        statement_timeout_ms=statement_timeout_ms,
        http_max_inflight=http_max_inflight,
        thread_tokens=thread_tokens,
        admission_slots=admission_slots,
        admission_actor_share=admission_actor_share,
        uvicorn_limit_concurrency=None if role == "mcp" else http_max_inflight + 32,
        timeout_keep_alive=5,
    )


@lru_cache
def get_runtime_capacity() -> RuntimeCapacity:
    return _from_env(current_process_role())


def reset_runtime_capacity() -> None:
    get_runtime_capacity.cache_clear()


def log_capacity_warnings(cap: RuntimeCapacity) -> None:
    banner = (
        "runtime capacity role=%s pool=%s+%s timeout=%ss recycle=%ss "
        "statement_timeout_ms=%s inflight=%s thread_tokens=%s "
        "admission_slots=%s admission_actor_share=%s "
        "uvicorn_limit_concurrency=%s"
        % (
            cap.role,
            cap.pool_size,
            cap.max_overflow,
            cap.pool_timeout_sec,
            cap.pool_recycle_sec,
            cap.statement_timeout_ms,
            cap.http_max_inflight,
            cap.thread_tokens,
            cap.admission_slots,
            cap.admission_actor_share,
            cap.uvicorn_limit_concurrency,
        )
    )
    print(banner, flush=True)
    logger.info(banner)
    if cap.role in ("api", "mcp") and cap.thread_tokens > cap.pool_max_connections:
        logger.warning(
            "runtime capacity: thread_tokens (%s) exceed "
            "pool_size+max_overflow (%s); short reads will queue on the platform pool",
            cap.thread_tokens,
            cap.pool_max_connections,
        )
    print(
        "runtime capacity deploy constraint: sum over api/mcp/worker/beat of "
        f"(pool_size+max_overflow) should stay at or below 0.8 x Postgres max_connections; "
        f"this process budget is {cap.pool_max_connections}",
        flush=True,
    )
