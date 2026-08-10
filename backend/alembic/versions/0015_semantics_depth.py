"""Add full object/column semantics depth columns.

Revision ID: 0015_semantics_depth
Revises: 0014_structure_depth
Create Date: 2026-08-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_semantics_depth"
down_revision: Union[str, None] = "0014_structure_depth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalog_objects",
        sa.Column("object_category", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "catalog_objects", sa.Column("grain_description", sa.Text(), nullable=True)
    )
    op.add_column(
        "catalog_objects",
        sa.Column("business_primary_key_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "catalog_objects", sa.Column("time_semantics_json", sa.Text(), nullable=True)
    )
    op.add_column(
        "catalog_objects", sa.Column("status_semantics_json", sa.Text(), nullable=True)
    )
    op.add_column(
        "catalog_objects",
        sa.Column("relation_summary_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "catalog_objects",
        sa.Column("business_domain", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "catalog_objects",
        sa.Column("evidence_summary_json", sa.Text(), nullable=True),
    )
    op.add_column("catalog_objects", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column(
        "catalog_objects", sa.Column("open_questions_json", sa.Text(), nullable=True)
    )
    op.add_column(
        "catalog_objects",
        sa.Column("semantic_source", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "catalog_objects",
        sa.Column(
            "business_semantics_ready",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "catalog_objects",
        sa.Column("semantics_updated_at", sa.DateTime(), nullable=True),
    )

    op.add_column(
        "catalog_columns",
        sa.Column("column_semantics_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "catalog_columns", sa.Column("enum_catalog_json", sa.Text(), nullable=True)
    )
    op.add_column(
        "catalog_columns",
        sa.Column("semantic_source", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "catalog_columns",
        sa.Column(
            "field_kind",
            sa.String(length=64),
            nullable=False,
            server_default="column",
        ),
    )

    # Drop server defaults after backfill so ORM owns defaults going forward.
    op.alter_column(
        "catalog_objects",
        "business_semantics_ready",
        server_default=None,
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )
    op.alter_column(
        "catalog_columns",
        "field_kind",
        server_default=None,
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.drop_column("catalog_columns", "field_kind")
    op.drop_column("catalog_columns", "semantic_source")
    op.drop_column("catalog_columns", "enum_catalog_json")
    op.drop_column("catalog_columns", "column_semantics_json")
    op.drop_column("catalog_objects", "semantics_updated_at")
    op.drop_column("catalog_objects", "business_semantics_ready")
    op.drop_column("catalog_objects", "semantic_source")
    op.drop_column("catalog_objects", "open_questions_json")
    op.drop_column("catalog_objects", "confidence")
    op.drop_column("catalog_objects", "evidence_summary_json")
    op.drop_column("catalog_objects", "business_domain")
    op.drop_column("catalog_objects", "relation_summary_json")
    op.drop_column("catalog_objects", "status_semantics_json")
    op.drop_column("catalog_objects", "time_semantics_json")
    op.drop_column("catalog_objects", "business_primary_key_json")
    op.drop_column("catalog_objects", "grain_description")
    op.drop_column("catalog_objects", "object_category")
