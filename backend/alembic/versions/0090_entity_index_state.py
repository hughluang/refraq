"""Entity-owned index readiness, separate from Catalog.

Revision ID: 0090_entity_index_state
Revises: 0089_catalog_index_state

Starts not ready. Does not copy the Catalog bit and does not enqueue a refill.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0090_entity_index_state"
down_revision: Union[str, None] = "0089_catalog_index_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_index_state (
            id varchar(32) NOT NULL,
            ready boolean NOT NULL,
            generation integer,
            written integer NOT NULL,
            failed integer NOT NULL,
            attempted integer NOT NULL,
            progress text,
            failure_summary text,
            rebuild_owed boolean NOT NULL,
            CONSTRAINT pk_entity_index_state PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO entity_index_state (
            id,
            ready,
            generation,
            written,
            failed,
            attempted,
            progress,
            failure_summary,
            rebuild_owed
        )
        VALUES (
            'entity',
            false,
            NULL,
            0,
            0,
            0,
            NULL,
            NULL,
            false
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE entity_index_state")
