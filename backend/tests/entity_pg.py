"""Shared Postgres setup for Entity Table DDL that names product roles."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, make_url

from backend.entity.bootstrap import run_bootstrap
from backend.entity.ddl import (
    ACL_OWNER_ROLE,
    ENTITY_OWNER_ROLE,
    EXPOSURE_OWNER_ROLE,
    READER_ROLE,
)

_ENSURE_ROLES = """
DO $body$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'refraq_entity_owner') THEN
    CREATE ROLE refraq_entity_owner NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'refraq_exposure_owner') THEN
    CREATE ROLE refraq_exposure_owner NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'refraq_reader') THEN
    CREATE ROLE refraq_reader NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;
  END IF;
END
$body$;
"""
_ROLES = (ENTITY_OWNER_ROLE, EXPOSURE_OWNER_ROLE, ACL_OWNER_ROLE, READER_ROLE)


def ensure_entity_ddl_targets(conn: Connection) -> None:
    """Roles and ``entity_data`` so publish DDL can name them.

    Roles are cluster-wide. Existing roles are left unchanged, including
    passwords set by ``python -m backend.entity.bootstrap``.
    """
    conn.execute(text(_ENSURE_ROLES))
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS entity_data"))


@dataclass(frozen=True)
class EntityDatabase:
    admin_url: str
    owner_url: str
    reader_url: str


@contextmanager
def bootstrapped_entity_database(maintenance_url: str, prefix: str) -> Iterator[EntityDatabase]:
    """A throwaway PostgreSQL 18 database after ``run_bootstrap``.

    Bootstrap sets cluster-wide role passwords; the previous ones are put back on exit.
    """
    maintenance = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    database = f"{prefix}_{uuid.uuid4().hex[:8]}"
    base = make_url(maintenance_url)
    before: dict[str, str | None] = {}
    created = False
    try:
        with maintenance.connect() as conn:
            version = int(conn.execute(text("SHOW server_version_num")).scalar_one())
            if version < 180000:
                pytest.skip(f"PostgreSQL server_version_num={version} is older than 18")
            before = _snapshot(conn)
            conn.execute(text(f'CREATE DATABASE "{database}"'))
            created = True
        urls = EntityDatabase(
            admin_url=_url(base, database, base.username or "refraq", base.password or ""),
            owner_url=_url(base, database, ENTITY_OWNER_ROLE, "owner-secret"),
            reader_url=_url(base, database, READER_ROLE, "reader-secret"),
        )
        run_bootstrap(urls.admin_url, urls.owner_url, urls.reader_url)
        yield urls
    finally:
        with maintenance.connect() as conn:
            if created:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :name AND pid <> pg_backend_pid()"
                    ),
                    {"name": database},
                )
                conn.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
            if before or created:
                _restore(conn, before)
        maintenance.dispose()


def _url(base, database: str, username: str, password: str) -> str:
    return base.set(database=database, username=username, password=password).render_as_string(
        hide_password=False
    )


def _snapshot(conn: Connection) -> dict[str, str | None]:
    rows = conn.execute(
        text("SELECT rolname, rolpassword FROM pg_authid WHERE rolname = ANY(:names)"),
        {"names": list(_ROLES)},
    ).all()
    return {str(name): password for name, password in rows}


def _restore(conn: Connection, before: dict[str, str | None]) -> None:
    for name in _ROLES:
        if name not in before:
            conn.execute(text(f'ALTER ROLE "{name}" WITH NOLOGIN PASSWORD NULL'))
            continue
        conn.execute(
            text("UPDATE pg_authid SET rolpassword = :password WHERE rolname = :name"),
            {"name": name, "password": before[name]},
        )
