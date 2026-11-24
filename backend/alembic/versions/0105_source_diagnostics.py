"""Persist bounded, redacted Source and runtime diagnostic observations."""

import sqlalchemy as sa
from alembic import op

revision = "0105_source_diagnostics"
down_revision = "0104_mirror_effective_status"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_mirror_diagnostics",
        sa.Column("id", sa.String(256), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("scope_id", sa.String(128), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
    )
    op.create_index("ix_source_mirror_diagnostics_kind", "source_mirror_diagnostics", ["kind"])
    op.create_index("ix_source_mirror_diagnostics_scope_id", "source_mirror_diagnostics", ["scope_id"])


def downgrade():
    op.drop_table("source_mirror_diagnostics")
