"""Client read timeout on Model Service rows.

Revision ID: 0044_model_service_timeout
Revises: 0043_code_lists

Existing rows take the previous hard-coded client timeout of 30 seconds.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044_model_service_timeout"
down_revision: Union[str, None] = "0043_code_lists"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "model_services",
        sa.Column("timeout_sec", sa.Integer(), nullable=False, server_default="30"),
    )
    op.alter_column("model_services", "timeout_sec", server_default=None)


def downgrade() -> None:
    op.drop_column("model_services", "timeout_sec")
