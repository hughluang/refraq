"""Retire Business Domain (ADR 0064).

Revision ID: 0068_retire_business_domain
Revises: 0067_execution_container
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0068_retire_business_domain"
down_revision: Union[str, None] = "0067_execution_container"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM catalog_semantics_changes "
            "WHERE field_name = 'business_domain_id'"
        )
    )
    op.execute(
        sa.text("DELETE FROM audit_events WHERE resource_type = 'business_domain'")
    )
    op.drop_constraint(
        "fk_catalog_objects_business_domain_id",
        "catalog_objects",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_catalog_objects_business_domain_id",
        table_name="catalog_objects",
    )
    op.drop_column("catalog_objects", "business_domain_id")
    op.drop_index("ix_business_domains_code", table_name="business_domains")
    op.drop_table("business_domains")


def downgrade() -> None:
    op.create_table(
        "business_domains",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_business_domains_code"),
    )
    op.create_index("ix_business_domains_code", "business_domains", ["code"])
    op.add_column(
        "catalog_objects",
        sa.Column("business_domain_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_catalog_objects_business_domain_id",
        "catalog_objects",
        ["business_domain_id"],
    )
    op.create_foreign_key(
        "fk_catalog_objects_business_domain_id",
        "catalog_objects",
        "business_domains",
        ["business_domain_id"],
        ["id"],
        ondelete="RESTRICT",
    )
