"""Entity database engine and pool. Never merged with the metadata engine.

Opened by the API process (Entity Data API action verbs) and by the worker
(publish / drop). MCP and Beat do not open this pool. Schema discovery uses
only the metadata store.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from backend.core.config import get_settings, require_entity_database_url
from backend.core.db import ObservedQueuePool
from backend.core.runtime import get_runtime_capacity

__all__ = [
    "entity_db_schema",
    "get_entity_engine",
    "open_entity_pool_when_persistent",
    "reset_entity_engine",
]

_LOCK_TIMEOUT_MS = 5000
_IDLE_IN_TRANSACTION_MS = 60_000


def entity_db_schema() -> str:
    settings = get_settings()
    schema = (settings.refraq_entity_db_schema or "public").strip()
    return schema or "public"


def open_entity_pool_when_persistent() -> None:
    """Open the entity pool in persistent mode. No-op for memory tests."""
    settings = get_settings()
    if settings.store_backend != "persistent":
        return
    require_entity_database_url(settings.entity_database_url)
    engine = get_entity_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


@lru_cache
def get_entity_engine() -> Engine:
    url = require_entity_database_url(get_settings().entity_database_url)
    cap = get_runtime_capacity()
    engine = create_engine(
        url,
        poolclass=ObservedQueuePool,
        pool_size=cap.entity_pool_size,
        max_overflow=cap.entity_max_overflow,
        pool_timeout=cap.entity_pool_timeout_sec,
        pool_recycle=cap.entity_pool_recycle_sec or -1,
        pool_pre_ping=True,
        connect_args=_connect_args(url),
    )
    return engine


def _connect_args(database_url: str) -> dict[str, str]:
    if not database_url.startswith("postgresql"):
        return {}
    options = [
        "-c TimeZone=UTC",
        f"-c lock_timeout={_LOCK_TIMEOUT_MS}",
        f"-c idle_in_transaction_session_timeout={_IDLE_IN_TRANSACTION_MS}",
    ]
    cap = get_runtime_capacity()
    if cap.statement_timeout_ms is not None:
        options.append(f"-c statement_timeout={int(cap.statement_timeout_ms)}")
    return {"options": " ".join(options)}


def reset_entity_engine() -> None:
    engine = None
    try:
        engine = get_entity_engine()
    except Exception:
        pass
    get_entity_engine.cache_clear()
    if engine is not None:
        engine.dispose()
