"""Draft change-log switch and retention on entity versions.

Revision ID: 0074_entity_version_change_log
Revises: 0073_channel_owned_variables

Existing versions stay off and never-expire. Null retention is never-expire.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0074_entity_version_change_log"
down_revision: Union[str, None] = "0073_channel_owned_variables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_versions",
        sa.Column(
            "change_log_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("entity_versions", "change_log_enabled", server_default=None)
    op.add_column(
        "entity_versions",
        sa.Column("change_log_retention_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("entity_versions", "change_log_retention_days")
    op.drop_column("entity_versions", "change_log_enabled")
