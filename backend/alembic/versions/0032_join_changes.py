"""Join Change ledger; drop catalog_joins.origin after backfill.

Revision ID: 0032_join_changes
Revises: 0031_join_rejection
Create Date: 2026-08-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_join_changes"
down_revision: Union[str, None] = "0031_join_rejection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_join_changes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("from_column_id", sa.String(length=64), nullable=False),
        sa.Column("to_column_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("attester", sa.String(length=32), nullable=True),
        sa.Column("actor_user_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_catalog_join_changes_from_to",
        "catalog_join_changes",
        ["from_column_id", "to_column_id"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO catalog_join_changes (
                id, from_column_id, to_column_id, kind, attester,
                actor_user_id, created_at
            )
            SELECT
                'jch_' || substr(id, 6),
                from_column_id,
                to_column_id,
                'create',
                origin,
                created_by_user_id,
                created_at
            FROM catalog_joins
            """
        )
    )
    op.drop_column("catalog_joins", "origin")


def downgrade() -> None:
    op.add_column(
        "catalog_joins",
        sa.Column(
            "origin",
            sa.String(length=32),
            nullable=False,
            server_default="human",
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE catalog_joins AS j
            SET origin = c.attester
            FROM catalog_join_changes AS c
            WHERE c.from_column_id = j.from_column_id
              AND c.to_column_id = j.to_column_id
              AND c.kind = 'create'
              AND c.attester IS NOT NULL
            """
        )
    )
    op.alter_column("catalog_joins", "origin", server_default=None)
    op.drop_index(
        "ix_catalog_join_changes_from_to", table_name="catalog_join_changes"
    )
    op.drop_table("catalog_join_changes")
