"""Add join_kind, join_expression, origin on catalog_joins.

Revision ID: 0016_join_graph
Revises: 0015_semantics_depth
Create Date: 2026-08-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_join_graph"
down_revision: Union[str, None] = "0015_semantics_depth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalog_joins",
        sa.Column(
            "join_kind",
            sa.String(length=32),
            nullable=False,
            server_default="INNER",
        ),
    )
    op.add_column(
        "catalog_joins", sa.Column("join_expression", sa.Text(), nullable=True)
    )
    op.add_column(
        "catalog_joins",
        sa.Column(
            "origin",
            sa.String(length=32),
            nullable=False,
            server_default="human",
        ),
    )
    op.alter_column(
        "catalog_joins",
        "join_kind",
        server_default=None,
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "catalog_joins",
        "origin",
        server_default=None,
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.drop_column("catalog_joins", "origin")
    op.drop_column("catalog_joins", "join_expression")
    op.drop_column("catalog_joins", "join_kind")
