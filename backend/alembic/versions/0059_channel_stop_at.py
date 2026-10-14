"""Optional stop node on a channel run.

Revision ID: 0059_channel_stop_at
Revises: 0058_channel_unattended
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0059_channel_stop_at"
down_revision: Union[str, None] = "0058_channel_unattended"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_runs",
        sa.Column("stop_at_node_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_runs", "stop_at_node_id")
