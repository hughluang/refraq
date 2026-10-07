"""Signed context and revision fence against PostgreSQL 18 acl functions.

Skipped when the integration server is not reachable. Does not start Docker.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, make_url

from backend.entity.access.context import sign_payload
from backend.entity.bootstrap import run_bootstrap
from backend.entity.ddl import (
    ACL_OWNER_ROLE,
    ENTITY_OWNER_ROLE,
    EXPOSURE_OWNER_ROLE,
    READER_ROLE,
)

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_OWNER_PASSWORD = "owner-secret"
_READER_PASSWORD = "reader-secret"
_ROLES = (ENTITY_OWNER_ROLE, EXPOSURE_OWNER_ROLE, ACL_OWNER_ROLE, READER_ROLE)
NOW = datetime.now(timezone.utc)


def _postgres_available() -> bool:
    engine = create_engine(_MAINTENANCE_DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


def _url(database: str, *, username: str, password: str) -> str:
    url = make_url(_MAINTENANCE_DATABASE_URL).set(
        database=database, username=username, password=password
    )
    return url.render_as_string(hide_password=False)


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


def test_signed_revision_mismatch_returns_no_rows() -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available")
    maintenance = create_engine(_MAINTENANCE_DATABASE_URL, isolation_level="AUTOCOMMIT")
    database = f"refraq_eview_{uuid.uuid4().hex[:8]}"
    before: dict[str, str | None] = {}
    try:
        with maintenance.connect() as conn:
            version = int(conn.execute(text("SHOW server_version_num")).scalar_one())
            if version < 180000:
                pytest.skip(f"PostgreSQL server_version_num={version} is older than 18")
            before = _snapshot(conn)
            conn.execute(text(f'CREATE DATABASE "{database}"'))
        admin_url = _url(
            database,
            username=make_url(_MAINTENANCE_DATABASE_URL).username or "refraq",
            password=make_url(_MAINTENANCE_DATABASE_URL).password or "",
        )
        owner_url = _url(database, username=ENTITY_OWNER_ROLE, password=_OWNER_PASSWORD)
        reader_url = _url(database, username=READER_ROLE, password=_READER_PASSWORD)
        run_bootstrap(admin_url, owner_url, reader_url)
        secret = b"k" * 32
        payload = {
            "sub": "user_1",
            "grants": ["g1"],
            "attrs": {},
            "rev": {"ent_fence": 2},
            "exp": int(NOW.timestamp()) + 3600,
            "req": "req_1",
            "kid": "k1",
        }
        token = sign_payload(payload, secret)
        admin = create_engine(admin_url)
        reader = create_engine(reader_url)
        try:
            with admin.begin() as conn:
                conn.execute(text("SELECT acl.install_key(:kid, :secret)"), {"kid": "k1", "secret": secret})
                conn.execute(
                    text(
                        "CREATE TABLE entity_data.fence_probe ("
                        "row_id bigint PRIMARY KEY, name text)"
                    )
                )
                conn.execute(text("INSERT INTO entity_data.fence_probe VALUES (1, 'ada')"))
                conn.execute(
                    text(
                        "CREATE VIEW entity_access.fence_v WITH (security_barrier = true) AS "
                        "SELECT row_id, name FROM entity_data.fence_probe AS t "
                        "WHERE (SELECT acl.rev_ok('ent_fence', 1))"
                    )
                )
                conn.execute(text("GRANT SELECT ON entity_access.fence_v TO refraq_reader"))
            with reader.connect() as conn:
                conn.execute(text("SELECT set_config('app.ctx', :token, true)"), {"token": token})
                assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is True
                assert conn.execute(text("SELECT acl.rev_ok('ent_fence', 2)")).scalar_one() is True
                assert conn.execute(text("SELECT acl.rev_ok('ent_fence', 1)")).scalar_one() is False
                rows = conn.execute(text("SELECT name FROM entity_access.fence_v")).all()
                assert rows == []
                matched = sign_payload({**payload, "rev": {"ent_fence": 1}}, secret)
                conn.execute(
                    text("SELECT set_config('app.ctx', :token, true)"), {"token": matched}
                )
                seen = conn.execute(text("SELECT name FROM entity_access.fence_v")).scalar_one()
                assert seen == "ada"
                forged = token[:-1] + ("0" if token[-1] != "0" else "1")
                conn.execute(
                    text("SELECT set_config('app.ctx', :token, true)"), {"token": forged}
                )
                assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is False
                with pytest.raises(Exception):
                    conn.execute(text("SET ROLE refraq_entity_owner"))
                conn.rollback()
                conn.execute(text("RESET ROLE"))
                with pytest.raises(Exception):
                    conn.execute(text("SELECT name FROM entity_data.fence_probe"))
        finally:
            reader.dispose()
            admin.dispose()
    finally:
        with maintenance.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
            if before:
                _restore(conn, before)
        maintenance.dispose()
