"""Add independent mirror lineage to existing Channel checkpoints."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0098_mirror_checkpoints"
down_revision = "0097_mirror_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_checkpoints", sa.Column("stream_kind", sa.String(16), nullable=False, server_default="entity"))
    op.add_column("channel_checkpoints", sa.Column("history_epoch", sa.String(64), nullable=True))
    op.add_column("channel_checkpoints", sa.Column("source_ids", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("channel_checkpoints", "source_ids")
    op.drop_column("channel_checkpoints", "history_epoch")
    op.drop_column("channel_checkpoints", "stream_kind")
