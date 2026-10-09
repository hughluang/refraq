"""Data Channel definition tables.

Revision ID: 0055_channel_definitions
Revises: 0054_entity_access_seed
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055_channel_definitions"
down_revision: Union[str, None] = "0054_entity_access_seed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("draft_graph", postgresql.JSONB(), nullable=False),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_channels_created_at", "channels", ["created_at"])
    op.create_table(
        "channel_versions",
        sa.Column(
            "channel_id",
            sa.String(64),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("graph", postgresql.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by_user_id", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("channel_versions")
    op.drop_index("ix_channels_created_at", table_name="channels")
    op.drop_table("channels")
