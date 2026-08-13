"""Job result, Normalized Type, and Structure Diff.

Revision ID: 0024_structure_diff_job_result
Revises: 0023_user_display_timezone
Create Date: 2026-08-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_structure_diff_job_result"
down_revision: Union[str, None] = "0023_user_display_timezone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column(
        "catalog_columns",
        sa.Column("normalized_type", sa.String(length=32), nullable=True),
    )
    op.create_table(
        "structure_diffs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("class", sa.String(length=32), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("job_id", name="uq_structure_diffs_job_id"),
    )
    op.create_index(
        "ix_structure_diffs_source_id", "structure_diffs", ["source_id"]
    )
    op.create_index("ix_structure_diffs_job_id", "structure_diffs", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_structure_diffs_job_id", table_name="structure_diffs")
    op.drop_index("ix_structure_diffs_source_id", table_name="structure_diffs")
    op.drop_table("structure_diffs")
    op.drop_column("catalog_columns", "normalized_type")
    op.drop_column("jobs", "result")
