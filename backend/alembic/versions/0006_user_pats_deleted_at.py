"""Add user_pats.deleted_at for soft-delete.

Revision ID: 0006_user_pats_deleted_at
Revises: 0005_user_email_locale
Create Date: 2026-08-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_user_pats_deleted_at"
down_revision: Union[str, None] = "0005_user_email_locale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_pats",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_pats", "deleted_at")
