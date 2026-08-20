"""Join Rejection columns on catalog_joins.

Revision ID: 0031_join_rejection
Revises: 0030_system_parameters
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_join_rejection"
down_revision: Union[str, None] = "0030_system_parameters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalog_joins",
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "catalog_joins",
        sa.Column("rejected_by_user_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("catalog_joins", "rejected_by_user_id")
    op.drop_column("catalog_joins", "rejected_at")
