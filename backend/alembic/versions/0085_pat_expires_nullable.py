"""Allow a User PAT to have no expiry.

Revision ID: 0085_pat_expires_nullable
Revises: 0084_commit_order_cursors

``user_pats.expires_at`` null means the token does not expire.
Downgrade restores NOT NULL and fails when a null row exists.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0085_pat_expires_nullable"
down_revision: Union[str, None] = "0084_commit_order_cursors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "user_pats",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "user_pats",
        "expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
