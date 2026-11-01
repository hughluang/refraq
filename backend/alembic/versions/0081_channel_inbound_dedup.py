"""Inbound event dedup records and per-channel hit counts.

Revision ID: 0081_channel_inbound_dedup
Revises: 0080_channel_inbound_rejections
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0081_channel_inbound_dedup"
down_revision: Union[str, None] = "0080_channel_inbound_rejections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_inbound_dedup",
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("headers", postgresql.JSONB(), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("channel_id", "path", "event_id"),
    )
    op.create_index(
        "ix_channel_inbound_dedup_expires_at",
        "channel_inbound_dedup",
        ["expires_at"],
    )
    op.create_index(
        "ix_channel_inbound_dedup_job_id",
        "channel_inbound_dedup",
        ["job_id"],
    )
    op.create_table(
        "channel_inbound_dedup_hits",
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("channel_id"),
    )


def downgrade() -> None:
    op.drop_table("channel_inbound_dedup_hits")
    op.drop_index("ix_channel_inbound_dedup_job_id", "channel_inbound_dedup")
    op.drop_index("ix_channel_inbound_dedup_expires_at", "channel_inbound_dedup")
    op.drop_table("channel_inbound_dedup")
