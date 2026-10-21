"""Count published failure episodes on a channel.

Revision ID: 0063_channel_failure_streak
Revises: 0062_drop_channel_run_pinned
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0063_channel_failure_streak"
down_revision: Union[str, None] = "0062_drop_channel_run_pinned"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("failure_streak", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("channels", "failure_streak")
