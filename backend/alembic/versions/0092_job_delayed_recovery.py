"""Record delayed cron recovery provenance on Jobs."""

from alembic import op
import sqlalchemy as sa

revision = "0092_job_delayed_recovery"
down_revision = "0091_source_capture_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("is_delayed_recovery", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("jobs", "is_delayed_recovery", server_default=None)


def downgrade() -> None:
    op.drop_column("jobs", "is_delayed_recovery")
