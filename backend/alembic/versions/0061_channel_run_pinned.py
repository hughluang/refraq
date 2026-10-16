"""Pinned outputs for on-demand channel runs.

Revision ID: 0061_channel_run_pinned
Revises: 0060_channel_run_context
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0061_channel_run_pinned"
down_revision: Union[str, None] = "0060_channel_run_context"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_column("channel_runs", "pinned")
