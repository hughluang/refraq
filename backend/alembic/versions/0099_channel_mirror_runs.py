"""Persist separate mirror execution identity and protected run provenance."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0099_channel_mirror_runs"
down_revision = "0098_mirror_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_runs", sa.Column("mirror_execution_user_id", sa.String(64), nullable=True))
    op.add_column("channel_runs", sa.Column("mirror_state", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("channel_runs", "mirror_state")
    op.drop_column("channel_runs", "mirror_execution_user_id")
