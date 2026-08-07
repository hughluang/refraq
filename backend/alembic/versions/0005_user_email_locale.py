"""Add users.email and users.locale for Account Center.

Revision ID: 0005_user_email_locale
Revises: 0004_sources_catalog
Create Date: 2026-08-06
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_user_email_locale"
down_revision: Union[str, None] = "0004_sources_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=256), nullable=True))
    op.add_column(
        "users",
        sa.Column("locale", sa.String(length=16), nullable=False, server_default="en-US"),
    )
    op.alter_column("users", "locale", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "locale")
    op.drop_column("users", "email")
