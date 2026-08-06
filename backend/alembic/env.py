"""Alembic environment — URL comes from settings or alembic.ini override."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.core.db import Base
import backend.admin.models  # noqa: F401 — register Foundation tables
import backend.metadata.models  # noqa: F401 — register metadata tables
import backend.worker.models  # noqa: F401 — register Scheduled Task tables

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url and not url.startswith("driver://"):
        return url
    from backend.core.config import get_settings

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to run Alembic")
    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
