"""Add SQL statement fields to the Entity Access Log.

Revision ID: 0086_access_log_sql_fields
Revises: 0085_pat_expires_nullable

``sql_sha256`` and ``statement_summary`` are null for every verb other than sql.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0086_access_log_sql_fields"
down_revision: Union[str, None] = "0085_pat_expires_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_access_logs",
        sa.Column("sql_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "entity_access_logs",
        sa.Column("statement_summary", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("entity_access_logs", "statement_summary")
    op.drop_column("entity_access_logs", "sql_sha256")
