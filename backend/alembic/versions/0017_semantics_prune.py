"""Drop pruned object semantics columns (ADR 0015).

Revision ID: 0017_semantics_prune
Revises: 0016_join_graph
Create Date: 2026-08-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_semantics_prune"
down_revision: Union[str, None] = "0016_join_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("catalog_objects", "time_semantics_json")
    op.drop_column("catalog_objects", "status_semantics_json")
    op.drop_column("catalog_objects", "relation_summary_json")
    op.drop_column("catalog_objects", "confidence")


def downgrade() -> None:
    op.add_column(
        "catalog_objects",
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "catalog_objects",
        sa.Column("relation_summary_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "catalog_objects",
        sa.Column("status_semantics_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "catalog_objects",
        sa.Column("time_semantics_json", sa.Text(), nullable=True),
    )
