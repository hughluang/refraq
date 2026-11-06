"""Entity database engines and pools. Never merged with the metadata engine.

Opened by the API process (owner and reader pools for the Entity Data API),
by the worker (owner pool for publish / drop), and by the Entity MCP process
(reader pool only). Metadata MCP and Beat do not open these pools. Schema
discovery uses only the metadata store.
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
from backend.entity.ddl import ENTITY_SCHEMAS

__all__ = [
    "get_entity_engine",
    "get_entity_reader_engine",
    "open_entity_pool_when_persistent",
    "open_entity_reader_pool_when_persistent",
    "require_entity_schemas",
    "require_unprivileged_role",
    "reset_entity_engine",
]

_LOCK_TIMEOUT_MS = 5000
_IDLE_IN_TRANSACTION_MS = 60_000
_BOOTSTRAP_COMMAND = "python -m backend.entity.bootstrap"
_SCHEMA_PRESENCE_SQL = text(
    "SELECT nspname FROM pg_namespace WHERE nspname IN ("
    + ", ".join(f"'{name}'" for name in ENTITY_SCHEMAS)
    + ")"
)


def open_entity_pool_when_persistent() -> None:
    """Open and check the entity pools in persistent mode. No-op for memory tests.

    The worker opens the owner pool; the API also opens the reader pool. The
    Entity MCP process opens the reader pool only. Every runtime entity
    connection must name a database other than the metadata database and log in
    as a role that is not a superuser. The owner connection must already have
    every schema the entity bootstrap creates. This check does not create
    schemas and does not read the admin URL.
    """
    if get_runtime_capacity().role == "entity_mcp":
        open_entity_reader_pool_when_persistent()
        return
    settings = get_settings()
    if settings.store_backend != "persistent":
        return
    owner_url = require_entity_database_url(settings.entity_database_url)
    require_distinct_entity_database(owner_url, settings.database_url)
    with get_entity_engine().connect() as conn:
        require_unprivileged_role(conn, "ENTITY_DATABASE_URL")
        require_entity_schemas(conn)
    if get_runtime_capacity().role != "api":
        return
    reader_url = require_entity_reader_database_url(
        settings.entity_reader_database_url, owner_url=owner_url
    )
    require_distinct_entity_database(reader_url, settings.database_url)
    with get_entity_reader_engine().connect() as conn:
        require_unprivileged_role(conn, "ENTITY_READER_DATABASE_URL", reader=True)


def _reader_database_url() -> str:
    """Reader URL for the current process.

    Role ``entity_mcp`` does not require ``ENTITY_DATABASE_URL``. When that
    variable is set, the reader database must still equal it. When it is
    absent, that comparison is skipped. Other roles still require the owner URL.
    """
    settings = get_settings()
    owner_url = (settings.entity_database_url or "").strip()
    if get_runtime_capacity().role == "entity_mcp" and not owner_url:
        return require_entity_reader_database_url(
            settings.entity_reader_database_url, owner_url=None
        )
    return require_entity_reader_database_url(
        settings.entity_reader_database_url,
        owner_url=require_entity_database_url(settings.entity_database_url),
    )


def open_entity_reader_pool_when_persistent() -> None:
    """Open and check the entity reader pool. No-op for memory tests.

    Persistent Entity MCP startup. Refuses a missing reader URL, a reader
    database equal to the metadata database, and a superuser or BYPASSRLS
    login. Does not construct the owner engine and does not require
    ``ENTITY_DATABASE_URL``. When that variable is set, the reader database
    must still name the same database.
    """
    settings = get_settings()
    if settings.store_backend != "persistent":
        return
    reader_url = _reader_database_url()
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


def require_entity_schemas(conn: Connection) -> None:
    """Refuse startup when a schema created by entity bootstrap is absent.

    Checked on the owner connection. The reader URL names the same database.
    """
    present = {str(row[0]) for row in conn.execute(_SCHEMA_PRESENCE_SQL)}
    missing = [name for name in ENTITY_SCHEMAS if name not in present]
    if not missing:
        return
    listed = ", ".join(missing)
    noun = "schema" if len(missing) == 1 else "schemas"
    raise ValueError(
        f"ENTITY_DATABASE_URL is missing {noun} {listed}; run {_BOOTSTRAP_COMMAND}"
    )


@lru_cache
def get_entity_engine() -> Engine:
    if get_runtime_capacity().role == "entity_mcp":
        raise RuntimeError("entity_mcp must not open the entity owner engine")
    return _engine(require_entity_database_url(get_settings().entity_database_url))


@lru_cache
def get_entity_reader_engine() -> Engine:
    return _engine(_reader_database_url())


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
