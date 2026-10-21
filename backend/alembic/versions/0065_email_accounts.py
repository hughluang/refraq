"""Site-wide Email Account catalog.

Revision ID: 0065_email_accounts
Revises: 0064_webhooks
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0065_email_accounts"
down_revision: Union[str, None] = "0064_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_accounts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("encryption", sa.String(length=16), nullable=False),
        sa.Column("username", sa.String(length=200), nullable=True),
        sa.Column("password_ciphertext", sa.Text(), nullable=True),
        sa.Column("from_address", sa.String(length=254), nullable=False),
        sa.Column("tls_skip_verify", sa.Boolean(), nullable=False),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_ok", sa.Boolean(), nullable=True),
        sa.Column("last_delivery_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("email_accounts")
