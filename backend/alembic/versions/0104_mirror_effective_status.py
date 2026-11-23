"""Index the evidence-derived Mirror lifecycle used by offset pagination."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from backend.metadata.mirrors.status_projection import refresh_source_status

revision = "0104_mirror_effective_status"
down_revision = "0103_catalog_table_statistics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source_mirrors", sa.Column("effective_status", sa.String(32), nullable=True))
    connection = op.get_bind()
    mirrors = sa.table("source_mirrors", sa.column("source_id", sa.String(64)))
    after = ""
    with Session(bind=connection) as session:
        while True:
            source_ids = connection.scalars(sa.select(mirrors.c.source_id).distinct()
                                            .where(mirrors.c.source_id > after)
                                            .order_by(mirrors.c.source_id).limit(100)).all()
            if not source_ids:
                break
            for source_id in source_ids:
                refresh_source_status(session, source_id)
            after = source_ids[-1]
        session.flush()
    op.alter_column("source_mirrors", "effective_status", nullable=False)
    op.create_index("ix_source_mirrors_effective_status", "source_mirrors", ["effective_status"])


def downgrade() -> None:
    op.drop_index("ix_source_mirrors_effective_status", table_name="source_mirrors")
    op.drop_column("source_mirrors", "effective_status")
