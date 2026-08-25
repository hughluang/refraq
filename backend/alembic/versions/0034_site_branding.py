"""Add site branding and branding assets.

Revision ID: 0034_site_branding
Revises: 0033_federation
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034_site_branding"
down_revision: Union[str, None] = "0033_federation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "site_branding_assets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.LargeBinary(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('logo', 'favicon')", name="ck_branding_asset_kind"
        ),
        sa.UniqueConstraint("kind", name="uq_site_branding_assets_kind"),
    )
    op.create_table(
        "site_branding",
        sa.Column("id", sa.String(length=16), primary_key=True),
        sa.Column(
            "brand_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "taglines",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("primary_color", sa.String(length=7), nullable=True),
        sa.Column(
            "primary_shades",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "show_brand_name_with_logo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=64), nullable=True),
        sa.CheckConstraint("id = 'site'", name="ck_site_branding_singleton"),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )


def downgrade() -> None:
    op.drop_table("site_branding")
    op.drop_table("site_branding_assets")
