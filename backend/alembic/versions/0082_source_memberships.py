"""Source memberships and one-time Role reach seed.

Revision ID: 0082_source_memberships
Revises: 0081_channel_inbound_dedup

One-time data migration. Roles created later, including by a later Foundation
Upgrade, receive nothing. This revision is not invoked from core upgrade.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0082_source_memberships"
down_revision: Union[str, None] = "0081_channel_inbound_dedup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SUPER_ADMIN_KEY = "super_admin"
_EVERY_SOURCE_TARGET = "*"
_REACH_KEYS = frozenset({"sources:read", "metadata:read"})


def upgrade() -> None:
    op.create_table(
        "source_memberships",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subject_type",
            "subject_id",
            "target",
            name="uq_source_memberships_subject_target",
        ),
    )
    op.create_index(
        "ix_source_memberships_target",
        "source_memberships",
        ["target"],
    )
    _seed_role_reach(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_source_memberships_target", table_name="source_memberships")
    op.drop_table("source_memberships")


def _seed_role_reach(conn: sa.Connection) -> None:
    """Every-Source maintainer for Roles that store sources:read or metadata:read.

    ``super_admin`` is excluded by key. The stored permission list is read as
    stored; the System Role's effective catalog expansion is not applied.
    """
    now = datetime.now(timezone.utc)
    rows = conn.execute(sa.text("SELECT id, key, permissions FROM roles ORDER BY id"))
    for role_id, key, permissions in rows:
        if key == _SUPER_ADMIN_KEY:
            continue
        if _REACH_KEYS.isdisjoint(_permission_set(permissions)):
            continue
        role_key = str(role_id)
        exists = conn.execute(
            sa.text(
                "SELECT 1 FROM source_memberships "
                "WHERE subject_type = 'role' AND subject_id = :role_id AND target = :target"
            ),
            {"role_id": role_key, "target": _EVERY_SOURCE_TARGET},
        ).first()
        if exists is not None:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO source_memberships "
                "(id, subject_type, subject_id, target, level, created_at, updated_at) "
                "VALUES (:id, 'role', :role_id, :target, 'maintainer', :now, :now)"
            ),
            {
                "id": f"smb_{uuid.uuid4().hex[:12]}",
                "role_id": role_key,
                "target": _EVERY_SOURCE_TARGET,
                "now": now,
            },
        )


def _permission_set(value: object) -> set[str]:
    if not isinstance(value, (list, tuple)):
        return set()
    return {item for item in value if isinstance(item, str)}
