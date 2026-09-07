"""SQLAlchemy engine and session factory for persistent User/Role stores."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from pgvector.psycopg import register_vector
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from backend.core.config import get_settings
from backend.core.errors import AppError, PlatformCapacityExceeded, PlatformTimeout
from backend.core.metrics import observe_pool_checkout_wait, record_reject, set_pool_gauges
from backend.core.runtime import get_runtime_capacity

_SQLSTATE_CAPACITY = frozenset({"53300", "08001", "08004"})
_SQLSTATE_TIMEOUT = frozenset({"57014"})
_CAPACITY_TYPE_NAMES = frozenset({"ConnectionTimeout", "TooManyConnections"})
_TIMEOUT_TYPE_NAMES = frozenset({"QueryCanceled"})


class Base(DeclarativeBase):
    """Shared metadata root; domain packages define tables against this base."""


class ObservedQueuePool(QueuePool):
    """QueuePool that records checkout wait, including time blocked on a full pool."""

    def _do_get(self):  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        try:
            return super()._do_get()
        finally:
            observe_pool_checkout_wait(time.perf_counter() - started)


def _sync_pool_gauges(engine: Engine) -> None:
    pool = engine.pool
    overflow = pool.overflow()
    checked_out = pool.checkedout()
    size = pool.size()
    cap = get_runtime_capacity()
    set_pool_gauges(
        checked_out=checked_out,
        overflow=overflow,
        size=size,
        max_overflow=cap.max_overflow,
    )


def _connect_args(database_url: str) -> dict[str, str]:
    options = ["-c TimeZone=UTC"]
    cap = get_runtime_capacity()
    if cap.statement_timeout_ms is not None:
        options.append(f"-c statement_timeout={int(cap.statement_timeout_ms)}")
    connect_args: dict[str, str] = {}
    if database_url.startswith("postgresql"):
        connect_args["options"] = " ".join(options)
    return connect_args


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for persistent Store Backend")
    cap = get_runtime_capacity()
    engine = create_engine(
        settings.database_url,
        poolclass=ObservedQueuePool,
        pool_size=cap.pool_size,
        max_overflow=cap.max_overflow,
        pool_timeout=cap.pool_timeout_sec,
        pool_recycle=cap.pool_recycle_sec or -1,
        pool_pre_ping=True,
        connect_args=_connect_args(settings.database_url),
    )

    def _on_pool_event(*_args: object, **_kwargs: object) -> None:
        _sync_pool_gauges(engine)

    event.listen(engine, "checkout", _on_pool_event)
    event.listen(engine, "checkin", _on_pool_event)
    if settings.database_url.startswith("postgresql"):

        def _register_vector(dbapi_connection: object, *_args: object) -> None:
            register_vector(dbapi_connection)

        event.listen(engine, "connect", _register_vector)
    return engine


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


def _exception_chain(exc: BaseException) -> list[BaseException]:
    seen: set[int] = set()
    out: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        out.append(current)
        orig = getattr(current, "orig", None)
        if isinstance(orig, BaseException) and id(orig) not in seen:
            seen.add(id(orig))
            out.append(orig)
        current = current.__cause__ or current.__context__
    return out


def _sqlstate(exc: BaseException) -> str | None:
    for item in _exception_chain(exc):
        code = getattr(item, "sqlstate", None) or getattr(item, "pgcode", None)
        if isinstance(code, str) and code:
            return code
    return None


def map_platform_db_error(exc: BaseException) -> AppError | None:
    """Translate platform-pool / platform-Postgres failures to Problem Codes."""
    if isinstance(exc, PoolTimeoutError):
        record_reject(PlatformCapacityExceeded.code)
        return PlatformCapacityExceeded()
    state = _sqlstate(exc)
    type_names = {type(item).__name__ for item in _exception_chain(exc)}
    if state in _SQLSTATE_TIMEOUT or type_names & _TIMEOUT_TYPE_NAMES:
        record_reject(PlatformTimeout.code)
        return PlatformTimeout()
    if state in _SQLSTATE_CAPACITY or type_names & _CAPACITY_TYPE_NAMES:
        record_reject(PlatformCapacityExceeded.code)
        return PlatformCapacityExceeded()
    return None


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception as exc:
        session.rollback()
        if isinstance(exc, AppError):
            raise
        mapped = map_platform_db_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    finally:
        session.close()


def ping_database() -> None:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))


def reset_db_singletons() -> None:
    get_session_factory.cache_clear()
    engine = None
    try:
        engine = get_engine()
    except Exception:
        pass
    get_engine.cache_clear()
    if engine is not None:
        engine.dispose()
