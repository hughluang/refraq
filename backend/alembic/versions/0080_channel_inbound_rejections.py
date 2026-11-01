"""Refused inbound requests.

Revision ID: 0080_channel_inbound_rejections
Revises: 0079_channel_inbound_paths
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0080_channel_inbound_rejections"
down_revision: Union[str, None] = "0079_channel_inbound_paths"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_inbound_rejections",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("headers", postgresql.JSONB(), nullable=False),
        sa.Column("query", postgresql.JSONB(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_channel_inbound_rejections_channel_id",
        "channel_inbound_rejections",
        ["channel_id"],
    )
    op.create_index(
        "ix_channel_inbound_rejections_received_at",
        "channel_inbound_rejections",
        ["received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_inbound_rejections_received_at",
        "channel_inbound_rejections",
    )
    op.drop_index(
        "ix_channel_inbound_rejections_channel_id",
        "channel_inbound_rejections",
    )
    op.drop_table("channel_inbound_rejections")
