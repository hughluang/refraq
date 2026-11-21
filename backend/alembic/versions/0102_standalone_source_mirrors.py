"""Retire the unpublished Channel integration with Source Mirrors."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0102_standalone_source_mirrors"
down_revision = "0101_channel_pin_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("source_mirror_intent_receipts")
    op.drop_table("source_mirror_publications")
    op.drop_table("source_mirror_references")

    op.drop_column("channel_runs", "pending_pin_mirror_id")
    op.drop_column("channel_runs", "mirror_pin_state")
    op.drop_column("channel_runs", "mirror_state")
    op.drop_column("channel_runs", "mirror_execution_user_id")

    op.execute("DELETE FROM channel_checkpoints WHERE stream_kind = 'mirror'")
    op.drop_column("channel_checkpoints", "source_ids")
    op.drop_column("channel_checkpoints", "history_epoch")
    op.drop_column("channel_checkpoints", "stream_kind")

    op.execute("""
        UPDATE source_mirror_recoveries
        SET journal = jsonb_set(journal::jsonb, '{state}', '"superseded"')::json
        WHERE journal #>> '{request,action}' = 'reconcile_state'
    """)


def downgrade() -> None:
    op.add_column("channel_checkpoints", sa.Column("stream_kind", sa.String(16), nullable=False, server_default="entity"))
    op.add_column("channel_checkpoints", sa.Column("history_epoch", sa.String(64), nullable=True))
    op.add_column("channel_checkpoints", sa.Column("source_ids", postgresql.JSONB(), nullable=True))

    op.add_column("channel_runs", sa.Column("mirror_execution_user_id", sa.String(64), nullable=True))
    op.add_column("channel_runs", sa.Column("mirror_state", postgresql.JSONB(), nullable=True))
    op.add_column("channel_runs", sa.Column("mirror_pin_state", sa.String(16), nullable=True))
    op.add_column("channel_runs", sa.Column("pending_pin_mirror_id", sa.String(64), nullable=True))

    op.create_table(
        "source_mirror_references",
        sa.Column("channel_id", sa.String(64), primary_key=True),
        sa.Column("mirror_id", sa.String(64), sa.ForeignKey("source_mirrors.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("channel_version", sa.Integer(), nullable=False),
    )
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
