"""Model Services registry and embedding generation.

Revision ID: 0038_model_services
Revises: 0037_semantics_change_embed
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038_model_services"
down_revision: Union[str, None] = "0037_semantics_change_embed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_services",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("protocol", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_services_purpose", "model_services", ["purpose"])
    op.create_table(
        "model_service_purposes",
        sa.Column("purpose", sa.String(length=32), primary_key=True),
        sa.Column("in_use_id", sa.String(length=64), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["in_use_id"],
            ["model_services.id"],
            ondelete="SET NULL",
        ),
    )
    op.add_column(
        "catalog_embeddings",
        sa.Column(
            "generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("catalog_embeddings", "generation")
    op.drop_table("model_service_purposes")
    op.drop_index("ix_model_services_purpose", table_name="model_services")
    op.drop_table("model_services")
