"""Persist mirror registry, live references, receipts and command outbox."""

from alembic import op
import sqlalchemy as sa

revision = "0095_mirror_management"
down_revision = "0094_foundation_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_mirrors",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("table_identity", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_id", "table_identity", name="uq_source_mirror_binding"),
    )
    op.create_table(
        "source_mirror_references",
        sa.Column("channel_id", sa.String(64), primary_key=True),
        sa.Column("mirror_id", sa.String(64), sa.ForeignKey("source_mirrors.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("channel_version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "source_mirror_operations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("mirror_id", sa.String(64), sa.ForeignKey("source_mirrors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("command", sa.JSON(), nullable=False),
    )
    op.create_index("ix_source_mirror_operations_mirror_id", "source_mirror_operations", ["mirror_id"])
    op.create_table(
        "source_mirror_publications",
        sa.Column("channel_id", sa.String(64), primary_key=True),
        sa.Column("channel_version", sa.Integer(), nullable=False),
        sa.Column("object_ids", sa.JSON(), nullable=False),
    )
    op.create_table(
        "source_mirror_intent_receipts",
        sa.Column("operation_id", sa.String(64), primary_key=True),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("source_mirror_intent_receipts")
    op.drop_table("source_mirror_publications")
    op.drop_index("ix_source_mirror_operations_mirror_id", table_name="source_mirror_operations")
    op.drop_table("source_mirror_operations")
    op.drop_table("source_mirror_references")
    op.drop_table("source_mirrors")
