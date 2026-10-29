"""Site-wide HTTP Account catalog.

Revision ID: 0076_http_accounts
Revises: 0075_entity_change_log_policy
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0076_http_accounts"
down_revision: Union[str, None] = "0075_entity_change_log_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "http_accounts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("auth_type", sa.String(length=16), nullable=False),
        sa.Column("username", sa.String(length=256), nullable=True),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("headers_ciphertext", sa.Text(), nullable=False),
        sa.Column("query_ciphertext", sa.Text(), nullable=False),
        sa.Column("allowed_origins", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("http_accounts")
