"""Retain compacted, typed CDC payload-byte interval evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0106_mirror_throughput"
down_revision = "0105_source_diagnostics"
branch_labels = None
depends_on = None


def upgrade():
    columns = []
    for metric in ("received", "committed"):
        columns.extend([
            sa.Column(metric + "_bytes", sa.BigInteger()),
            sa.Column(metric + "_seconds", sa.Float(), nullable=False),
            sa.Column(metric + "_intervals", sa.JSON(), nullable=False),
            *[sa.Column(metric + "_" + name, sa.DateTime(timezone=True)) for name in ("start", "end", "oldest", "newest")],
        ])
    op.create_table(
        "source_mirror_throughput",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("mirror_id", sa.String(64), sa.ForeignKey("source_mirrors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("capture_generation", sa.String(128), nullable=False),
        sa.Column("generation_id", sa.String(64), nullable=False),
        sa.Column("authority", sa.JSON(), nullable=False),
        sa.Column("bucket_at", sa.DateTime(timezone=True), nullable=False),
        *columns,
    )
    op.create_index("ix_mirror_throughput_scope_time", "source_mirror_throughput", ["source_id", "bucket_at"])
    op.create_index("ix_mirror_throughput_mirror_time", "source_mirror_throughput", ["mirror_id", "bucket_at"])
    op.create_index("ix_mirror_throughput_time", "source_mirror_throughput", ["bucket_at"])


def downgrade():
    op.drop_table("source_mirror_throughput")
