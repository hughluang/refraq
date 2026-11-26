"""Add call-tree linkage and return values for sub-channel runs and datasets."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0107_subchannel_runs"
down_revision = "0106_mirror_throughput"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "channel_runs",
        sa.Column("parent_job_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "channel_runs",
        sa.Column("root_job_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "channel_runs",
        sa.Column("return_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute("UPDATE channel_runs SET root_job_id = job_id WHERE root_job_id IS NULL")
    op.alter_column("channel_runs", "root_job_id", nullable=False)
    op.create_index(
        "ix_channel_runs_parent_job_id",
        "channel_runs",
        ["parent_job_id"],
    )
    op.create_index(
        "ix_channel_runs_root_job_id",
        "channel_runs",
        ["root_job_id"],
    )

    op.add_column(
        "channel_datasets",
        sa.Column("root_job_id", sa.String(64), nullable=True),
    )
    op.execute("UPDATE channel_datasets SET root_job_id = job_id WHERE root_job_id IS NULL")
    op.alter_column("channel_datasets", "root_job_id", nullable=False)
    op.create_index(
        "ix_channel_datasets_root_job_id",
        "channel_datasets",
        ["root_job_id"],
    )


def downgrade():
    op.drop_index("ix_channel_datasets_root_job_id", table_name="channel_datasets")
    op.drop_column("channel_datasets", "root_job_id")
    op.drop_index("ix_channel_runs_root_job_id", table_name="channel_runs")
    op.drop_index("ix_channel_runs_parent_job_id", table_name="channel_runs")
    op.drop_column("channel_runs", "return_value")
    op.drop_column("channel_runs", "root_job_id")
    op.drop_column("channel_runs", "parent_job_id")
