"""Seed all-clear profiles and role grants, and record access-log duration.

Revision ID: 0054_entity_access_seed
Revises: 0053_access_views_revision

Runs on the migration connection so it sees tables created earlier in the same
upgrade transaction. Profile views are not created here. Startup reconciliation
enqueues entity_access_views for each seeded Entity.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0054_entity_access_seed"
down_revision: Union[str, None] = "0053_access_views_revision"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALL_CLEAR_KEY = "all_clear"
_SUPER_ADMIN_KEY = "super_admin"
_DATA_READ = "entity:data_read"
_DATA_WRITE = "entity:data_write"


def upgrade() -> None:
    op.add_column(
        "entity_access_logs",
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    roles = _entitled_roles(conn)
    for entity_id in conn.execute(sa.text("SELECT id FROM business_entities")).scalars():
        _seed_entity(conn, str(entity_id), roles, now)


def downgrade() -> None:
    op.drop_column("entity_access_logs", "duration_ms")


def _entitled_roles(conn: sa.Connection) -> list[tuple[str, list[str]]]:
    found: list[tuple[str, list[str]]] = []
    for role_id, key, permissions in conn.execute(
        sa.text("SELECT id, key, permissions FROM roles ORDER BY id")
    ):
        perms = set(permissions or [])
        if key == _SUPER_ADMIN_KEY:
            perms |= {_DATA_READ, _DATA_WRITE}
        if _DATA_READ not in perms and _DATA_WRITE not in perms:
            continue
        actions = ["read", "write"] if _DATA_WRITE in perms else ["read"]
        found.append((str(role_id), actions))
    return found


def _seed_entity(
    conn: sa.Connection,
    entity_id: str,
    roles: list[tuple[str, list[str]]],
    now: datetime,
) -> None:
    attributes = _stamped_attributes(conn, entity_id, now)
    if not attributes:
        return
    profile_id = conn.execute(
        sa.text(
            "SELECT id FROM entity_access_profiles WHERE entity_id = :entity_id AND key = :key"
        ),
        {"entity_id": entity_id, "key": _ALL_CLEAR_KEY},
    ).scalar()
    if profile_id is None:
        profile_id = f"eap_{uuid.uuid4().hex[:12]}"
        columns = [
            {"attribute_id": item["attribute_id"], "level": "clear"} for item in attributes
        ]
        conn.execute(
            sa.text(
                "INSERT INTO entity_access_profiles "
                "(id, entity_id, key, name, description, columns, created_at, updated_at) "
                "VALUES (:id, :entity_id, :key, 'All clear', NULL, CAST(:columns AS jsonb), "
                ":now, :now)"
            ),
            {
                "id": profile_id,
                "entity_id": entity_id,
                "key": _ALL_CLEAR_KEY,
                "columns": json.dumps(columns),
                "now": now,
            },
        )
    inserted = False
    for role_id, actions in roles:
        exists = conn.execute(
            sa.text(
                "SELECT 1 FROM entity_access_grants WHERE entity_id = :entity_id "
                "AND subject_type = 'role' AND subject_id = :role_id AND profile_id = :profile_id"
            ),
            {"entity_id": entity_id, "role_id": role_id, "profile_id": profile_id},
        ).first()
        if exists is not None:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO entity_access_grants (id, entity_id, subject_type, subject_id, "
                "profile_id, row_rule, actions, status, valid_until, created_at, updated_at) "
                "VALUES (:id, :entity_id, 'role', :role_id, :profile_id, NULL, "
                "CAST(:actions AS jsonb), 'active', NULL, :now, :now)"
            ),
            {
                "id": f"eag_{uuid.uuid4().hex[:12]}",
                "entity_id": entity_id,
                "role_id": role_id,
                "profile_id": profile_id,
                "actions": json.dumps(actions),
                "now": now,
            },
        )
        inserted = True
    conn.execute(
        sa.text(
            "INSERT INTO entity_access_revisions (entity_id, revision, views_revision) "
            "VALUES (:entity_id, :bump, 0) "
            "ON CONFLICT (entity_id) DO UPDATE "
            "SET revision = entity_access_revisions.revision + :bump"
        ),
        {"entity_id": entity_id, "bump": 1 if inserted else 0},
    )


def _stamped_attributes(
    conn: sa.Connection, entity_id: str, now: datetime
) -> list[dict[str, Any]]:
    """Head attributes of the latest published version, stamping ids 0050 left unset."""
    row = conn.execute(
        sa.text(
            "SELECT id, attributes, materialized_attributes FROM entity_versions "
            "WHERE entity_id = :entity_id AND publish_status = 'published' "
            "ORDER BY version DESC LIMIT 1"
        ),
        {"entity_id": entity_id},
    ).first()
    if row is None:
        return []
    version_id, attributes, materialized = row
    raw = [dict(item) for item in (materialized or attributes or [])]
    changed = False
    for item in raw:
        if not isinstance(item.get("attribute_id"), str):
            name = str(item.get("name") or "")
            digest = hashlib.sha256(f"{entity_id}\n{name}".encode()).hexdigest()[:12]
            item["attribute_id"] = f"att_{digest}"
            changed = True
    if changed:
        ids = {item.get("name"): item["attribute_id"] for item in raw}
        stamped = [
            {**dict(item), "attribute_id": ids.get(item.get("name"), item.get("attribute_id"))}
            for item in (attributes or [])
        ]
        conn.execute(
            sa.text(
                "UPDATE entity_versions SET attributes = CAST(:attributes AS jsonb), "
                "materialized_attributes = CAST(:materialized AS jsonb), updated_at = :now "
                "WHERE id = :id"
            ),
            {
                "id": version_id,
                "attributes": json.dumps(stamped),
                "materialized": json.dumps(raw),
                "now": now,
            },
        )
    return [item for item in raw if isinstance(item.get("attribute_id"), str)]
