"""Entity database engines and pools. Never merged with the metadata engine.

Opened by the API process (owner and reader pools for the Entity Data API) and
by the worker (owner pool for publish / drop). MCP and Beat do not open these
pools. Schema discovery uses only the metadata store.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from backend.core.config import (
    get_settings,
    require_distinct_entity_database,
    require_entity_database_url,
    require_entity_reader_database_url,
)
from backend.core.db import ObservedQueuePool
from backend.core.runtime import get_runtime_capacity

__all__ = [
    "get_entity_engine",
    "get_entity_reader_engine",
    "open_entity_pool_when_persistent",
    "require_unprivileged_role",
    "reset_entity_engine",
]

_LOCK_TIMEOUT_MS = 5000
_IDLE_IN_TRANSACTION_MS = 60_000


def open_entity_pool_when_persistent() -> None:
    """Open and check the entity pools in persistent mode. No-op for memory tests.

    The worker opens the owner pool; the API also opens the reader pool. Every
    runtime entity connection must name a database other than the metadata
    database and log in as a role that is not a superuser.
    """
    settings = get_settings()
    if settings.store_backend != "persistent":
        return
    owner_url = require_entity_database_url(settings.entity_database_url)
    require_distinct_entity_database(owner_url, settings.database_url)
    with get_entity_engine().connect() as conn:
        require_unprivileged_role(conn, "ENTITY_DATABASE_URL")
    if get_runtime_capacity().role != "api":
        return
    reader_url = require_entity_reader_database_url(
        settings.entity_reader_database_url, owner_url=owner_url
    )
    require_distinct_entity_database(reader_url, settings.database_url)
    with get_entity_reader_engine().connect() as conn:
        require_unprivileged_role(conn, "ENTITY_READER_DATABASE_URL", reader=True)


def require_unprivileged_role(
    conn: Connection, setting: str, *, reader: bool = False
) -> None:
    row = conn.execute(
        text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
    ).one()
    if bool(row[0]):
        raise ValueError(f"{setting} must not log in as a superuser")
    if reader and bool(row[1]):
        raise ValueError(f"{setting} must not log in as a BYPASSRLS role")


@lru_cache
def get_entity_engine() -> Engine:
    return _engine(require_entity_database_url(get_settings().entity_database_url))


@lru_cache
def get_entity_reader_engine() -> Engine:
    settings = get_settings()
    return _engine(
        require_entity_reader_database_url(
            settings.entity_reader_database_url,
            owner_url=require_entity_database_url(settings.entity_database_url),
        )
    )


def _engine(url: str) -> Engine:
    cap = get_runtime_capacity()
    return create_engine(
        url,
        poolclass=ObservedQueuePool,
        pool_size=cap.entity_pool_size,
        max_overflow=cap.entity_max_overflow,
        pool_timeout=cap.entity_pool_timeout_sec,
        pool_recycle=cap.entity_pool_recycle_sec or -1,
        pool_pre_ping=True,
        connect_args=_connect_args(url),
    )


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
    for factory in (get_entity_engine, get_entity_reader_engine):
        engine = None
        try:
            engine = factory()
        except Exception:
            pass
        factory.cache_clear()
        if engine is not None:
            engine.dispose()
