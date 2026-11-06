"""Signer role on PostgreSQL 18: one function, and a context the reader accepts."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from backend.core.runtime import reset_runtime_capacity, set_process_role
from backend.entity.access.context import sign_payload
from backend.entity.access.enforce import read_context, reset_signing_ring
from backend.entity.ddl import SIGNER_ROLE
from backend.entity.entity_db import reset_entity_engine
from backend.tests.entity_pg import bootstrapped_entity_database
from backend.tests.test_entity_signer import _read_access

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def test_signer_obtains_the_key_and_the_reader_accepts_the_context() -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_sign") as urls:
        signer = create_engine(urls.signer_url)
        reader = create_engine(urls.reader_url)
        try:
            with signer.connect() as conn:
                who = conn.execute(
                    text(
                        "SELECT current_user, rolsuper, rolbypassrls, rolinherit "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                ).one()
                assert who[0] == SIGNER_ROLE
                assert who[1] is False
                assert who[2] is False
                assert who[3] is False
                first = conn.execute(
                    text("SELECT kid, secret FROM acl.ensure_signing_key()")
                ).one()
                conn.commit()
                again = conn.execute(
                    text("SELECT kid, secret FROM acl.ensure_signing_key()")
                ).one()
                conn.commit()
                assert again[0] == first[0]
                secret = first[1]
                if not isinstance(secret, bytes):
                    secret = bytes(secret)
                assert len(secret) >= 32
                for sql in (
                    "SELECT secret FROM entity_data.no_such",
                    "SELECT 1 FROM entity_access.no_such",
                    "SELECT kid FROM acl.signing_keys",
                    "SELECT acl.install_key('other', '\\x11'::bytea)",
                ):
                    with pytest.raises(ProgrammingError, match="permission denied"):
                        conn.execute(text(sql))
                    conn.rollback()
            payload = {
                "sub": "user_1",
                "grants": ["g1"],
                "attrs": {},
                "rev": {"ent_1": 3},
                "exp": int(datetime.now(timezone.utc).timestamp()) + 60,
                "req": "req-signer",
                "kid": str(first[0]),
            }
            token = sign_payload(payload, secret)
            with reader.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.ctx', :token, true)"), {"token": token}
                )
                assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is True
                assert (
                    conn.execute(text("SELECT acl.grant_active('other')")).scalar_one() is False
                )
        finally:
            signer.dispose()
            reader.dispose()


def test_entity_mcp_signs_a_context_the_reader_accepts_without_the_owner_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_sig2") as urls:
        set_process_role("entity_mcp")
        reset_runtime_capacity()
        reset_signing_ring()
        monkeypatch.setattr(
            "backend.entity.entity_db.get_settings",
            lambda: _SignerSettings(urls.reader_url, urls.signer_url),
        )
        monkeypatch.setattr(
            "backend.entity.access.enforce.get_settings",
            lambda: type("Persistent", (), {"store_backend": "persistent"})(),
        )
        monkeypatch.setattr(
            "backend.entity.access.enforce.get_entity_engine",
            lambda: (_ for _ in ()).throw(AssertionError("owner engine constructed")),
        )
        reader = create_engine(urls.reader_url)
        try:
            token = read_context(_read_access())
            assert token is not None
            with reader.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.ctx', :token, true)"), {"token": token}
                )
                assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is True
        finally:
            reader.dispose()
            reset_signing_ring()
            set_process_role("api")
            reset_runtime_capacity()
            reset_entity_engine()


class _SignerSettings:
    def __init__(self, reader_url: str, signer_url: str) -> None:
        self.store_backend = "persistent"
        self.entity_database_url = None
        self.entity_reader_database_url = reader_url
        self.entity_signer_database_url = signer_url
        self.database_url = "postgresql+psycopg://refraq:pw@127.0.0.1:5432/refraq"
