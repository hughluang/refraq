"""Foundation Upgrade: advisory-locked schema migrate, then System Role ensure."""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from backend.admin.roles import ensure_system_role
from backend.core.config import get_settings
from backend.repositories.role_store import get_role_store

# Stable 64-bit signed key derived from product identity (not a generic magic number).
_ADVISORY_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"refraq-alembic-migrate").digest()[:8],
    "big",
    signed=True,
)
_LOCK_TIMEOUT_SECONDS = 60
_LOCK_POLL_SECONDS = 0.5

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    return cfg


def migrate_with_advisory_lock(database_url: str) -> None:
    """Schema-only migrate under advisory lock (no System Role ensure)."""
    _run_under_advisory_lock(database_url, ensure_roles=False)


def run_upgrade(database_url: str) -> None:
    """Foundation Upgrade: migrate schema, then ensure System Role `super_admin`."""
    _run_under_advisory_lock(database_url, ensure_roles=True)


def _run_under_advisory_lock(database_url: str, *, ensure_roles: bool) -> None:
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        with engine.connect() as conn:
            deadline = time.time() + _LOCK_TIMEOUT_SECONDS
            acquired = False
            while time.time() < deadline:
                row = conn.execute(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": _ADVISORY_LOCK_KEY},
                ).scalar()
                if row:
                    acquired = True
                    break
                time.sleep(_LOCK_POLL_SECONDS)
            if not acquired:
                raise RuntimeError(
                    "timed out waiting for Postgres advisory lock for migrations"
                )
            try:
                command.upgrade(_alembic_config(database_url), "head")
                if ensure_roles:
                    ensure_system_role(get_role_store())
            finally:
                conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": _ADVISORY_LOCK_KEY},
                )
    finally:
        engine.dispose()


def main() -> None:
    settings = get_settings()
    if settings.store_backend != "persistent":
        print(
            "REFRAQ_STORE_BACKEND must be persistent for Foundation Upgrade",
            file=sys.stderr,
        )
        raise SystemExit(1)
    assert settings.database_url
    try:
        run_upgrade(settings.database_url)
    except Exception as exc:  # noqa: BLE001 — upgrade must exit non-zero with context
        print(f"upgrade failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
