"""One Alembic run from 0049 to head seeds access policy for existing Entities.

Skipped when the integration server is not reachable. Does not start Docker.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_BEFORE = "0049_entity_reference_snapshots"


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


def _config(database_url: str) -> Config:
    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    return cfg


def test_single_upgrade_from_0049_seeds_existing_entities() -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available")
    database = f"refraq_emig_{uuid.uuid4().hex[:8]}"
    maintenance = create_engine(_MAINTENANCE_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with maintenance.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{database}"'))
    url = make_url(_MAINTENANCE_DATABASE_URL).set(database=database)
    database_url = url.render_as_string(hide_password=False)
    engine = create_engine(database_url)
    try:
        command.upgrade(_config(database_url), _BEFORE)
        now = datetime.now(timezone.utc)
        attributes = [{"name": "sku", "type": "string", "max_length": 32}]
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO roles (id, key, name, permissions, locked, created_at) VALUES "
                    "('role_reader', 'data_reader', 'Reader', "
                    "CAST(:read AS jsonb), false, 0), "
                    "('role_writer', 'data_writer', 'Writer', "
                    "CAST(:write AS jsonb), false, 0), "
                    "('role_none', 'console_only', 'Console', "
                    "CAST(:none AS jsonb), false, 0)"
                ),
                {
                    "read": json.dumps(["entity:data_read"]),
                    "write": json.dumps(["entity:data_read", "entity:data_write"]),
                    "none": json.dumps(["console:access"]),
                },
            )
            conn.execute(
                text(
                    "INSERT INTO business_entities "
                    "(id, table_name, name, description, created_at, updated_at) "
                    "VALUES ('ent_legacy', 'legacy', 'Legacy', '', :now, :now)"
                ),
                {"now": now},
            )
            conn.execute(
                text(
                    "INSERT INTO entity_versions (id, entity_id, version, attributes, "
                    "materialized_attributes, publish_status, dictionary_snapshots, "
                    "reference_snapshots, created_at, updated_at) VALUES "
                    "('ver_legacy', 'ent_legacy', 1, CAST(:attrs AS jsonb), "
                    "CAST(:attrs AS jsonb), 'published', '{}'::jsonb, '{}'::jsonb, :now, :now)"
                ),
                {"attrs": json.dumps(attributes), "now": now},
            )
        command.upgrade(_config(database_url), "head")
        with engine.connect() as conn:
            stamped = conn.execute(
                text(
                    "SELECT materialized_attributes FROM entity_versions WHERE id = 'ver_legacy'"
                )
            ).scalar_one()
            attribute_id = stamped[0]["attribute_id"]
            assert attribute_id.startswith("att_")
            columns = conn.execute(
                text(
                    "SELECT columns FROM entity_access_profiles "
                    "WHERE entity_id = 'ent_legacy' AND key = 'all_clear'"
                )
            ).scalar_one()
            assert columns == [{"attribute_id": attribute_id, "level": "clear"}]
            grants = {
                row[0]: sorted(row[1])
                for row in conn.execute(
                    text(
                        "SELECT subject_id, actions FROM entity_access_grants "
                        "WHERE entity_id = 'ent_legacy' AND subject_type = 'role'"
                    )
                )
            }
            assert grants == {"role_reader": ["read"], "role_writer": ["read", "write"]}
            revision, applied = conn.execute(
                text(
                    "SELECT revision, views_revision FROM entity_access_revisions "
                    "WHERE entity_id = 'ent_legacy'"
                )
            ).one()
            assert revision >= 1
            assert applied != revision
    finally:
        engine.dispose()
        with maintenance.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        maintenance.dispose()
