"""Channel dataset registry.

Revision ID: 0066_channel_datasets
Revises: 0065_email_accounts
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0066_channel_datasets"
down_revision: Union[str, None] = "0065_email_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_datasets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('loading', 'ready', 'dropped')",
            name="ck_channel_datasets_status",
        ),
    )
    op.create_index("ix_channel_datasets_job_id", "channel_datasets", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_channel_datasets_job_id", table_name="channel_datasets")
    op.drop_table("channel_datasets")
