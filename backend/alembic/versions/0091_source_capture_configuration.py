"""Separate encrypted Source capture configuration.

Revision ID: 0091_source_capture_config
Revises: 0090_entity_index_state
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from backend.core.time import UtcDateTime

revision = "0091_source_capture_config"
down_revision = "0090_entity_index_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sources", sa.Column("capture_credential_ciphertext", sa.Text(), nullable=True)
    )
    op.add_column(
        "sources",
        sa.Column("capture_credential_updated_at", UtcDateTime(), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("capture_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("sources", "capture_revision", server_default=None)
    op.add_column(
        "sources", sa.Column("snapshot_window", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sources", "snapshot_window")
    op.drop_column("sources", "capture_revision")
    op.drop_column("sources", "capture_credential_updated_at")
    op.drop_column("sources", "capture_credential_ciphertext")
