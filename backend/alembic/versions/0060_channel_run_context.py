"""Expression Context a channel run evaluated with.

Revision ID: 0060_channel_run_context
Revises: 0059_channel_stop_at
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060_channel_run_context"
down_revision: Union[str, None] = "0059_channel_stop_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_runs",
        sa.Column("context", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_runs", "context")
