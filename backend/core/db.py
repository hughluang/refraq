"""SQLAlchemy engine and session factory for persistent User/Role stores."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.core.config import get_settings


class Base(DeclarativeBase):
    """Shared metadata root; domain packages define tables against this base."""


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for persistent Store Backend")
    # Pin session TimeZone=UTC so offset-less literals cannot silently shift Instants.
    connect_args: dict[str, str] = {}
    if settings.database_url.startswith("postgresql"):
        connect_args["options"] = "-c TimeZone=UTC"
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
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
