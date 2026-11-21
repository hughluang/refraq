"""Restore live Channel history references and current Mirror open intents."""

from alembic import op

revision = "0100_mirror_references"
down_revision = "0099_channel_mirror_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        WITH latest AS (
            SELECT DISTINCT ON (v.channel_id) v.channel_id, v.number, v.graph
            FROM channel_versions AS v JOIN channels AS ch ON ch.id = v.channel_id
            ORDER BY v.channel_id, v.number DESC
        )
        INSERT INTO source_mirror_references (channel_id, mirror_id, channel_version)
        SELECT DISTINCT c.channel_id, m.id, c.number
        FROM latest AS c
        CROSS JOIN LATERAL jsonb_array_elements(c.graph->'nodes') AS node
        JOIN source_mirrors AS m ON m.id = node #>> '{config,source,mirror_id}'
        WHERE node->>'type' IN ('read.changes', 'volume.changes_dataset')
          AND node #>> '{config,source,kind}' = 'mirror'
        ON CONFLICT (channel_id, mirror_id) DO UPDATE SET channel_version = EXCLUDED.channel_version
    """)
    op.execute("""
        UPDATE source_mirror_operations AS op
        SET command = jsonb_set(op.command::jsonb, '{kind}', '"open"')::json
        FROM source_mirrors AS m
        WHERE op.mirror_id = m.id AND m.enabled
          AND op.command->>'kind' = 'enable' AND op.command->>'state' = 'pending'
          AND op.command->>'control_revision' = m.state #>> '{control,control_revision}'
    """)


def downgrade() -> None:
    # The preceding schema supports the restored references and open intents.
    pass
