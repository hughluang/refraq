"""Add site_branding.show_logo display choice.

Revision ID: 0035_branding_show_logo
Revises: 0034_site_branding
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035_branding_show_logo"
down_revision: Union[str, None] = "0034_site_branding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "site_branding",
        sa.Column(
            "show_logo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("site_branding", "show_logo")
