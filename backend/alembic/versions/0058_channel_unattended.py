"""Channel run stop node and global variables.

Revision ID: 0058_channel_unattended
Revises: 0057_channel_runs
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058_channel_unattended"
down_revision: Union[str, None] = "0057_channel_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_runs",
        sa.Column("stopped_node_id", sa.String(64), nullable=True),
    )
    op.create_table(
        "channel_variables",
        sa.Column("name", sa.String(128), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("channel_variables")
    op.drop_column("channel_runs", "stopped_node_id")
