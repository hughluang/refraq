"""Published inbound path registry.

Revision ID: 0079_channel_inbound_paths
Revises: 0078_inbound_credentials
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0079_channel_inbound_paths"
down_revision: Union[str, None] = "0078_inbound_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_inbound_paths",
        sa.Column("path", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("path"),
    )
    op.create_index(
        "ix_channel_inbound_paths_channel_id",
        "channel_inbound_paths",
        ["channel_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_inbound_paths_channel_id", "channel_inbound_paths"
    )
    op.drop_table("channel_inbound_paths")
