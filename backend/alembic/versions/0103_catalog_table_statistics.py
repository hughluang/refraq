"""Store the latest collected PostgreSQL table statistics."""

import sqlalchemy as sa
from alembic import op

revision = "0103_catalog_table_statistics"
down_revision = "0102_standalone_source_mirrors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("catalog_objects", sa.Column("source_size_bytes", sa.BigInteger()))
    op.add_column("catalog_objects", sa.Column("estimated_rows", sa.BigInteger()))


def downgrade() -> None:
    op.drop_column("catalog_objects", "estimated_rows")
    op.drop_column("catalog_objects", "source_size_bytes")
