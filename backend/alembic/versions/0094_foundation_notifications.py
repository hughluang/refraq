"""Persist encrypted Foundation routes and transactional notification outbox."""

from alembic import op
import sqlalchemy as sa

revision = "0094_foundation_notifications"
down_revision = "0093_source_capture_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("notification_channel",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("routes_ciphertext", sa.Text(), nullable=False),
        sa.Column("responder", sa.String(128), nullable=False),
        sa.Column("delivery_state", sa.JSON(), nullable=False),
        sa.Column("last_test_at", sa.DateTime(timezone=True)),
        sa.Column("last_fault_code", sa.String(64)),
        sa.Column("test_operation_id", sa.String(64)))
    op.create_table("notification_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("dedup_key", sa.String(64), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("channel_revision", sa.String(64)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("route", sa.String(16), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcomes", sa.JSON(), nullable=False),
        sa.Column("attempt_history", sa.JSON(), nullable=False),
        sa.Column("last_fault_code", sa.String(64)))
    op.create_index("ix_notification_events_next_attempt_at", "notification_events", ["next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_notification_events_next_attempt_at", table_name="notification_events")
    op.drop_table("notification_events")
    op.drop_table("notification_channel")
