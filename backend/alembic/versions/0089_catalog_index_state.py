"""Catalog-owned index readiness, separate from the shared purpose bit.

Revision ID: 0089_catalog_index_state
Revises: 0088_entity_embeddings

Copies the existing purpose ready bit so an installation that is ready stays
ready. Does not advance generation and does not enqueue a rebuild.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0089_catalog_index_state"
down_revision: Union[str, None] = "0088_entity_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE catalog_index_state (
            id varchar(32) NOT NULL,
            ready boolean NOT NULL,
            generation_last_swept integer,
            objects_written integer NOT NULL,
            columns_written integer NOT NULL,
            objects_failed integer NOT NULL,
            columns_failed integer NOT NULL,
            objects_attempted integer NOT NULL,
            columns_attempted integer NOT NULL,
            progress text,
            failure_summary text,
            rebuild_owed boolean NOT NULL,
            CONSTRAINT pk_catalog_index_state PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO catalog_index_state (
            id,
            ready,
            generation_last_swept,
            objects_written,
            columns_written,
            objects_failed,
            columns_failed,
            objects_attempted,
            columns_attempted,
            progress,
            failure_summary,
            rebuild_owed
        )
        SELECT
            'catalog',
            ready,
            CASE WHEN ready THEN generation ELSE NULL END,
            0,
            0,
            0,
            0,
            0,
            0,
            NULL,
            NULL,
            false
        FROM model_service_purposes
        WHERE purpose = 'embedding'
        """
    )
    op.execute(
        """
        INSERT INTO catalog_index_state (
            id,
            ready,
            generation_last_swept,
            objects_written,
            columns_written,
            objects_failed,
            columns_failed,
            objects_attempted,
            columns_attempted,
            progress,
            failure_summary,
            rebuild_owed
        )
        SELECT
            'catalog',
            false,
            NULL,
            0,
            0,
            0,
            0,
            0,
            0,
            NULL,
            NULL,
            false
        WHERE NOT EXISTS (
            SELECT 1 FROM catalog_index_state WHERE id = 'catalog'
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE catalog_index_state")
