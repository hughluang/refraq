"""Business Entity definition and version tables.

Revision ID: 0041_business_entities
Revises: 0040_catalog_embeddings_vector
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0041_business_entities"
down_revision: Union[str, None] = "0040_catalog_embeddings_vector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "business_entities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("table_name", sa.String(48), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("table_name", name="uq_business_entities_table_name"),
    )
    op.create_index(
        "ix_business_entities_table_name", "business_entities", ["table_name"]
    )
    op.create_table(
        "entity_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("attributes", JSONB(), nullable=False),
        sa.Column("materialized_attributes", JSONB(), nullable=False),
        sa.Column("publish_status", sa.String(16), nullable=False),
        sa.Column("latest_reconcile_job_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["business_entities.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "entity_id", "version", name="uq_entity_versions_entity_version"
        ),
    )


def downgrade() -> None:
    op.drop_table("entity_versions")
    op.drop_index("ix_business_entities_table_name", table_name="business_entities")
    op.drop_table("business_entities")
