"""Drop pinned outputs from channel runs.

Revision ID: 0062_drop_channel_run_pinned
Revises: 0061_channel_run_pinned
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0062_drop_channel_run_pinned"
down_revision: Union[str, None] = "0061_channel_run_pinned"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM channel_node_executions WHERE status = 'pinned'")
    op.drop_column("channel_runs", "pinned")
    op.execute(
        "UPDATE jobs SET input = input - 'pinned' "
        "WHERE kind = 'channel_run' AND input ? 'pinned'"
    )


def downgrade() -> None:
    op.add_column(
        "channel_runs",
        sa.Column(
            "pinned",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("channel_runs", "pinned", server_default=None)
