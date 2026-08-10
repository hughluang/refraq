"""Add structure depth fields: comments, defaults, PK, FKs, indexes.

Revision ID: 0014_structure_depth
Revises: 0013_locator_keys
Create Date: 2026-08-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_structure_depth"
down_revision: Union[str, None] = "0013_locator_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("catalog_objects", sa.Column("comment", sa.Text(), nullable=True))
    op.add_column(
        "catalog_objects", sa.Column("primary_key_json", sa.Text(), nullable=True)
    )
    op.add_column("catalog_columns", sa.Column("default_value", sa.Text(), nullable=True))
    op.add_column("catalog_columns", sa.Column("comment", sa.Text(), nullable=True))

    op.create_table(
        "catalog_foreign_keys",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("columns_json", sa.Text(), nullable=False),
        sa.Column("ref_schema", sa.String(length=256), nullable=False),
        sa.Column("ref_table", sa.String(length=256), nullable=False),
        sa.Column("ref_columns_json", sa.Text(), nullable=False),
        sa.Column("is_present", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_id"], ["catalog_objects.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_catalog_foreign_keys_object_id",
        "catalog_foreign_keys",
        ["object_id"],
    )

    op.create_table(
        "catalog_indexes",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("columns_json", sa.Text(), nullable=False),
        sa.Column("is_unique", sa.Boolean(), nullable=False),
        sa.Column("is_present", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["object_id"], ["catalog_objects.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_catalog_indexes_object_id",
        "catalog_indexes",
        ["object_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_indexes_object_id", table_name="catalog_indexes")
    op.drop_table("catalog_indexes")
    op.drop_index(
        "ix_catalog_foreign_keys_object_id", table_name="catalog_foreign_keys"
    )
    op.drop_table("catalog_foreign_keys")
    op.drop_column("catalog_columns", "comment")
    op.drop_column("catalog_columns", "default_value")
    op.drop_column("catalog_objects", "primary_key_json")
    op.drop_column("catalog_objects", "comment")
