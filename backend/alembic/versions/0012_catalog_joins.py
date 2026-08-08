"""Add catalog_joins for Slice C evidence-backed edges.

Revision ID: 0012_catalog_joins
Revises: 0011_encrypted_access_blob
Create Date: 2026-08-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_catalog_joins"
down_revision: Union[str, None] = "0011_encrypted_access_blob"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_joins",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("from_column_id", sa.String(length=64), nullable=False),
        sa.Column("to_column_id", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["from_column_id"], ["catalog_columns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["to_column_id"], ["catalog_columns.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "from_column_id",
            "to_column_id",
            name="uq_catalog_joins_from_to",
        ),
    )
    op.create_index(
        "ix_catalog_joins_from_column_id",
        "catalog_joins",
        ["from_column_id"],
    )
    op.create_index(
        "ix_catalog_joins_to_column_id",
        "catalog_joins",
        ["to_column_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_joins_to_column_id", table_name="catalog_joins")
    op.drop_index("ix_catalog_joins_from_column_id", table_name="catalog_joins")
    op.drop_table("catalog_joins")
