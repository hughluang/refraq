"""Persist recovery identity, modes, bounded retry budget and replacement intent."""

from alembic import op
import sqlalchemy as sa

revision = "0097_mirror_recovery"
down_revision = "0096_mirror_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_mirror_recoveries",
        sa.Column("operation_id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mirror_id", sa.String(64), sa.ForeignKey("source_mirrors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("identity", sa.String(64), nullable=False),
        sa.Column("journal", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_id", "identity", name="uq_mirror_recovery_identity"),
    )


def downgrade() -> None:
    op.drop_table("source_mirror_recoveries")
