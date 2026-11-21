"""Track target pin release independently of retained Channel provenance."""

from alembic import op
import sqlalchemy as sa


revision = "0101_channel_pin_retention"
down_revision = "0100_mirror_references"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channel_runs", sa.Column("mirror_pin_state", sa.String(16), nullable=True))
    op.add_column("channel_runs", sa.Column("pending_pin_mirror_id", sa.String(64), nullable=True))
    op.execute("""
        UPDATE channel_runs SET mirror_pin_state = CASE
            WHEN jsonb_typeof(mirror_state->'pins') = 'object'
                AND mirror_state->'pins' <> '{}'::jsonb THEN 'held'
            WHEN mirror_execution_user_id IS NULL
                AND (mirror_state IS NULL OR mirror_state = 'null'::jsonb)
                AND NOT COALESCE(graph->'nodes' @> '[{"type":"read.mirror"}]'::jsonb, false)
                THEN 'unused'
            WHEN jsonb_typeof(graph->'nodes') = 'array'
                AND NOT (graph->'nodes' @> '[{"type":"read.mirror"}]'::jsonb)
                AND (mirror_state->'history_bounds' IS NOT NULL
                     OR mirror_state->'inherited_source_ids' IS NOT NULL)
                AND mirror_state->'pins' IS NULL THEN 'unused'
        END
    """)


def downgrade() -> None:
    op.drop_column("channel_runs", "pending_pin_mirror_id")
    op.drop_column("channel_runs", "mirror_pin_state")
