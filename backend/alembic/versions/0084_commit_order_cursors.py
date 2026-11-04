"""Epoch row for the change-log cursor rewrite.

Revision ID: 0084_commit_order_cursors
Revises: 0083_access_stamp

The entity database numbers existing entries. The first persistent checkpoint
read rewrites ``channel_checkpoints`` and clears in-flight proposals. This
table records that the rewrite has happened. Downgrade drops the row and does
not restore the old cursors.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0084_commit_order_cursors"
down_revision: Union[str, None] = "0083_access_stamp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "change_log_cursor_epoch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("adopted", sa.Boolean(), nullable=False),
    )
    op.execute("INSERT INTO change_log_cursor_epoch (id, adopted) VALUES (1, false)")


def downgrade() -> None:
    op.drop_table("change_log_cursor_epoch")
