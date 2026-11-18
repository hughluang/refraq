"""Persist management history gates and recoverable target invalidation intent."""

from alembic import op
import sqlalchemy as sa

revision = "0096_mirror_history"
down_revision = "0095_mirror_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_mirror_history_gates",
        sa.Column("mirror_id", sa.String(64), sa.ForeignKey("source_mirrors.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("history_epoch", sa.String(64), nullable=False),
        sa.Column("lower_commit_seq", sa.BigInteger(), nullable=False),
        sa.Column("lower_entry_seq", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.CheckConstraint("status IN ('available', 'invalidating')"),
        sa.CheckConstraint("lower_commit_seq >= 0 AND lower_entry_seq >= 0"),
    )
    op.create_table(
        "source_mirror_history_invalidations",
        sa.Column("operation_id", sa.String(64), primary_key=True),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("transitions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("source_mirror_history_invalidations")
    op.drop_table("source_mirror_history_gates")
