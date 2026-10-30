"""Channel checkpoints and the positions a run proposes.

Revision ID: 0077_channel_checkpoints
Revises: 0076_http_accounts
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0077_channel_checkpoints"
down_revision: Union[str, None] = "0076_http_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_checkpoints",
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("stream", sa.String(length=64), nullable=False),
        sa.Column("position_xact", sa.BigInteger(), nullable=False),
        sa.Column("position_seq", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("channel_id", "node_id", "stream"),
    )
    op.add_column(
        "channel_runs",
        sa.Column("checkpoint_proposals", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_runs", "checkpoint_proposals")
    op.drop_table("channel_checkpoints")
