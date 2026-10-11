"""System identity user and locked access grants.

Revision ID: 0056_system_identity
Revises: 0055_channel_definitions
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056_system_identity"
down_revision: Union[str, None] = "0055_channel_definitions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_access_grants",
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        INSERT INTO users (
            id, account, display_name, locale, status, identity_source, created_at
        )
        SELECT 'usr_system', 'system', 'System', 'en-US', 'active', 'system', NOW()
        WHERE NOT EXISTS (SELECT 1 FROM users WHERE id = 'usr_system')
        """
    )
    op.execute(
        """
        INSERT INTO entity_access_grants (
            id, entity_id, subject_type, subject_id, profile_id, row_rule,
            actions, status, locked, valid_until, created_at, updated_at
        )
        SELECT
            'eag_sys_' || substr(md5(p.entity_id), 1, 12),
            p.entity_id,
            'user',
            'usr_system',
            p.id,
            NULL,
            '["read", "export", "write"]'::jsonb,
            'active',
            true,
            NULL,
            NOW(),
            NOW()
        FROM entity_access_profiles p
        WHERE p.key = 'all_clear'
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM entity_access_grants WHERE subject_id = 'usr_system' AND locked")
    op.execute("DELETE FROM users WHERE id = 'usr_system'")
    op.drop_column("entity_access_grants", "locked")
