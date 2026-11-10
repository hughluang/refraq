"""search_entities Top-K against pgvector on the metadata database.

The authorized set is ranked before the limit. A nearer entity without a
grant stays out, and cosine 0 and cosine -1 stay in. This file does not
open a business Entity database.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from backend.tests.test_entity_mcp_search import (
    _call,
    _grant,
    _install_embed,
    _open_model,
    _pat,
    _publish,
    _ready,
    _reset,
    _seed_vector,
    _user,
)

_INTEGRATION_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)
_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_MIGRATED = False
_MID_SCORE = 0.7071067811865476
_TABLES = (
    "entity_embeddings",
    "entity_access_grants",
    "entity_access_profiles",
    "entity_access_restrictions",
    "entity_access_revisions",
    "entity_presentation_ladders",
    "entity_profile_view_bindings",
    "entity_versions",
    "tag_assignments",
    "tag_subject_revisions",
    "business_entities",
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


def _migrate_once() -> None:
    global _MIGRATED
    if _MIGRATED:
        return
    engine = create_engine(_INTEGRATION_DATABASE_URL)
    with engine.begin() as conn:
        present = conn.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar()
        if present:
            conn.execute(
                text(
                    "ALTER TABLE alembic_version "
                    "ALTER COLUMN version_num TYPE varchar(64)"
                )
            )
    engine.dispose()
    from backend.core.entry import migrate_with_advisory_lock

    migrate_with_advisory_lock(_INTEGRATION_DATABASE_URL)
    _MIGRATED = True


def _truncate() -> None:
    engine = create_engine(_INTEGRATION_DATABASE_URL)
    with engine.begin() as conn:
        present = [
            name
            for name in _TABLES
            if conn.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{name}"},
            ).scalar()
        ]
        if present:
            conn.execute(
                text("TRUNCATE TABLE " + ", ".join(present) + " RESTART IDENTITY CASCADE")
            )
    engine.dispose()


@pytest.fixture()
def metadata_db(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    _migrate_once()
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
    monkeypatch.setenv("DATABASE_URL", _INTEGRATION_DATABASE_URL)
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    from backend.core.config import reset_settings_cache
    from backend.core.db import reset_db_singletons

    reset_settings_cache()
    reset_db_singletons()
    _reset()
    from backend.entity.projection import bind_entity_projection_drop_hook

    bind_entity_projection_drop_hook(None)
    _truncate()
    yield
    _reset()
    reset_settings_cache()
    reset_db_singletons()


def test_search_entities_ranks_the_authorized_set_in_postgres(
    metadata_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.admin.role_store import get_role_store
    from backend.admin.roles import create_role, seed_roles
    from backend.core.config import get_settings

    assert get_settings().store_backend == "persistent"
    _open_model()
    roles = get_role_store()
    seed_roles(roles)
    suffix = uuid.uuid4().hex[:8]
    role = create_role(
        roles,
        key=f"entity_search_pg_{suffix}",
        name="Entity search pg",
        permissions=["entity:data_read"],
    )
    user_id = _user(f"search_pg_{suffix}", role.id)
    secret = _pat(user_id)
    specs = (
        ("ent_hidden", (1.0, 0.0), False),
        ("ent_b", (1.0, 1.0), True),
        ("ent_a", (1.0, 1.0), True),
        ("ent_zero", (0.0, 1.0), True),
        ("ent_neg", (-1.0, 0.0), True),
    )
    for table_name, vector, allowed in specs:
        entity_id, attribute_id = _publish(table_name)
        if allowed:
            _grant(entity_id, attribute_id, "user", user_id)
        _seed_vector(entity_id, vector)
    _ready()
    _install_embed(monkeypatch, [])

    topped = _call(secret, query_text="nearest", limit=2)
    assert [item["table_name"] for item in topped["items"]] == ["ent_a", "ent_b"]
    assert set(topped) == {"items"}

    page = _call(secret, query_text="nearest", limit=10)
    assert [item["table_name"] for item in page["items"]] == [
        "ent_a",
        "ent_b",
        "ent_zero",
        "ent_neg",
    ]
    assert page["items"][0]["score"] == pytest.approx(_MID_SCORE)
    assert page["items"][1]["score"] == pytest.approx(_MID_SCORE)
    assert page["items"][2]["score"] == pytest.approx(0.0, abs=1e-6)
    assert page["items"][3]["score"] == pytest.approx(-1.0, abs=1e-6)
    assert "ent_hidden" not in [item["table_name"] for item in page["items"]]
